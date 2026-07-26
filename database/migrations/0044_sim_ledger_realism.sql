-- Atlas Migration 0044: Sim ledger realism (IL.7) — fee breakdown + cash movements
-- Idempotent. Simulation only (P10).

-- Persist Broker Profile fee components alongside scalar fee total.
ALTER TABLE sim.trades
    ADD COLUMN IF NOT EXISTS fees JSONB NOT NULL DEFAULT '{}';

-- Cash movements outside buy/sell fills (withdraw / deposit / adjustment).
CREATE TABLE IF NOT EXISTS sim.cash_movements (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id   UUID NOT NULL REFERENCES sim.portfolios(id) ON DELETE CASCADE,
    mission_id     UUID,
    kind           TEXT NOT NULL,  -- withdraw | deposit | adjustment
    amount         DOUBLE PRECISION NOT NULL,  -- signed: withdraw negative of principal
    tds            DOUBLE PRECISION NOT NULL DEFAULT 0,
    fee            DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash_after     DOUBLE PRECISION NOT NULL DEFAULT 0,
    note           TEXT NOT NULL DEFAULT '',
    metadata       JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_cash_movement_kind_check CHECK (kind IN ('withdraw', 'deposit', 'adjustment'))
);

CREATE INDEX IF NOT EXISTS idx_sim_cash_movements_portfolio
    ON sim.cash_movements (portfolio_id, created_at DESC);
