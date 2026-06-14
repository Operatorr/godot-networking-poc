// Package content holds the data-driven game-content domain for the CMS — the
// enemy / item / spell / projectile definitions and balance patches that
// designers edit without a game rebuild.
//
// See docs/CMS.md and docs/gdd/index.md ("Data-Driven Content System").
//
// STATUS: scaffold. Nothing here is wired into the live API yet. The live,
// authoritative content is still the JSON under client/data/** that the Rust
// server and the Godot client consume. This package sketches the SERVER side of
// the future CMS: a versioned content store the web editors write to, which
// publishes the JSON artifacts the game downloads (the "publish -> JSON/CDN ->
// version-check hot reload" flow in docs/CMS.md).
package content

import "time"

// Kind enumerates the editable content domains the CMS manages. Each maps to a
// JSON schema under client/data/schemas/<kind>_schema.json.
type Kind string

const (
	KindEnemy      Kind = "enemy"
	KindItem       Kind = "item"
	KindSpell      Kind = "spell"
	KindProjectile Kind = "projectile"
	KindBalance    Kind = "balance"
)

// Definition is one versioned content record. Payload is validated against the
// matching data/schemas/<kind>_schema.json before it may be published.
type Definition struct {
	ID        string         `json:"id"`
	Kind      Kind           `json:"kind"`
	Version   int            `json:"version"`
	Payload   map[string]any `json:"payload"`
	Draft     bool           `json:"draft"`
	UpdatedAt time.Time      `json:"updated_at"`
}

// Store is the persistence seam for content definitions (Postgres-backed in the
// real implementation; see api/database/migrations/0002_content_cms.sql).
//
// TODO: implement a PostgresStore and inject it into handlers.ContentHandler.
type Store interface {
	// List returns every definition of a kind (drafts included for editors).
	List(kind Kind) ([]Definition, error)
	// Get returns one definition by kind + id.
	Get(kind Kind, id string) (Definition, error)
	// Upsert creates or updates a draft definition.
	Upsert(def Definition) error
	// Publish validates all drafts of a kind, exports the JSON artifact (CDN),
	// bumps the content version, and returns the artifact URL.
	Publish(kind Kind) (artifactURL string, err error)
}
