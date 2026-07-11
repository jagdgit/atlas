-- Atlas Migration 0004: Scheduler Foundation Tables

CREATE TABLE IF NOT EXISTS scheduler.tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type       TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scheduler_tasks_status_check
        CHECK (status IN ('pending', 'claimed', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS scheduler.task_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES scheduler.tasks(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    result          JSONB,
    error           TEXT,
    worker_id       TEXT,
    CONSTRAINT scheduler_task_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_scheduler_tasks_status_scheduled
    ON scheduler.tasks (status, scheduled_at ASC)
    WHERE status IN ('pending', 'failed');

CREATE INDEX IF NOT EXISTS idx_scheduler_tasks_type_status
    ON scheduler.tasks (task_type, status);

CREATE INDEX IF NOT EXISTS idx_scheduler_task_runs_task_started
    ON scheduler.task_runs (task_id, started_at DESC);

-- Recovery index: find interrupted tasks after crash/restart
CREATE INDEX IF NOT EXISTS idx_scheduler_tasks_interrupted
    ON scheduler.tasks (status, claimed_at)
    WHERE status IN ('claimed', 'running');
