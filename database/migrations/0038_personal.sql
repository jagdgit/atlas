-- Atlas Migration 0038: Personal Intelligence store (Phase C · PHASE_C_PLAN §C.7, CC7/A9)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Personal Intelligence is "a model of you, not a memory dump": a curated profile assembled INDIRECTLY
-- from Research + Engineering + Experience + operator interaction. A `personal.facts` row is one
-- profile fact — an identity/profile fact, a **skill** (distilled from consolidated experiences), a
-- **timeline** entry (projects/roles over years), or a **professional** fact (publications, patents,
-- roles). Each fact carries **provenance + confidence** and a governed lifecycle state:
--
--   inferred  → auto-derived by Atlas (default). Held, never presented as truth.
--   verified  → an operator confirmed it (CC7/A9: promotion requires human confirmation; no silent
--               scraping). An operator can also CORRECT a fact (edit + verify) …
--   rejected  → … or REJECT it (operator says "not true / not me"); Atlas must not re-infer over it.
--
-- Facts are **retrieval, not action** (P10): other missions read this profile; resume/LinkedIn/portfolio
-- managers DRAFT from it — they never scan code and never post.
--
-- Governed + reversible: every mutation appends a before/after row to `personal.events` so a change is
-- explainable (P9) and revertible, mirroring the Policy store's journal (C.5) — a dedicated journal,
-- not the learning ledger.

CREATE SCHEMA IF NOT EXISTS personal AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS personal.facts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category          TEXT NOT NULL,                    -- identity | skill | timeline | professional
    key               TEXT NOT NULL,                    -- canonical fact key (e.g. skill name, role id)
    subject           TEXT NOT NULL DEFAULT '',         -- optional grouping (e.g. skill context) — '' not NULL so the natural key is stable
    statement         TEXT NOT NULL DEFAULT '',         -- human-readable rendering
    value             JSONB NOT NULL DEFAULT '{}',      -- structured fact value
    state             TEXT NOT NULL DEFAULT 'inferred', -- inferred | verified | rejected
    confidence        TEXT,                             -- UNVERIFIED | LOW | MEDIUM | HIGH
    confidence_score  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    source            TEXT,                             -- experience | finding | intelligence | operator
    provenance        JSONB NOT NULL DEFAULT '{}',      -- evidence: experience/finding ids, sources, counts
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT personal_facts_category_check
        CHECK (category IN ('identity', 'skill', 'timeline', 'professional')),
    CONSTRAINT personal_facts_state_check
        CHECK (state IN ('inferred', 'verified', 'rejected')),
    CONSTRAINT personal_facts_confidence_score_check
        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    -- One fact per (category, key, subject): re-inference upserts in place (idempotent, CC7).
    CONSTRAINT uq_personal_facts_natural UNIQUE (category, key, subject)
);

CREATE INDEX IF NOT EXISTS idx_personal_facts_category ON personal.facts (category);
CREATE INDEX IF NOT EXISTS idx_personal_facts_state ON personal.facts (state);

-- Append-only journal: every infer/confirm/correct/reject/update/delete/revert with before/after
-- snapshots, so a profile change is explainable (P9) and reversible. Never pruned.
CREATE TABLE IF NOT EXISTS personal.events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id     UUID,                             -- soft ref → personal.facts(id) (row may be gone after delete)
    action      TEXT NOT NULL,                    -- inferred | confirmed | corrected | rejected | updated | deleted | reverted
    before      JSONB,                            -- fact snapshot prior to the change (NULL for infer/create)
    after       JSONB,                            -- fact snapshot after the change (NULL for delete)
    actor       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT personal_events_action_check
        CHECK (action IN ('inferred', 'confirmed', 'corrected', 'rejected', 'updated', 'deleted', 'reverted'))
);

CREATE INDEX IF NOT EXISTS idx_personal_events_fact ON personal.events (fact_id);
CREATE INDEX IF NOT EXISTS idx_personal_events_created_at ON personal.events (created_at DESC);
