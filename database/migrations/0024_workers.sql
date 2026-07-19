-- Atlas Migration 0024: Persistent Workers + operator input queue (Phase A · §A.4, P1/P4)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- The payoff of Phase A: long-running **Persistent Workers** owned by a Mission. A worker runs
-- as a **short-task + checkpoint** loop (A-new1) — a scheduled `worker_tick` loads its
-- checkpoint, does one bounded unit, saves, and the schedule (0023) drives the next tick — so a
-- worker survives kill -9 + reboot and resumes exactly where it left off. Checkpoints reuse the
-- Phase-0 store (`system.checkpoints`, owner_type='worker'); no separate table (A-new2).
--
--   * worker.workers — one row per worker: identity + `worker_version` (B8 upgrade), lifecycle
--     `status`, dashboard `health` tier, its driving `schedule_id`, the `config_version` it last
--     picked up, and crash-policy state (`restart_count` / `next_retry_at`, B4 backoff).
--   * worker.inputs — durable operator-input queue (Q4): "give paper trading a constraint while
--     it runs". Enqueued live; the worker drains pending inputs at the top of each tick.

CREATE SCHEMA IF NOT EXISTS worker AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS worker.workers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id     UUID NOT NULL REFERENCES mission.missions(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,
    worker_version INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'running',
    health         TEXT NOT NULL DEFAULT 'healthy',
    schedule_id    UUID,                          -- → scheduler.schedules (soft ref)
    config_version INTEGER,                       -- active config version last picked up
    restart_count  INTEGER NOT NULL DEFAULT 0,    -- consecutive tick failures (B4)
    next_retry_at  TIMESTAMPTZ,                   -- recovering: don't tick before this
    last_tick_at   TIMESTAMPTZ,
    metadata       JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT workers_status_check CHECK (
        status IN ('running', 'recovering', 'paused', 'failed', 'stopped')
    ),
    CONSTRAINT workers_health_check CHECK (
        health IN ('healthy', 'degraded', 'blocked', 'recovering', 'failed')
    ),
    CONSTRAINT workers_restart_check CHECK (restart_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_workers_mission
    ON worker.workers (mission_id);
CREATE INDEX IF NOT EXISTS idx_workers_status
    ON worker.workers (status);

CREATE TABLE IF NOT EXISTS worker.inputs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id    UUID NOT NULL REFERENCES worker.workers(id) ON DELETE CASCADE,
    payload      JSONB NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at  TIMESTAMPTZ,
    CONSTRAINT worker_inputs_status_check CHECK (status IN ('pending', 'consumed'))
);

-- The hot path: "pending inputs for this worker, oldest first" (drained each tick).
CREATE INDEX IF NOT EXISTS idx_worker_inputs_pending
    ON worker.inputs (worker_id, created_at)
    WHERE status = 'pending';
