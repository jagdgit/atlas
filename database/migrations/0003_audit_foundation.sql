-- Atlas Migration 0003: Audit Foundation Tables

CREATE TABLE IF NOT EXISTS audit.events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}',
    source       TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT audit_events_status_check
        CHECK (status IN ('pending', 'processed', 'failed'))
);

CREATE TABLE IF NOT EXISTS audit.logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level       TEXT NOT NULL,
    module      TEXT,
    message     TEXT NOT NULL,
    context     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_type_created
    ON audit.events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_status_created
    ON audit.events (status, created_at DESC)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_audit_logs_level_created
    ON audit.logs (level, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
    ON audit.logs (created_at DESC);

-- Retention: events older than 90 days (ADR-0016).
-- Cleanup job implemented in Sprint 2 scheduler.
