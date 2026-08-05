-- Atlas Migration 0048: Decision Intelligence — Outcome Attribution (DI.Attr)
-- Idempotent. Grades decision_quality ≠ market P&L (hard rule in application code).

CREATE TABLE IF NOT EXISTS decision.attributions (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision_id     UUID REFERENCES decision.packets(decision_id),
    symbol          TEXT NOT NULL,
    portfolio_key   TEXT NOT NULL,
    trigger         TEXT NOT NULL DEFAULT 'exit',  -- exit | revisit | manual
    checkpoint      TEXT,
    grades          JSONB NOT NULL DEFAULT '{}',
    payload         JSONB NOT NULL DEFAULT '{}',
    payload_version TEXT NOT NULL DEFAULT 'di.attr.1',
    CONSTRAINT decision_attributions_trigger_check
        CHECK (trigger IN ('exit', 'revisit', 'manual'))
);

CREATE INDEX IF NOT EXISTS decision_attributions_decision
    ON decision.attributions (decision_id, created_at DESC)
    WHERE decision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS decision_attributions_symbol
    ON decision.attributions (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS decision_attributions_portfolio
    ON decision.attributions (portfolio_key, created_at DESC);
