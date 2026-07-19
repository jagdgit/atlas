-- Atlas Migration 0036: policy store (Phase C · PHASE_C_PLAN §C.5, CC8)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- The Policy layer is the fourth of the five things Atlas holds (Knowledge, Experience, **Policy**,
-- Configuration, Mission State). Policies are durable, editable, provenance-stamped **operator rules**
-- that *influence* how Atlas retrieves knowledge and phrases advice — e.g. "prefer momentum
-- strategies", "avoid crypto", "trust finding F-1928". They are NOT knowledge (not learned/evidenced),
-- NOT experience (not the owner's history), and NOT static config (YAML/env knobs). Crucially they are
-- **influence, not arbitration** (CC8): a policy nudges ranking/inclusion, it never acts on the world
-- or hard-decides — that is the Phase-D Decision Engine.
--
-- Governed + reversible: every mutation appends a before/after row to `policy.events` so an edit can be
-- explained and reverted, mirroring the learning ledger's ethos without entangling the two layers.

CREATE SCHEMA IF NOT EXISTS policy AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS policy.rules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope       TEXT NOT NULL DEFAULT 'global',   -- global | domain:<x> | mission:<id> | ... (future scoping)
    subject     TEXT NOT NULL,                    -- what it is about (topic, source, finding id)
    rule        TEXT NOT NULL,                    -- prefer | avoid | trust | distrust
    strength    DOUBLE PRECISION NOT NULL DEFAULT 1.0,  -- 0..1 influence magnitude
    enabled     BOOLEAN NOT NULL DEFAULT true,
    provenance  JSONB NOT NULL DEFAULT '{}',
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT policy_rules_rule_check
        CHECK (rule IN ('prefer', 'avoid', 'trust', 'distrust')),
    CONSTRAINT policy_rules_strength_check
        CHECK (strength >= 0.0 AND strength <= 1.0),
    CONSTRAINT uq_policy_rules_scope_subject_rule
        UNIQUE (scope, subject, rule)
);

-- Hot path: load enabled rules to influence retrieval/advice.
CREATE INDEX IF NOT EXISTS idx_policy_rules_enabled
    ON policy.rules (scope) WHERE enabled;

-- Append-only journal: every create/update/disable/enable/delete/revert, with before/after snapshots,
-- so a policy change is explainable (P9) and reversible. Never pruned.
CREATE TABLE IF NOT EXISTS policy.events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id     UUID,                             -- soft ref → policy.rules(id) (row may be gone after delete)
    action      TEXT NOT NULL,                    -- created | updated | disabled | enabled | deleted | reverted
    before      JSONB,                            -- rule snapshot prior to the change (NULL for create)
    after       JSONB,                            -- rule snapshot after the change (NULL for delete)
    actor       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT policy_events_action_check
        CHECK (action IN ('created', 'updated', 'disabled', 'enabled', 'deleted', 'reverted'))
);

CREATE INDEX IF NOT EXISTS idx_policy_events_rule ON policy.events (rule_id);
CREATE INDEX IF NOT EXISTS idx_policy_events_created_at ON policy.events (created_at DESC);
