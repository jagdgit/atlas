-- Atlas Migration 0039: Decision Engine journal (Phase D · PHASE_D_PLAN §D.1, §5.5 / P9/P14/P15)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- The Decision Engine is a **Kernel Service** (R2): every Mission asks "what should I do next?" and the
-- engine answers by combining Research + Engineering + Personal knowledge with Policy arbitration into a
-- single, deterministic, **recommend-only** choice. Each decision is journaled here as the canonical
-- **P9 "Explain this" record**: the action, why (rule), the evidence/knowledge/experience it used, the
-- config + model versions in force, its confidence, and the alternatives it rejected.
--
-- Recommend, don't act (P14): a decision that would change the world sets `requires_approval = true` and
-- flows through `decision.approvals` (migration 0040) before anything happens; simulation/retrieval
-- decisions apply freely. Honest about limits (P15): when a needed capability/reader/rule is absent the
-- engine records an `action_kind = 'capability_gap'` decision naming what is missing, never a fabricated
-- action. Append-only + never pruned (store refs/ids, not copies — A8).

CREATE SCHEMA IF NOT EXISTS decision AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS decision.decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id      UUID,                              -- soft ref → mission.missions(id) (provenance, P12)
    mission_type    TEXT NOT NULL,                     -- which DecisionRule answered (e.g. paper_trading)
    config_id       UUID,                              -- soft ref → config.mission_configs(id)
    config_version  INTEGER,                           -- the versioned config in force (P6)
    action          JSONB NOT NULL DEFAULT '{}',       -- {kind, key, payload} — the chosen next action
    action_kind     TEXT NOT NULL DEFAULT 'recommend', -- recommend | hold | capability_gap
    why             TEXT,                              -- human-readable rationale (deterministic; LLM may polish)
    decision_rule   TEXT,                              -- the rule identity that produced this (P9)
    rule_version    TEXT,
    evidence_refs   JSONB NOT NULL DEFAULT '[]',       -- ids, not copies (A8)
    knowledge_refs  JSONB NOT NULL DEFAULT '[]',
    experience_refs JSONB NOT NULL DEFAULT '[]',
    model_versions  JSONB NOT NULL DEFAULT '{}',       -- from the Capability Registry (P2/CC-D3)
    policy_ids      JSONB NOT NULL DEFAULT '[]',       -- which policy rules influenced the ranking (DD5)
    confidence      TEXT NOT NULL DEFAULT 'low',       -- high | medium | low (deterministic, from margin)
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    alternatives_rejected JSONB NOT NULL DEFAULT '[]', -- the losing options + their scores (P9)
    requires_approval BOOLEAN NOT NULL DEFAULT false,  -- side-effecting → gated by decision.approvals (P14)
    status          TEXT NOT NULL DEFAULT 'recorded',  -- recorded | superseded (future)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT decision_action_kind_check
        CHECK (action_kind IN ('recommend', 'hold', 'capability_gap')),
    CONSTRAINT decision_confidence_check
        CHECK (confidence IN ('high', 'medium', 'low')),
    CONSTRAINT decision_status_check
        CHECK (status IN ('recorded', 'superseded'))
);

-- Hot paths: a mission's decision history, the recent global feed, the capability-gap backlog (P15),
-- and the set of decisions awaiting operator approval (P14).
CREATE INDEX IF NOT EXISTS idx_decision_mission     ON decision.decisions (mission_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_type        ON decision.decisions (mission_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_created_at  ON decision.decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_gaps        ON decision.decisions (created_at DESC)
    WHERE action_kind = 'capability_gap';
CREATE INDEX IF NOT EXISTS idx_decision_pending     ON decision.decisions (created_at DESC)
    WHERE requires_approval;
