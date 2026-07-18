-- Atlas Migration 0021: Mission Manager + Journal (Phase A · PHASE_A_PLAN §A.1)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- The Mission layer above Jobs (the single most important structural addition in the
-- roadmap). A Mission is a long-lived, operator-created objective that owns Jobs and
-- (later) Persistent Workers, runs off a versioned Configuration, and records every
-- important action in an append-only Journal (P9 explainability; refs, never copies).
--
-- Also adds mission provenance (`mission_id`) to every row Atlas creates *because of* a
-- mission (jobs, findings, experiences, assets, events), so "show me everything Mission X
-- produced" is a filter, not a join graph. All columns are NULLABLE + back-compatible:
-- non-mission work simply leaves them NULL. The mission is PROVENANCE only — archiving or
-- deleting a mission never deletes the knowledge/assets it produced (soft references, no FK).

CREATE SCHEMA IF NOT EXISTS mission AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS mission.missions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    objective          TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'draft',
    success_criteria   JSONB NOT NULL DEFAULT '{}',
    knowledge_domains  TEXT[] NOT NULL DEFAULT '{}',
    active_config_id   UUID,                          -- → config.mission_configs (A.2, soft ref)

    -- arbitration (A.6 / A7): operator knob = scheduling_policy; priority/criticality refine.
    scheduling_policy  TEXT NOT NULL DEFAULT 'background',
    priority           INTEGER NOT NULL DEFAULT 0,
    criticality        TEXT NOT NULL DEFAULT 'normal',
    budget             JSONB NOT NULL DEFAULT '{}',   -- Phase A: {max_concurrent_tasks} only (B1)
    deadline           TIMESTAMPTZ,                   -- advisory in v1
    importance         TEXT,                          -- advisory in v1

    -- identity / provenance (architect): labels for filtering; metadata separate from config.
    labels             TEXT[] NOT NULL DEFAULT '{}',
    metadata           JSONB NOT NULL DEFAULT '{}',   -- created_by, description, owner, notes
    template_id        UUID,                          -- → mission.templates (A.5, soft ref)
    template_version   INTEGER,                       -- stamped at instantiation (B7)

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mission_missions_status_check CHECK (
        status IN ('draft', 'active', 'waiting', 'paused', 'completed', 'archived')
    ),
    CONSTRAINT mission_missions_policy_check CHECK (
        scheduling_policy IN ('realtime', 'background', 'batch', 'idle', 'exclusive')
    ),
    CONSTRAINT mission_missions_criticality_check CHECK (
        criticality IN ('low', 'normal', 'high', 'critical')
    ),
    CONSTRAINT mission_missions_priority_check CHECK (priority >= 0 AND priority <= 100)
);

CREATE INDEX IF NOT EXISTS idx_mission_missions_status
    ON mission.missions (status, created_at DESC);

-- GIN index so `list?label=finance` (labels @> ARRAY['finance']) is fast.
CREATE INDEX IF NOT EXISTS idx_mission_missions_labels
    ON mission.missions USING GIN (labels);

-- Append-only forensic + explainability log (P9/A8). Stores REFS (ids) + a short reason,
-- never full payloads, so it stays small over a mission's multi-month life.
CREATE TABLE IF NOT EXISTS mission.journal (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id  UUID NOT NULL REFERENCES mission.missions(id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    action      TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    refs        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mission_journal_mission_ts
    ON mission.journal (mission_id, ts DESC);

-- Mission provenance on every mission-generated row (soft, nullable, no cross-schema FK).
ALTER TABLE job.jobs             ADD COLUMN IF NOT EXISTS mission_id UUID;
ALTER TABLE knowledge.findings   ADD COLUMN IF NOT EXISTS mission_id UUID;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS mission_id UUID;
ALTER TABLE asset.assets         ADD COLUMN IF NOT EXISTS mission_id UUID;
ALTER TABLE audit.events         ADD COLUMN IF NOT EXISTS mission_id UUID;

CREATE INDEX IF NOT EXISTS idx_job_jobs_mission
    ON job.jobs (mission_id) WHERE mission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_knowledge_findings_mission
    ON knowledge.findings (mission_id) WHERE mission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_learning_experiences_mission
    ON learning.experiences (mission_id) WHERE mission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_asset_assets_mission
    ON asset.assets (mission_id) WHERE mission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_events_mission
    ON audit.events (mission_id) WHERE mission_id IS NOT NULL;
