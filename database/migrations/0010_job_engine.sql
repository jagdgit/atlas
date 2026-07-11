-- Atlas Migration 0010: Job Engine (job schema)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`
-- (atlas owns the database, so it may create the schema itself — same pattern as
-- 0007's `agent` and 0009's `conversation` schemas).
--
-- Stage 2 / Sprint 12 (D1/R1/R3/Q10): persistent, concurrent, resumable jobs on
-- top of the durable scheduler. A `job` has an objective decomposed into ordered
-- `steps`. Jobs run concurrently (R1); steps within a job run sequentially in v1.
-- A `blocked` step needs the user (R3) and does NOT stop the job — other independent
-- steps still run, and the job finishes `completed_with_blocks` until resumed.
-- Reboot recovery (Q10): running jobs/steps re-hydrate on startup.

CREATE SCHEMA IF NOT EXISTS job AUTHORIZATION atlas;

-- A unit of work. `status` lifecycle:
--   queued -> running -> completed | completed_with_blocks | failed | cancelled
-- `session_id` optionally links the job to a conversation (nullable, no FK so a
-- job can outlive/precede a session cleanup).
CREATE TABLE IF NOT EXISTS job.jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID,
    objective       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    result          JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    CONSTRAINT job_jobs_status_check CHECK (
        status IN ('queued', 'running', 'completed',
                   'completed_with_blocks', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_job_jobs_status_created
    ON job.jobs (status, created_at DESC);

-- The ordered plan. `ordinal` is a per-job 0-based sequence. `depends_on` is the
-- ordinal of a prerequisite step (nullable = independent): a blocked/failed
-- dependency cascades to its dependents without stalling unrelated steps (R3).
-- Step `status` lifecycle:
--   pending -> running -> done | failed | blocked | skipped
CREATE TABLE IF NOT EXISTS job.steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES job.jobs(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,
    intent          TEXT NOT NULL,
    capability      TEXT NOT NULL,
    args            JSONB NOT NULL DEFAULT '{}',
    description     TEXT NOT NULL DEFAULT '',
    depends_on      INTEGER,                     -- ordinal of prerequisite (nullable)
    status          TEXT NOT NULL DEFAULT 'pending',
    result          JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    blocked_reason  TEXT,                        -- "needs: login to IEEE" (R3)
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    CONSTRAINT job_steps_status_check CHECK (
        status IN ('pending', 'running', 'done', 'failed', 'blocked', 'skipped')
    ),
    CONSTRAINT uq_job_steps_job_ordinal UNIQUE (job_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_job_steps_job_ordinal
    ON job.steps (job_id, ordinal);
