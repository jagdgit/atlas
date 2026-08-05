-- Atlas Migration 0047: Decision Intelligence — Observation Layer indexes (DI.Obs)
-- Idempotent. Table ``decision.observations`` created empty in 0045.

CREATE INDEX IF NOT EXISTS decision_observations_symbol_ts
    ON decision.observations (symbol, created_at DESC)
    WHERE symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS decision_observations_kind_ts
    ON decision.observations (kind, created_at DESC);
CREATE INDEX IF NOT EXISTS decision_observations_created
    ON decision.observations (created_at DESC);
