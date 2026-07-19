-- Atlas Migration 0041: Virtual (simulation-only) trading portfolio (Phase D · PHASE_D_PLAN §D.6 / P10)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- The Paper-Trading Mission is **simulation only** — NO real money, NO real broker (P10). Its decisions
-- are produced by the Decision Engine and applied here to a *virtual* portfolio: cash, positions, and a
-- trade blotter. Because a simulated fill changes nothing in the world, these applies flow freely
-- without the human-approval gate (DD3) — only a *real* order would set `requires_approval` (P14).
--
-- Each trade links back to the `decision.decisions` row that caused it (soft ref → the P9 "explain
-- this" record), so the whole blotter is auditable: every fill has a why. mission_id is provenance
-- (P12); deleting a mission never deletes its simulated history (soft refs, no cross-schema FK).

CREATE SCHEMA IF NOT EXISTS sim AUTHORIZATION atlas;

-- One virtual account per (mission, name). Cash is the free balance; starting_cash is the immutable
-- opening balance so total return is computable at any time.
CREATE TABLE IF NOT EXISTS sim.portfolios (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id     UUID,                                  -- soft ref → mission.missions(id) (provenance)
    name           TEXT NOT NULL DEFAULT 'default',
    base_currency  TEXT NOT NULL DEFAULT 'USD',
    starting_cash  DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash           DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl   DOUBLE PRECISION NOT NULL DEFAULT 0,   -- cumulative realized P&L (closed lots)
    metadata       JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_portfolio_mission_name_uniq UNIQUE (mission_id, name)
);

-- Current holding per symbol (one row per open position; quantity 0 rows may be pruned or kept flat).
CREATE TABLE IF NOT EXISTS sim.positions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id  UUID NOT NULL REFERENCES sim.portfolios(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    quantity      DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_price     DOUBLE PRECISION NOT NULL DEFAULT 0,     -- average cost basis of the open lot
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_position_portfolio_symbol_uniq UNIQUE (portfolio_id, symbol)
);

-- Append-only blotter: every simulated fill, linked to the decision that caused it (P9).
CREATE TABLE IF NOT EXISTS sim.trades (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id  UUID NOT NULL REFERENCES sim.portfolios(id) ON DELETE CASCADE,
    mission_id    UUID,                                    -- provenance (P12)
    decision_id   UUID,                                    -- soft ref → decision.decisions(id) (why)
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,                           -- buy | sell
    quantity      DOUBLE PRECISION NOT NULL,
    price         DOUBLE PRECISION NOT NULL,
    fee           DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash_after    DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl  DOUBLE PRECISION NOT NULL DEFAULT 0,     -- P&L realized by this fill (sells)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_trade_side_check CHECK (side IN ('buy', 'sell'))
);

CREATE INDEX IF NOT EXISTS idx_sim_positions_portfolio ON sim.positions (portfolio_id);
CREATE INDEX IF NOT EXISTS idx_sim_trades_portfolio     ON sim.trades (portfolio_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_trades_mission       ON sim.trades (mission_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_trades_decision      ON sim.trades (decision_id);
