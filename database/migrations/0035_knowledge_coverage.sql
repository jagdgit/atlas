-- Atlas Migration 0035: knowledge.coverage (Phase C · PHASE_C_PLAN §C.4, A10/CC15)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Coverage map: for every (asset_version × reader) Atlas has processed, record WHAT was read and how
-- it went — the denominator behind "Python 100%, MATLAB 20%". Keyed on the same 4-tuple as the
-- Derived Artifact Store (asset_id, asset_version, reader, reader_version) so "was this asset read by
-- this reader version?" is one indexed lookup. `extractor_version` is stored (not keyed): bumping the
-- reader mints a NEW coverage row (old version's read is preserved for the reader-improved delta),
-- while bumping only the extractor updates the row in place — and both are stamped so targeted
-- re-extraction (A10) can enumerate exactly the assets processed by an older version.
--
-- Soft ref: asset_id has no cross-schema FK (matches 0027/0028); coverage is provenance/telemetry,
-- never a visibility filter.

CREATE TABLE IF NOT EXISTS knowledge.coverage (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id          UUID NOT NULL,                 -- soft ref → asset.assets(id)
    asset_version     INTEGER NOT NULL,
    reader            TEXT NOT NULL,                 -- document | code | ...
    reader_version    TEXT NOT NULL,
    extractor_version TEXT NOT NULL DEFAULT '',      -- extractor that ran (BB8); '' when N/A
    domain            TEXT NOT NULL DEFAULT 'external',
    source            TEXT,                          -- document | repo | ... (provenance source)
    repo_uid          TEXT,                          -- nullable: documents have no repo
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed | unsupported | empty
    findings_count    INTEGER NOT NULL DEFAULT 0,
    chunks_count      INTEGER NOT NULL DEFAULT 0,
    reason            TEXT,
    extracted_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_coverage
        UNIQUE (asset_id, asset_version, reader, reader_version),
    CONSTRAINT knowledge_coverage_status_check
        CHECK (status IN ('pending', 'done', 'failed', 'unsupported', 'empty'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_coverage_domain ON knowledge.coverage (domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_coverage_reader ON knowledge.coverage (reader, reader_version);
CREATE INDEX IF NOT EXISTS idx_knowledge_coverage_repo
    ON knowledge.coverage (repo_uid) WHERE repo_uid IS NOT NULL;
