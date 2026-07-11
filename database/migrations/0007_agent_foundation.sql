-- Atlas Migration 0007: Agent Foundation (agent schema, agents, runs, steps)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`
-- (atlas owns the database, so it may create the schema itself — no superuser
-- round-trip needed).
--
-- Introduces the `agent` schema (ADR-0028/0029): the top layer of the four-layer
-- architecture. Agents orchestrate services (knowledge, llm) to accomplish goals.
-- Every invocation is persisted as a run (with an ordered step trace) so agent
-- behaviour is observable and recoverable after a crash (ADR-0032).

CREATE SCHEMA IF NOT EXISTS agent AUTHORIZATION atlas;

-- Catalog of registered agents. `config` is a snapshot of the effective settings
-- at registration time (retrieval_k, grounding, ...), useful for auditing changes.
CREATE TABLE IF NOT EXISTS agent.agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,                 -- stable identifier, e.g. 'rag'
    kind            TEXT NOT NULL,                 -- 'rag' | ... (agent type)
    description     TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_agents_name UNIQUE (name)
);

-- Runs: one row per invocation — the unit of observability and crash recovery.
-- Status pipeline mirrors scheduler.tasks so interrupted runs can be recovered.
CREATE TABLE IF NOT EXISTS agent.runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID REFERENCES agent.agents(id) ON DELETE SET NULL,
    agent_name      TEXT NOT NULL,                 -- denormalized for easy querying
    status          TEXT NOT NULL DEFAULT 'pending',
    input           JSONB NOT NULL DEFAULT '{}',   -- {query, options}
    output          JSONB,                         -- {answer, citations, usage}
    error           TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT agent_runs_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent
    ON agent.runs (agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status
    ON agent.runs (status);

CREATE INDEX IF NOT EXISTS idx_agent_runs_created
    ON agent.runs (created_at DESC);

-- Steps: the ordered trace of how a run produced its answer (retrieve, generate).
CREATE TABLE IF NOT EXISTS agent.steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES agent.runs(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,              -- 0-based position within the run
    kind            TEXT NOT NULL,                 -- 'retrieve' | 'generate' | ...
    detail          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_steps_run_ordinal UNIQUE (run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run
    ON agent.steps (run_id);
