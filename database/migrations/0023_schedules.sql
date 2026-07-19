-- Atlas Migration 0023: Recurring / interval schedules (Phase A · PHASE_A_PLAN §A.3, P1/P4)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- A first-class, DURABLE recurrence table. Until now, periodic work (ingestion scan, backup)
-- re-enqueued itself ad hoc with `delay_seconds`; that is fine but invisible and not pausable.
-- A `schedule` row makes recurrence inspectable, pausable per mission, and crash-safe: the
-- next fire time lives in the DB (`next_run_at`), so a `kill -9` + reboot resumes on cadence
-- rather than losing the schedule. A lightweight `schedule_tick` task claims due rows, enqueues
-- their task, and advances `next_run_at` (see atlas/scheduler/schedules.py).
--
-- Phase A drives **workers** off this (B3); backup/ingestion self-re-enqueue stays untouched
-- and migrates in a later phase. `mission_id` cascades so archiving/deleting a mission disables
-- its schedules; `worker_id` is a soft ref (worker.workers lands in 0024).

CREATE TABLE IF NOT EXISTS scheduler.schedules (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type        TEXT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}',
    interval_seconds INTEGER NOT NULL,
    next_run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at      TIMESTAMPTZ,
    enabled          BOOLEAN NOT NULL DEFAULT true,
    mission_id       UUID REFERENCES mission.missions(id) ON DELETE CASCADE,
    worker_id        UUID,                          -- → worker.workers (0024, soft ref)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT schedules_interval_check CHECK (interval_seconds >= 1)
);

-- The hot path: "which enabled schedules are due?" — ordered by next_run_at.
CREATE INDEX IF NOT EXISTS idx_schedules_due
    ON scheduler.schedules (next_run_at)
    WHERE enabled;

CREATE INDEX IF NOT EXISTS idx_schedules_mission
    ON scheduler.schedules (mission_id) WHERE mission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_schedules_worker
    ON scheduler.schedules (worker_id) WHERE worker_id IS NOT NULL;
