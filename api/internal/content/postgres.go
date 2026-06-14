package content

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"

	"github.com/omega-realm/api/internal/database"
)

// PostgresStore is the Postgres-backed implementation of Store. It reads and
// writes the content_definitions / content_releases tables created by
// database.InitSchema (mirrored in api/database/migrations/0002_content_cms.sql).
type PostgresStore struct {
	db *database.DB
}

// NewPostgresStore wires a PostgresStore to the shared database connection.
func NewPostgresStore(db *database.DB) *PostgresStore {
	return &PostgresStore{db: db}
}

// compile-time assertion that PostgresStore satisfies the Store seam.
var _ Store = (*PostgresStore)(nil)

// List returns every definition of a kind (drafts included, for the editors),
// ordered by id for a stable editor listing.
func (s *PostgresStore) List(kind Kind) ([]Definition, error) {
	rows, err := s.db.Query(
		`SELECT id, version, payload, draft, updated_at
		   FROM content_definitions
		  WHERE kind = $1
		  ORDER BY id`,
		string(kind),
	)
	if err != nil {
		return nil, fmt.Errorf("content: list %s: %w", kind, err)
	}
	defer rows.Close()

	var defs []Definition
	for rows.Next() {
		def := Definition{Kind: kind}
		var payload []byte
		if err := rows.Scan(&def.ID, &def.Version, &payload, &def.Draft, &def.UpdatedAt); err != nil {
			return nil, fmt.Errorf("content: scan %s row: %w", kind, err)
		}
		if err := json.Unmarshal(payload, &def.Payload); err != nil {
			return nil, fmt.Errorf("content: unmarshal %s/%s payload: %w", kind, def.ID, err)
		}
		defs = append(defs, def)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("content: iterate %s rows: %w", kind, err)
	}
	return defs, nil
}

// Get returns one definition by kind + id. A missing row yields ErrNotFound.
func (s *PostgresStore) Get(kind Kind, id string) (Definition, error) {
	def := Definition{Kind: kind, ID: id}
	var payload []byte
	err := s.db.QueryRow(
		`SELECT id, version, payload, draft, updated_at
		   FROM content_definitions
		  WHERE kind = $1 AND id = $2`,
		string(kind), id,
	).Scan(&def.ID, &def.Version, &payload, &def.Draft, &def.UpdatedAt)
	if err == sql.ErrNoRows {
		return Definition{}, fmt.Errorf("content: %s/%s: %w", kind, id, ErrNotFound)
	}
	if err != nil {
		return Definition{}, fmt.Errorf("content: get %s/%s: %w", kind, id, err)
	}
	if err := json.Unmarshal(payload, &def.Payload); err != nil {
		return Definition{}, fmt.Errorf("content: unmarshal %s/%s payload: %w", kind, id, err)
	}
	return def, nil
}

// Upsert creates or updates a definition. New records start at version 1; on
// conflict only payload + draft + updated_by + updated_at change, so the stored
// version stays stable across edits (Publish is what bumps the version). The
// def.Draft flag is honored on both insert and update (editors send draft=true
// while iterating; Publish clears it). editorID is recorded as updated_by; 0
// stores NULL (e.g. the ALLOW_INSECURE_CMS dev bypass, where there are no JWT claims).
func (s *PostgresStore) Upsert(def Definition, editorID int) error {
	payload, err := json.Marshal(def.Payload)
	if err != nil {
		return fmt.Errorf("content: marshal %s/%s payload: %w", def.Kind, def.ID, err)
	}
	var updatedBy any // NULL unless we know the editing user (FK -> users.id).
	if editorID > 0 {
		updatedBy = editorID
	}
	_, err = s.db.Exec(
		`INSERT INTO content_definitions (kind, id, version, payload, draft, updated_by, updated_at)
		      VALUES ($1, $2, 1, $3, $4, $5, now())
		 ON CONFLICT (kind, id) DO UPDATE
		    SET payload    = EXCLUDED.payload,
		        draft      = EXCLUDED.draft,
		        updated_by = EXCLUDED.updated_by,
		        updated_at = now()`,
		string(def.Kind), def.ID, payload, def.Draft, updatedBy,
	)
	if err != nil {
		return fmt.Errorf("content: upsert %s/%s: %w", def.Kind, def.ID, err)
	}
	return nil
}

// Remove deletes a definition by kind + id. Deleting a row that does not exist is
// treated as success (idempotent delete), so a double-DELETE from the editor still
// returns 200.
func (s *PostgresStore) Remove(kind Kind, id string) error {
	if _, err := s.db.Exec(
		`DELETE FROM content_definitions WHERE kind = $1 AND id = $2`,
		string(kind), id,
	); err != nil {
		return fmt.Errorf("content: remove %s/%s: %w", kind, id, err)
	}
	return nil
}

// Publish marks every draft of a kind clean, bumps the released content version,
// and returns the artifact URL the game's version-check downloads.
//
// TODO: the real implementation must also validate each definition against its
// data/schemas/<kind>_schema.json and export the actual JSON artifact to the CDN
// (CONTENT_CDN_URL) at the returned path. For now it only advances the version
// and records where the artifact will live.
func (s *PostgresStore) Publish(kind Kind) (string, error) {
	tx, err := s.db.Begin()
	if err != nil {
		return "", fmt.Errorf("content: publish %s: begin tx: %w", kind, err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	// Clear the draft flag on all definitions of this kind.
	if _, err := tx.Exec(
		`UPDATE content_definitions SET draft = false WHERE kind = $1`,
		string(kind),
	); err != nil {
		return "", fmt.Errorf("content: publish %s: clear drafts: %w", kind, err)
	}

	// Next released version = current released version (0 if none) + 1.
	var nextVersion int
	if err := tx.QueryRow(
		`SELECT COALESCE((SELECT version FROM content_releases WHERE kind = $1), 0) + 1`,
		string(kind),
	).Scan(&nextVersion); err != nil {
		return "", fmt.Errorf("content: publish %s: compute version: %w", kind, err)
	}

	artifactURL := artifactURLFor(kind, nextVersion)

	if _, err := tx.Exec(
		`INSERT INTO content_releases (kind, version, artifact_url, published_at)
		      VALUES ($1, $2, $3, now())
		 ON CONFLICT (kind) DO UPDATE
		    SET version      = EXCLUDED.version,
		        artifact_url = EXCLUDED.artifact_url,
		        published_at = now()`,
		string(kind), nextVersion, artifactURL,
	); err != nil {
		return "", fmt.Errorf("content: publish %s: record release: %w", kind, err)
	}

	if err := tx.Commit(); err != nil {
		return "", fmt.Errorf("content: publish %s: commit: %w", kind, err)
	}
	return artifactURL, nil
}

// artifactURLFor builds the published artifact path: <base>/<kind>/<version>.json,
// where the base is CONTENT_CDN_URL (the CDN origin) or "/content" when unset.
func artifactURLFor(kind Kind, version int) string {
	base := os.Getenv("CONTENT_CDN_URL")
	if base == "" {
		base = "/content"
	}
	return fmt.Sprintf("%s/%s/%d.json", base, kind, version)
}
