-- Migration 0002 — Content CMS (APPLIED via InitSchema)
--
-- Backs the data-driven content CMS (docs/CMS.md): the versioned store of
-- enemy / item / spell / projectile definitions and balance patches that
-- designers edit, then publish to the JSON artifacts the game downloads.
--
-- STATUS: APPLIED. This DDL is the source-of-truth mirror of the inline schema
-- string in InitSchema() (api/internal/database/database.go) — that inline
-- string is what actually runs at startup (api/database/schema.sql is NOT
-- auto-applied). Keep this file in sync with that block. Every statement is
-- idempotent so it is safe to re-run against an existing database.

-- Admin flag gates the CMS editor endpoints to designers, not every player.
-- Added idempotently so already-running databases pick it up (defaults false).
-- Grant a designer admin access with:
--   UPDATE users SET is_admin = true WHERE username = '<name>';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;

-- One versioned content record per (kind, id). `payload` is validated against
-- client/data/schemas/<kind>_schema.json before a draft may be published.
-- `version` stays stable on edit; Publish bumps the released version (tracked in
-- content_releases below).
CREATE TABLE IF NOT EXISTS content_definitions (
    kind       TEXT NOT NULL,             -- enemy | item | spell | projectile | balance
    id         TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    payload    JSONB NOT NULL,
    draft      BOOLEAN NOT NULL DEFAULT true,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (kind, id)
);

-- Tracks the currently-published content version per kind (the value the game's
-- version-check compares against to decide whether to re-download artifacts).
CREATE TABLE IF NOT EXISTS content_releases (
    kind         TEXT PRIMARY KEY,
    version      INTEGER NOT NULL,
    artifact_url TEXT,
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes: list-by-kind for the editors, and a (kind, draft) index for the
-- "drafts of a kind" / "published of a kind" lookups Publish and the editors run.
CREATE INDEX IF NOT EXISTS idx_content_definitions_kind ON content_definitions(kind);
CREATE INDEX IF NOT EXISTS idx_content_definitions_kind_draft ON content_definitions(kind, draft);
