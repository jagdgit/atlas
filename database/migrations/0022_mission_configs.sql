-- Atlas Migration 0022: Mission Configuration (Phase A · PHASE_A_PLAN §A.2, P6)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Per-mission, DB-persisted, **versioned** configuration (P6: everything configurable +
-- versioned; nothing hardcoded in a worker). Editing a config never mutates a row in place —
-- it writes a NEW version, so every past result is reproducible against the exact config that
-- produced it. `Mission.active_config_id` (0021) points at the version a worker currently reads.
--
-- Each row records BOTH:
--   * schema_type    — which Pydantic schema validated it ('hello_watcher', 'paper_trading', …)
--   * schema_version — which VERSION of that schema (B6): old rows are immutable and keep the
--     schema_version they were written under; a breaking schema change is a new schema_version,
--     migrated (if ever) by an explicit opt-in tool — never automatically.

CREATE SCHEMA IF NOT EXISTS config AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS config.mission_configs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id     UUID NOT NULL REFERENCES mission.missions(id) ON DELETE CASCADE,
    version        INTEGER NOT NULL,              -- 1-based, per mission; monotonic
    schema_type    TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    document       JSONB NOT NULL DEFAULT '{}',   -- the validated config document
    change_note    TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mission_configs_version_uniq UNIQUE (mission_id, version),
    CONSTRAINT mission_configs_version_check CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_mission_configs_mission
    ON config.mission_configs (mission_id, version DESC);
