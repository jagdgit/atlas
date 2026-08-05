-- Atlas Migration 0046: Decision Intelligence — Market Timeline + revisits (DI.2)
-- Idempotent. Timeline table exists from 0045; this adds indexes + revisit schedule.

CREATE INDEX IF NOT EXISTS decision_timeline_symbol_ts
    ON decision.timeline_events (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS decision_timeline_decision
    ON decision.timeline_events (decision_id, created_at DESC)
    WHERE decision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS decision_timeline_kind_ts
    ON decision.timeline_events (kind, created_at DESC);

CREATE TABLE IF NOT EXISTS decision.revisits (
    id                 UUID PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision_id        UUID REFERENCES decision.packets(decision_id),
    symbol             TEXT NOT NULL,
    portfolio_key      TEXT NOT NULL,
    checkpoint         TEXT NOT NULL,  -- day1 | week1 | month1 | quarter | exit
    due_ist            DATE NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',  -- pending | done | skipped
    completed_at       TIMESTAMPTZ,
    timeline_event_id  UUID REFERENCES decision.timeline_events(id),
    payload            JSONB NOT NULL DEFAULT '{}',
    payload_version    TEXT NOT NULL DEFAULT 'di.revisit.1',
    CONSTRAINT decision_revisits_checkpoint_check
        CHECK (checkpoint IN ('day1', 'week1', 'month1', 'quarter', 'exit')),
    CONSTRAINT decision_revisits_status_check
        CHECK (status IN ('pending', 'done', 'skipped')),
    CONSTRAINT decision_revisits_unique_pending
        UNIQUE (decision_id, checkpoint)
);

CREATE INDEX IF NOT EXISTS decision_revisits_due
    ON decision.revisits (status, due_ist)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS decision_revisits_portfolio
    ON decision.revisits (portfolio_key, due_ist);
