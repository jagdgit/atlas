-- Atlas Migration 0017: Experience Learning richness (Stage 3B.5)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Extends the Experience store with a durable JSON payload (A3B.16) and a
-- component+version observation table (D3B.24 / A3B.17). Soft bias remains off
-- until an operator explicitly enables it after apply (D3B.12 / A3B.18).

ALTER TABLE learning.experiences
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}';

ALTER TABLE learning.experiences
    ADD COLUMN IF NOT EXISTS bias_enabled BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS learning.component_observations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component_key       TEXT NOT NULL,
    component_version   TEXT NOT NULL DEFAULT '1',
    corpus              TEXT,
    profile             TEXT,
    metrics             JSONB NOT NULL DEFAULT '{}',
    source_job_id       TEXT,
    experience_id       UUID REFERENCES learning.experiences(id) ON DELETE SET NULL,
    event_id            UUID REFERENCES learning.events(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_learning_component_obs_key
    ON learning.component_observations (component_key, component_version, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_learning_component_obs_job
    ON learning.component_observations (source_job_id)
    WHERE source_job_id IS NOT NULL;
