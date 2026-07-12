-- Atlas Migration 0011: Learning Pipeline (learning schema)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`
-- (atlas owns the database, so it may create the schema itself — same pattern as
-- 0007's `agent`, 0009's `conversation`, and 0010's `job` schemas).
--
-- Stage 2 / Sprint 18b (D11 / §5d): Continuous Learning — the third pillar. Two
-- guarantees are baked into the schema:
--   1) Atlas NEVER silently learns. Every learning action is a row in
--      `learning.events` with what/why/from-where, a governance `policy`
--      (temporary/project/personal/verified) and a `status` (proposed → applied →
--      reverted). Promotion is explicit and REVERSIBLE.
--   2) The Experience store (`learning.experiences`) — the "missing fifth store" —
--      holds problem → diagnosis → actions → mistakes → solution → lessons so Atlas
--      can recall *how* it solved a class of problem, not just facts.

CREATE SCHEMA IF NOT EXISTS learning AUTHORIZATION atlas;

-- The governed, explainable, reversible ledger of every learning action.
-- `store` names the target knowledge store; `level` is the Learning Level (§5d.6:
-- 1 Store → 5 Recommend). `ref_id` points at the record created in the target store
-- (e.g. an experience id) once applied, so a revert can deactivate it.
CREATE TABLE IF NOT EXISTS learning.events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL,               -- job | repo | document | conversation | manual
    source_id       TEXT,
    store           TEXT NOT NULL,               -- experience | knowledge | code | memory | conversation
    policy          TEXT NOT NULL DEFAULT 'temporary',
    level           INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'proposed',
    summary         TEXT NOT NULL DEFAULT '',    -- WHAT was learned
    reason          TEXT NOT NULL DEFAULT '',    -- WHY it is worth learning
    origin          TEXT NOT NULL DEFAULT '',    -- FROM WHERE (human-readable provenance)
    project         TEXT,                        -- for the Project policy
    ref_id          TEXT,                        -- id of the created store record (once applied)
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    CONSTRAINT learning_events_policy_check CHECK (
        policy IN ('temporary', 'project', 'personal', 'verified')
    ),
    CONSTRAINT learning_events_status_check CHECK (
        status IN ('proposed', 'applied', 'reverted')
    ),
    CONSTRAINT learning_events_level_check CHECK (level BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_learning_events_status_created
    ON learning.events (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_events_store
    ON learning.events (store, created_at DESC);

-- The Experience store (§5d.2): lessons learned, keyed for recall. `status`
-- 'reverted' hides an experience without deleting the audit trail (reversible).
CREATE TABLE IF NOT EXISTS learning.experiences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL DEFAULT '',
    problem         TEXT NOT NULL DEFAULT '',
    diagnosis       TEXT NOT NULL DEFAULT '',
    actions         JSONB NOT NULL DEFAULT '[]',  -- ordered commands / steps taken
    mistakes        TEXT NOT NULL DEFAULT '',
    solution        TEXT NOT NULL DEFAULT '',
    lessons         TEXT NOT NULL DEFAULT '',
    tags            JSONB NOT NULL DEFAULT '[]',
    source_job_id   TEXT,
    policy          TEXT NOT NULL DEFAULT 'temporary',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT learning_experiences_status_check CHECK (
        status IN ('active', 'reverted')
    )
);

CREATE INDEX IF NOT EXISTS idx_learning_experiences_status_created
    ON learning.experiences (status, created_at DESC);
