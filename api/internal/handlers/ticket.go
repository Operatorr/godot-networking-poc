package handlers

import (
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"strings"

	"github.com/omega-realm/api/internal/auth"
	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/middleware"
	"github.com/omega-realm/api/internal/models"
)

// LoadTestCharacterIDMin is the lowest character_id the load-test endpoint will mint a
// ticket for. The game server excludes ids >= 1_000_000 from ALL Postgres I/O — no
// progression hydrate, no progress write-back, no death/permadeath (see
// rust/server/src/sim/world.rs, the `character_id < 1_000_000` guards). Refusing to sign
// anything lower means a leaked LOAD_TEST_TICKET_SECRET still cannot mint a ticket that
// touches a real character row — its blast radius is confined to harmless synthetic bots.
const LoadTestCharacterIDMin uint32 = 1_000_000

// TicketHandler issues short-lived Ed25519 session tickets that the authoritative game
// server verifies locally — no per-join API round-trip on the connect hot path. The
// signing key lives only here; the server holds the public half. See
// api/internal/auth/ticket.go and docs/server/design.md (Auth).
type TicketHandler struct {
	db     *database.DB
	signer *auth.TicketSigner // nil => signing not configured (server is in unsigned/dev mode)
}

// NewTicketHandler constructs a TicketHandler. signer may be nil.
func NewTicketHandler(db *database.DB, signer *auth.TicketSigner) *TicketHandler {
	return &TicketHandler{db: db, signer: signer}
}

// TicketRequest optionally pins the region the ticket is minted for. Empty falls back to
// the JWT's region claim, then to Asia (the default instance region).
type TicketRequest struct {
	RegionID string `json:"region_id"`
}

// TicketResponse carries the base64-encoded 86-byte ticket blob the client presents in
// ConnectAuth, plus metadata for display/refresh.
type TicketResponse struct {
	Ticket      string `json:"ticket"`        // base64 of the 86-byte blob
	CharacterID int    `json:"character_id"`  // the bound character (characters.id)
	Region      string `json:"region"`        // resolved region id
	ExpiresAtMs uint64 `json:"expires_at_ms"` // unix ms; expiry IS the revocation story
}

// IssueTicket mints a session ticket for the authenticated user's OWN character.
//
// POST /api/character/ticket  (JWT-protected)
func (h *TicketHandler) IssueTicket(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	// Fail closed when no signing key is configured. The game server is then presumably
	// running with --allow-unsigned-tickets, so the client should simply join with an
	// empty ticket; a 503 here tells it "no ticket to hand out" rather than 500-ing.
	if h.signer == nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Ticket signing not configured (set OMEGA_TICKET_PRIVKEY); join unsigned instead",
		})
		return
	}

	// Region: explicit body wins, then the JWT region claim, then Asia.
	var req TicketRequest
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&req) // body is optional; ignore decode errors
	}
	regionID := strings.ToLower(strings.TrimSpace(req.RegionID))
	if regionID == "" {
		regionID = strings.ToLower(strings.TrimSpace(claims.Region))
	}
	if regionID == "" {
		regionID = models.RegionAsia
	}
	if !models.IsValidRegion(regionID) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid region"})
		return
	}

	// The ticket binds the caller's OWN character (looked up by the authenticated user
	// id), so a client can never request a ticket for someone else's character.
	var characterID int
	err := h.db.QueryRow(`SELECT id FROM characters WHERE user_id = $1`, claims.UserID).Scan(&characterID)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "No character for this user"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}
	// character_id rides the wire as a u32; guard the cast.
	if characterID <= 0 || int64(characterID) > int64(math.MaxUint32) {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character id out of range"})
		return
	}

	blob, expiresMs := h.signer.Mint(uint32(characterID), auth.RegionToWire(regionID))

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(TicketResponse{
		Ticket:      base64.StdEncoding.EncodeToString(blob),
		CharacterID: characterID,
		Region:      regionID,
		ExpiresAtMs: expiresMs,
	})
}

// LoadTestTicketRequest is the body for IssueLoadTestTicket: the synthetic character_id
// the bot will present (must be >= LoadTestCharacterIDMin) and the region to pin.
type LoadTestTicketRequest struct {
	CharacterID uint32 `json:"character_id"`
	RegionID    string `json:"region_id"`
}

// IssueLoadTestTicket mints a signed ticket for a SYNTHETIC load-test bot — no user
// account required.
//
// POST /api/loadtest/ticket  (guarded by X-Loadtest-Token vs LOAD_TEST_TICKET_SECRET)
//
// It exists so the bot swarm can authenticate against a fail-closed live server WITHOUT
// opening unsigned tickets. To keep a leaked secret harmless it only mints character_ids
// in the synthetic range (>= LoadTestCharacterIDMin), which the game server excludes from
// all database I/O — so a load-test ticket can never read or corrupt a real character.
func (h *TicketHandler) IssueLoadTestTicket(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !requireLoadTestSecret(w, r) {
		return
	}
	if h.signer == nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Ticket signing not configured (set OMEGA_TICKET_PRIVKEY)",
		})
		return
	}

	var req LoadTestTicketRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}
	if req.CharacterID < LoadTestCharacterIDMin {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: fmt.Sprintf("character_id must be >= %d (synthetic load-test range)", LoadTestCharacterIDMin),
		})
		return
	}

	regionID := strings.ToLower(strings.TrimSpace(req.RegionID))
	if regionID == "" {
		regionID = models.RegionAsia
	}
	if !models.IsValidRegion(regionID) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid region"})
		return
	}

	blob, expiresMs := h.signer.Mint(req.CharacterID, auth.RegionToWire(regionID))

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(TicketResponse{
		Ticket:      base64.StdEncoding.EncodeToString(blob),
		CharacterID: int(req.CharacterID),
		Region:      regionID,
		ExpiresAtMs: expiresMs,
	})
}
