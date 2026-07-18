-- Atlas Migration 0019: Asset Store (Phase 0 · ATLAS_OS_ROADMAP §5.9, P8)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Assets ARE NOT knowledge. An asset is a raw, versioned source artifact (a git repo,
-- a PDF, a DWG/CAD file, a MATLAB project, an image, …) from which knowledge is later
-- extracted. Bytes live in the Storage Manager (migration 0018); this schema is the
-- logical registry that groups those stored blobs into versioned assets so knowledge
-- provenance can reference a stable (asset_id, version) instead of a raw file path.
--
-- Loose coupling: storage_file_id is a SOFT reference to storage.files(id) (no
-- cross-schema FK) — the Asset Store re-fetches bytes via (scope, name, version).

CREATE SCHEMA IF NOT EXISTS asset AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS asset.assets (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind             TEXT NOT NULL,           -- git_repo | pdf | dwg | image | matlab | …
    name             TEXT NOT NULL,           -- logical label, unique within a kind
    source_uri       TEXT,                    -- where it came from (url/path), optional
    current_version  INTEGER NOT NULL DEFAULT 0,
    content_type     TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_assets_kind_name_uniq UNIQUE (kind, name)
);

CREATE INDEX IF NOT EXISTS idx_asset_assets_kind ON asset.assets (kind);

CREATE TABLE IF NOT EXISTS asset.versions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id         UUID NOT NULL REFERENCES asset.assets(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL,
    storage_scope    TEXT NOT NULL,           -- how to re-fetch bytes from storage.files
    storage_name     TEXT NOT NULL,
    storage_version  INTEGER NOT NULL,
    storage_file_id  UUID,                    -- soft ref → storage.files(id)
    checksum         TEXT NOT NULL,           -- sha256 hex (mirrors the stored blob)
    size_bytes       BIGINT NOT NULL DEFAULT 0,
    content_type     TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_versions_version_check CHECK (version >= 1),
    CONSTRAINT asset_versions_asset_version_uniq UNIQUE (asset_id, version)
);

CREATE INDEX IF NOT EXISTS idx_asset_versions_asset
    ON asset.versions (asset_id, version DESC);
