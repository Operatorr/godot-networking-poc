package handlers

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"regexp"

	"github.com/omega-realm/api/internal/content"
	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/middleware"
)

// ContentHandler serves the CMS content-editor API — the enemy/item/spell/
// projectile/balance editors and the balance dashboard described in docs/CMS.md
// and docs/gdd/index.md.
//
// Every endpoint is gated by requireAdmin (users.is_admin), NOT plain JWT: the
// routes are registered behind middleware.RequireAuth in cmd/server/main.go, and
// each handler additionally checks the admin flag. The store is the Postgres-backed
// content.Store persisting the content_definitions / content_releases tables.
type ContentHandler struct {
	// db backs the admin check (SELECT is_admin FROM users).
	db *database.DB
	// store is the content persistence seam (PostgresStore in production).
	store content.Store
}

// NewContentHandler constructs the CMS handler over the shared DB and content store.
func NewContentHandler(db *database.DB, store content.Store) *ContentHandler {
	return &ContentHandler{db: db, store: store}
}

// contentIDPattern restricts definition ids to a filesystem/URL-safe slug, since an
// id becomes part of the published artifact path and the in-game lookup key.
var contentIDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// requireAdmin authorizes a CMS request: the caller must be authenticated (JWT
// claims present) AND flagged users.is_admin = true. It mirrors internal.go's
// dev opt-in — if ALLOW_INSECURE_CMS=true the check is bypassed entirely (local
// dev only, never production). On failure it writes the JSON error + status and
// returns false; callers must return immediately when it does.
func (h *ContentHandler) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	w.Header().Set("Content-Type", "application/json")

	// Explicit dev opt-in: skip the admin check entirely for the local stack.
	if os.Getenv("ALLOW_INSECURE_CMS") == "true" {
		return true
	}

	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return false
	}

	var isAdmin bool
	err := h.db.QueryRow(`SELECT is_admin FROM users WHERE id = $1`, claims.UserID).Scan(&isAdmin)
	if err == sql.ErrNoRows {
		// Token references a user that no longer exists.
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return false
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to verify admin"})
		return false
	}
	if !isAdmin {
		w.WriteHeader(http.StatusForbidden)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Admin access required"})
		return false
	}
	return true
}

// parseKind reads the {kind} path value and validates it against the content.Kind
// set. On an unknown kind it writes a 400 and returns ok=false.
func parseKind(w http.ResponseWriter, r *http.Request) (content.Kind, bool) {
	kind, ok := content.ParseKind(r.PathValue("kind"))
	if !ok {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unknown content kind"})
		return "", false
	}
	return kind, true
}

// ListDefinitions: GET /api/content/{kind} — list all definitions of a kind
// (drafts included, for the editors).
func (h *ContentHandler) ListDefinitions(w http.ResponseWriter, r *http.Request) {
	if !h.requireAdmin(w, r) {
		return
	}
	kind, ok := parseKind(w, r)
	if !ok {
		return
	}

	defs, err := h.store.List(kind)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to list definitions"})
		return
	}
	if defs == nil {
		defs = []content.Definition{}
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"kind":        string(kind),
		"definitions": defs,
	})
}

// GetDefinition: GET /api/content/{kind}/{id} — fetch one definition (404 if missing).
func (h *ContentHandler) GetDefinition(w http.ResponseWriter, r *http.Request) {
	if !h.requireAdmin(w, r) {
		return
	}
	kind, ok := parseKind(w, r)
	if !ok {
		return
	}

	id := r.PathValue("id")
	def, err := h.store.Get(kind, id)
	if errors.Is(err, content.ErrNotFound) {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Definition not found"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch definition"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(def)
}

// upsertRequest is the body for UpsertDefinition. Draft defaults to false when
// omitted; the editors send draft=true while iterating, then Publish clears it.
type upsertRequest struct {
	ID      string         `json:"id"`
	Payload map[string]any `json:"payload"`
	Draft   bool           `json:"draft"`
}

// UpsertDefinition: POST /api/content/{kind} — create/update a draft definition.
func (h *ContentHandler) UpsertDefinition(w http.ResponseWriter, r *http.Request) {
	if !h.requireAdmin(w, r) {
		return
	}
	kind, ok := parseKind(w, r)
	if !ok {
		return
	}

	var req upsertRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}
	if req.ID == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "id is required"})
		return
	}
	if !contentIDPattern.MatchString(req.ID) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "id must match ^[a-zA-Z0-9_-]+$"})
		return
	}

	err := h.store.Upsert(content.Definition{
		Kind:    kind,
		ID:      req.ID,
		Payload: req.Payload,
		Draft:   req.Draft,
	})
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to save definition"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(OKResponse{OK: true})
}

// PublishKind: POST /api/content/{kind}/publish — clear the kind's drafts, bump the
// released content version, and return the artifact URL the game downloads.
func (h *ContentHandler) PublishKind(w http.ResponseWriter, r *http.Request) {
	if !h.requireAdmin(w, r) {
		return
	}
	kind, ok := parseKind(w, r)
	if !ok {
		return
	}

	artifactURL, err := h.store.Publish(kind)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to publish"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"artifact_url": artifactURL,
	})
}

// BalanceDashboard: GET /api/admin/balance/dashboard — tuning analytics
// (most-used items, time-to-kill, win-rates by class; see docs/CMS.md).
//
// HONEST STATUS: there is no telemetry backend yet, so there is nothing to
// aggregate. Rather than 501, this returns 200 with an empty-but-shaped body so
// an admin UI can render an "analytics coming soon" panel without erroring.
func (h *ContentHandler) BalanceDashboard(w http.ResponseWriter, r *http.Request) {
	if !h.requireAdmin(w, r) {
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"status":  "analytics_not_implemented",
		"message": "Balance analytics are not yet implemented: no telemetry backend exists to aggregate item usage, time-to-kill, or win-rates.",
		"see":     "docs/CMS.md",
		"metrics": map[string]any{},
	})
}
