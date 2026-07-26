-- Atlas Migration 0043: Durable Goals (OX.3 / OI-IL-OX)
-- Idempotent. Platform goals — objectives first; Program/Portfolio are optional links.
-- Not Market-only: any Program may attach a Goal.

CREATE TABLE IF NOT EXISTS system.goals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title             TEXT NOT NULL,
    objective         JSONB NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'active',
    success_criteria  JSONB,
    program_id        TEXT,
    portfolio_key     TEXT,
    portfolio_id      TEXT,
    progress          JSONB NOT NULL DEFAULT '{}',
    metadata          JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT system_goals_status_check
        CHECK (status IN ('active', 'paused', 'completed', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_system_goals_status
    ON system.goals (status);

CREATE INDEX IF NOT EXISTS idx_system_goals_program
    ON system.goals (program_id) WHERE program_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_system_goals_portfolio_key
    ON system.goals (portfolio_key) WHERE portfolio_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_system_goals_title_fts
    ON system.goals USING gin (to_tsvector('english', coalesce(title, '')));
