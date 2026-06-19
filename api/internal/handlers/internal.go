package handlers

import (
	"crypto/subtle"
	"database/sql"
	"encoding/json"
	"net/http"
	"os"
	"strconv"

	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/progression"
)

// InternalHandler serves server-only endpoints used by the authoritative Rust game
// server to read and write character progression and to settle Glory on death. These
// routes are NOT JWT-protected; they are guarded by a shared server token instead
// (header X-Server-Token vs env SERVER_API_TOKEN), mirroring the region heartbeat.
type InternalHandler struct {
	db *database.DB
}

// NewInternalHandler constructs an InternalHandler.
func NewInternalHandler(db *database.DB) *InternalHandler {
	return &InternalHandler{db: db}
}

// requireServerToken validates the X-Server-Token header against SERVER_API_TOKEN.
// These endpoints mutate the Glory economy and delete characters, so they FAIL CLOSED:
// when SERVER_API_TOKEN is unset the request is rejected 401, unless the operator has
// explicitly opted into the insecure dev path by setting ALLOW_INSECURE_INTERNAL=true
// (used for the local stack, never in production). Returns true if the request may proceed.
func requireServerToken(w http.ResponseWriter, r *http.Request) bool {
	expectedToken := os.Getenv("SERVER_API_TOKEN")
	if expectedToken == "" {
		if os.Getenv("ALLOW_INSECURE_INTERNAL") == "true" {
			return true // explicit dev opt-in: internal routes are unauthenticated
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Internal endpoints unconfigured (set SERVER_API_TOKEN)"})
		return false
	}
	if !serverTokenValid(r.Header.Get("X-Server-Token"), expectedToken) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return false
	}
	return true
}

// serverTokenValid reports whether the presented token matches the expected one
// using a constant-time comparison, so the handler does not leak the token length
// or contents through response timing. Shared by the internal endpoints and the
// region heartbeat.
func serverTokenValid(got, expected string) bool {
	return subtle.ConstantTimeCompare([]byte(got), []byte(expected)) == 1
}

// requireLoadTestSecret guards the load-test ticket endpoint with LOAD_TEST_TICKET_SECRET
// (header X-Loadtest-Token). It FAILS CLOSED and — unlike requireServerToken — has NO
// ALLOW_INSECURE_INTERNAL bypass: an unset secret means 503, so the endpoint is dormant in
// normal production and only live when an operator deliberately sets the secret for a
// load-test session. (Local load tests run against an unsigned dev server and never need
// this endpoint.) Returns true if the request may proceed.
func requireLoadTestSecret(w http.ResponseWriter, r *http.Request) bool {
	expected := os.Getenv("LOAD_TEST_TICKET_SECRET")
	if expected == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Load-test ticket endpoint disabled (set LOAD_TEST_TICKET_SECRET)"})
		return false
	}
	if !serverTokenValid(r.Header.Get("X-Loadtest-Token"), expected) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return false
	}
	return true
}

// CharacterProgressResponse is the body returned by GetCharacter.
type CharacterProgressResponse struct {
	Level      int    `json:"level"`
	Experience int    `json:"experience"`
	Mode       string `json:"mode"`
}

// ProgressRequest is the body for the progress-update endpoint. Level and
// Experience are pointers so an OMITTED field is rejected (nil) rather than
// silently decoding to 0 and zeroing a character's progression.
type ProgressRequest struct {
	Level      *int `json:"level"`
	Experience *int `json:"experience"`
}

// OKResponse is a minimal success body for endpoints with nothing else to return.
type OKResponse struct {
	OK bool `json:"ok"`
}

// DeathResponse is the body returned by the death endpoint.
type DeathResponse struct {
	GloryAwarded     int64 `json:"glory_awarded"`
	CharacterDeleted bool  `json:"character_deleted"`
}

// GetCharacter returns level/experience/mode for the character with the given id
// (the characters.id primary key, NOT user_id). 404 if missing.
//
// GET /api/internal/characters/{id}
func (h *InternalHandler) GetCharacter(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	var resp CharacterProgressResponse
	err := h.db.QueryRow(
		`SELECT level, experience, mode FROM characters WHERE id = $1`, id,
	).Scan(&resp.Level, &resp.Experience, &resp.Mode)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp)
}

// UpdateProgress writes level + experience for the character with the given id.
// Both fields are required (omitted => 400, so a partial body can't zero out
// progression) and must fall on the shared progression curve: 1 <= level <=
// MaxPlayerLevel and 0 <= experience < XPToNextLevel(level). Progression is
// monotonic, so the write is guarded with a WHERE clause that refuses to move a
// character backwards: it only applies when the new (level, experience) is
// strictly ahead of the stored value. An in-range request that loses this race
// (the stored row is already further along) is treated as a no-op success.
//
// POST /api/internal/characters/{id}/progress
func (h *InternalHandler) UpdateProgress(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	var req ProgressRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}
	if req.Level == nil || req.Experience == nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Both level and experience are required"})
		return
	}

	level := *req.Level
	experience := *req.Experience
	if level < 1 || level > progression.MaxPlayerLevel {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "level out of range"})
		return
	}
	// experience is the in-level progress: it must be non-negative and below the
	// cost of advancing past the current level (0 at the cap, where the bar is full).
	maxExp := progression.XPToNextLevel(level)
	if experience < 0 || (maxExp > 0 && experience >= maxExp) || (maxExp == 0 && experience != 0) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "experience out of range for level"})
		return
	}

	// Monotonic write: only advance, never regress. The character must exist
	// (separate existence probe) but a stale/behind write is a benign no-op.
	var exists bool
	if err := h.db.QueryRow(`SELECT true FROM characters WHERE id = $1`, id).Scan(&exists); err != nil {
		if err == sql.ErrNoRows {
			w.WriteHeader(http.StatusNotFound)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
			return
		}
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	_, err := h.db.Exec(
		`UPDATE characters SET level = $1, experience = $2
		 WHERE id = $3 AND ($1 > level OR ($1 = level AND $2 > experience))`,
		level, experience, id,
	)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to update character"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(OKResponse{OK: true})
}

// Death settles a character death atomically. For hardcore (permadeath) characters
// it awards Glory (floor of lifetime XP / divisor) to the owning account and deletes
// the character, so its XP converts to Glory exactly once. Softcore characters
// survive death and receive NO Glory here (that would be farmable); their payout is
// the player-initiated church sacrifice instead.
//
// POST /api/internal/characters/{id}/death
func (h *InternalHandler) Death(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	tx, err := h.db.Begin()
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to start transaction"})
		return
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	var (
		level      int
		experience int
		mode       string
		userID     int
	)
	err = tx.QueryRow(
		`SELECT level, experience, mode, user_id FROM characters WHERE id = $1 FOR UPDATE`, id,
	).Scan(&level, &experience, &mode, &userID)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	// Glory is awarded only on permadeath (hardcore), where the character is also
	// deleted — so a given character's lifetime XP converts to Glory exactly once.
	// Softcore characters survive death (and could die repeatedly), so paying out
	// here would let them farm Glory without bound; their only payout is the
	// player-initiated church sacrifice (SacrificeCharacter), which deletes them.
	var glory int64
	characterDeleted := false
	if mode == "hardcore" {
		glory = progression.GloryFor(level, experience)
		if _, err := tx.Exec(
			`UPDATE users SET glory = glory + $1 WHERE id = $2`, glory, userID,
		); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to award glory"})
			return
		}
		if _, err := tx.Exec(`DELETE FROM characters WHERE id = $1`, id); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to delete character"})
			return
		}
		characterDeleted = true
	}

	if err := tx.Commit(); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to commit transaction"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(DeathResponse{
		GloryAwarded:     glory,
		CharacterDeleted: characterDeleted,
	})
}

// parsePathID reads and validates the {id} path value. On error it writes a 400 and
// returns ok=false.
func parsePathID(w http.ResponseWriter, r *http.Request) (int, bool) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil || id <= 0 {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid character id"})
		return 0, false
	}
	return id, true
}
