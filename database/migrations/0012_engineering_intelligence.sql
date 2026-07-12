-- Atlas Migration 0012: Engineering Intelligence (Code store)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Stage 2 / Sprint 19 (D11 / §5d): the higher-order learners that climb the Learning
-- Levels (§5d.6). S18b landed the governance ledger + Experience store; S19 "adds
-- sinks, not schema" — the **Code store** is the first non-Experience sink promoted
-- through the same governed, reversible ledger (`learning.events`).
--
--   * `learning.repositories` — L2 (Understand): a repository parsed by CodeCapability
--     (S14) and distilled to its structure (languages/frameworks/entry points/graph
--     size/per-repo patterns). Rows are created/deactivated via the learning ledger so
--     repository learning stays explainable & reversible.
--   * `learning.patterns` — L4 (Generalize): engineering patterns generalized *across*
--     the learned repositories ("you always use the Repository pattern"), each with a
--     prevalence. This is a materialised, recomputable view over the L2 rows that
--     powers L5 (Recommend). `status='reverted'` retires a generalization.

CREATE TABLE IF NOT EXISTS learning.repositories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    root            TEXT NOT NULL,
    languages       JSONB NOT NULL DEFAULT '{}',   -- lang -> file count
    frameworks      JSONB NOT NULL DEFAULT '[]',
    entry_points    JSONB NOT NULL DEFAULT '[]',
    dependencies    JSONB NOT NULL DEFAULT '{}',    -- manager -> [deps]
    file_count      INTEGER NOT NULL DEFAULT 0,
    symbol_count    INTEGER NOT NULL DEFAULT 0,
    loc             INTEGER NOT NULL DEFAULT 0,
    summary         TEXT NOT NULL DEFAULT '',
    top_symbols     JSONB NOT NULL DEFAULT '[]',
    patterns        JSONB NOT NULL DEFAULT '[]',    -- per-repo mined patterns (§5b.1)
    policy          TEXT NOT NULL DEFAULT 'project',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT learning_repositories_status_check CHECK (status IN ('active', 'reverted'))
);

CREATE INDEX IF NOT EXISTS idx_learning_repositories_status_created
    ON learning.repositories (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_repositories_root_active
    ON learning.repositories (root) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS learning.patterns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'engineering',
    description     TEXT NOT NULL DEFAULT '',
    prevalence      DOUBLE PRECISION NOT NULL DEFAULT 0,  -- fraction of repos (0..1)
    repo_count      INTEGER NOT NULL DEFAULT 0,
    total_repos     INTEGER NOT NULL DEFAULT 0,
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 0,
    level           INTEGER NOT NULL DEFAULT 4,
    evidence        JSONB NOT NULL DEFAULT '[]',          -- repo names supporting it
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT learning_patterns_status_check CHECK (status IN ('active', 'reverted'))
);

CREATE INDEX IF NOT EXISTS idx_learning_patterns_status_prevalence
    ON learning.patterns (status, prevalence DESC);
