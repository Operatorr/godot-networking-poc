package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/omega-realm/api/internal/content"
)

// ContentHandler serves the CMS content-editor API — the enemy/item/spell
// editors and the balance dashboard described in docs/CMS.md and
// docs/gdd/index.md.
//
// STATUS: scaffold. Every endpoint returns 501 Not Implemented and the routes
// are NOT yet registered in cmd/server/main.go (see the commented block there).
// Wire them — behind an ADMIN-role check, not plain JWT — once content.Store and
// the content_definitions table (api/database/migrations/0002_content_cms.sql)
// exist.
type ContentHandler struct {
	// store is the persistence seam; nil until a PostgresStore is implemented.
	store content.Store
}

// NewContentHandler constructs the (currently storeless) CMS handler.
func NewContentHandler() *ContentHandler {
	return &ContentHandler{}
}

func contentNotImplemented(w http.ResponseWriter, feature string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusNotImplemented)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":   "not_implemented",
		"feature": feature,
		"see":     "docs/CMS.md",
	})
}

// ListDefinitions: GET /api/content/{kind} — list all definitions of a kind.
func (h *ContentHandler) ListDefinitions(w http.ResponseWriter, r *http.Request) {
	contentNotImplemented(w, "content.list:"+r.PathValue("kind"))
}

// GetDefinition: GET /api/content/{kind}/{id} — fetch one definition.
func (h *ContentHandler) GetDefinition(w http.ResponseWriter, r *http.Request) {
	contentNotImplemented(w, "content.get")
}

// UpsertDefinition: POST /api/content/{kind} — create/update a draft definition.
func (h *ContentHandler) UpsertDefinition(w http.ResponseWriter, r *http.Request) {
	contentNotImplemented(w, "content.upsert")
}

// PublishKind: POST /api/content/{kind}/publish — validate drafts, export the
// JSON artifact to the CDN, bump the content version.
func (h *ContentHandler) PublishKind(w http.ResponseWriter, r *http.Request) {
	contentNotImplemented(w, "content.publish")
}

// BalanceDashboard: GET /api/admin/balance/dashboard — tuning analytics
// (most-used items, time-to-kill, win-rates by class; see docs/CMS.md).
func (h *ContentHandler) BalanceDashboard(w http.ResponseWriter, r *http.Request) {
	contentNotImplemented(w, "content.balance_dashboard")
}
