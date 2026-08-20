-- Atlas Migration 0051: Daily Activity Journal (OI-STAB0 P0.0)
-- Idempotent. Applied by atlas app role via `atlas-db migrate`.
--
-- Work journal for ownership — not debug logs. "What did you do today?"
-- queries this store deterministically (no LLM).

CREATE SCHEMA IF NOT EXISTS activity AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS activity.activity_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    domain      TEXT NOT NULL,
    worker      TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    target      TEXT,
    result      TEXT NOT NULL DEFAULT 'completed',
    summary     TEXT NOT NULL,
    evidence    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT activity_domain_check
        CHECK (domain IN ('market', 'engineering', 'personal', 'cross', 'system')),
    CONSTRAINT activity_result_check
        CHECK (result IN ('completed', 'skipped', 'failed', 'deferred', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_activity_events_ts
    ON activity.activity_events (ts DESC);

CREATE INDEX IF NOT EXISTS idx_activity_events_domain_ts
    ON activity.activity_events (domain, ts DESC);

CREATE INDEX IF NOT EXISTS idx_activity_events_worker_ts
    ON activity.activity_events (worker, ts DESC);
