-- Atlas Migration 0018: Storage Manager (Phase 0 · ATLAS_OS_ROADMAP §5.8, P8)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- One subsystem through which all durable files flow: versioned, checksummed file
-- registry (storage.files) + per-scope advisory quotas (storage.quotas). Objects are
-- referenced fully-qualified (storage.*); the schema is intentionally NOT added to the
-- atlas role search_path (mirrors learning.*).
--
-- Hot/warm/cold TIERING IS DEFERRED (single disk today, R2): the `tier` column ships
-- now (default 'hot') so the data model is forward-compatible, but no tier-move logic
-- exists until a second disk is added.

CREATE SCHEMA IF NOT EXISTS storage AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS storage.files (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope         TEXT NOT NULL,
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    relpath       TEXT NOT NULL,            -- path relative to the storage root (portable)
    size_bytes    BIGINT NOT NULL DEFAULT 0,
    checksum      TEXT NOT NULL,            -- sha256 hex of the stored bytes
    tier          TEXT NOT NULL DEFAULT 'hot',
    content_type  TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT storage_files_tier_check CHECK (tier IN ('hot', 'warm', 'cold')),
    CONSTRAINT storage_files_version_check CHECK (version >= 1),
    CONSTRAINT storage_files_scope_name_version_uniq UNIQUE (scope, name, version)
);

CREATE INDEX IF NOT EXISTS idx_storage_files_scope_name
    ON storage.files (scope, name, version DESC);

CREATE INDEX IF NOT EXISTS idx_storage_files_tier
    ON storage.files (tier);

-- Per-scope quotas. Phase 0 keeps enforcement OFF (advisory/warn only, R2/A2); the
-- `enforce` flag exists so enforcement can be switched on later without a migration.
CREATE TABLE IF NOT EXISTS storage.quotas (
    scope        TEXT PRIMARY KEY,
    limit_bytes  BIGINT NOT NULL,
    enforce      BOOLEAN NOT NULL DEFAULT false,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
