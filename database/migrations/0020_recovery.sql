-- Atlas Migration 0020: Recovery Manager + Checkpoints (Phase 0 · §2.8, P1/P4)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Two durability primitives for design-for-failure (P4):
--   * system.recovery_runs — a durable, re-entrant record of each startup recovery pass
--     (so a crash *during* recovery is visible and the next boot completes cleanly before
--     accepting work). Steps are recorded as JSONB for explainability (P9).
--   * system.checkpoints — the foundation for intra-step checkpointing (Phase A workers):
--     an upsertable (owner_type, owner_id, label) → state blob so long-running work can
--     resume "exactly there" after a power loss rather than restarting.

CREATE TABLE IF NOT EXISTS system.recovery_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host         TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    steps        JSONB NOT NULL DEFAULT '[]',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    CONSTRAINT recovery_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed', 'interrupted'))
);

CREATE INDEX IF NOT EXISTS idx_recovery_runs_started
    ON system.recovery_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS system.checkpoints (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_type   TEXT NOT NULL,           -- 'job' | 'worker' | 'mission' | …
    owner_id     TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT 'default',
    state        JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT checkpoints_owner_label_uniq UNIQUE (owner_type, owner_id, label)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_owner
    ON system.checkpoints (owner_type, owner_id);
