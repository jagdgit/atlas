-- Atlas Migration 0045: Decision Intelligence — Decision Packets (DI.1)
-- Idempotent. Schema ``decision`` already exists (0039 Decision Engine journal).
-- Packets are append-only: application code must never UPDATE/DELETE rows.
-- Timeline + observations stubs are empty until DI.2 / DI.Obs.

CREATE SCHEMA IF NOT EXISTS decision AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS decision.packets (
    decision_id        UUID PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ts_ist             DATE NOT NULL,
    symbol             TEXT NOT NULL,
    action             TEXT NOT NULL,
    portfolio_key      TEXT NOT NULL,
    mission_id         TEXT,
    strategy_tag       TEXT NOT NULL,
    setup_tag          TEXT,
    parent_decision_id UUID REFERENCES decision.packets(decision_id),
    prior_thesis_id    TEXT,
    engine_decision_id TEXT,
    fill_trade_id      TEXT,
    payload            JSONB NOT NULL,
    payload_version    TEXT NOT NULL DEFAULT 'di.packet.1',
    CONSTRAINT decision_packets_action_check
        CHECK (action IN ('buy', 'sell', 'hold', 'watch', 'reduce'))
);

CREATE INDEX IF NOT EXISTS decision_packets_symbol_ts
    ON decision.packets (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS decision_packets_portfolio_ts
    ON decision.packets (portfolio_key, ts_ist DESC);
CREATE INDEX IF NOT EXISTS decision_packets_action_ts
    ON decision.packets (action, created_at DESC);
CREATE INDEX IF NOT EXISTS decision_packets_strategy
    ON decision.packets (strategy_tag, created_at DESC);

CREATE TABLE IF NOT EXISTS decision.timeline_events (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    decision_id     UUID REFERENCES decision.packets(decision_id),
    payload         JSONB NOT NULL DEFAULT '{}',
    payload_version TEXT NOT NULL DEFAULT 'di.timeline.1'
);

CREATE TABLE IF NOT EXISTS decision.observations (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          TEXT,
    kind            TEXT NOT NULL,
    payload         JSONB NOT NULL,
    source          TEXT,
    confidence      TEXT,
    expires_at      TIMESTAMPTZ,
    payload_version TEXT NOT NULL DEFAULT 'di.obs.1'
);
