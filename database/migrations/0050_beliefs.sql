-- Atlas Migration 0050: Persistent Self — Belief Core + Atlas Identity (OI-SELF0 Phase 1)
-- Idempotent. Applied by atlas app role via `atlas-db migrate`.
--
-- Beliefs are first-class worldview (not documents, not WSO). Identity is versioned
-- Atlas-self (not personal.facts owner identity). Goals remain in system.goals.
-- Influence rows are advice-only in Phase 1 (strength check enforced in app).

CREATE SCHEMA IF NOT EXISTS beliefs AUTHORIZATION atlas;

-- Versioned Atlas identity documents (thin Phase 1 stub).
CREATE TABLE IF NOT EXISTS beliefs.identity_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version         INTEGER NOT NULL,
    title           TEXT NOT NULL DEFAULT 'Atlas Identity',
    statement       TEXT NOT NULL,                 -- who Atlas is / permanence doctrine
    non_negotiables JSONB NOT NULL DEFAULT '[]',
    voice           JSONB NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL DEFAULT 'operator',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_identity_version_unique UNIQUE (version),
    CONSTRAINT beliefs_identity_version_positive CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_beliefs_identity_created
    ON beliefs.identity_documents (created_at DESC);

-- Core worldview rows.
CREATE TABLE IF NOT EXISTS beliefs.beliefs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_key          TEXT,                         -- stable seed key (optional)
    domain              TEXT NOT NULL,                -- market | engineering | personal | cross
    level               TEXT NOT NULL DEFAULT 'domain', -- concrete | domain | abstract
    themes              JSONB NOT NULL DEFAULT '[]',
    applies_to          JSONB NOT NULL DEFAULT '[]',
    statement           TEXT NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    status              TEXT NOT NULL DEFAULT 'candidate',
    origin              TEXT NOT NULL DEFAULT 'llm',
    open_questions      JSONB NOT NULL DEFAULT '[]',
    last_evidence_at    TIMESTAMPTZ,
    last_consulted_at   TIMESTAMPTZ,
    last_revised_at     TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_domain_check
        CHECK (domain IN ('market', 'engineering', 'personal', 'cross')),
    CONSTRAINT beliefs_level_check
        CHECK (level IN ('concrete', 'domain', 'abstract')),
    CONSTRAINT beliefs_status_check
        CHECK (status IN (
            'candidate', 'active', 'weakened', 'falsified', 'superseded', 'dormant'
        )),
    CONSTRAINT beliefs_origin_check
        CHECK (origin IN (
            'operator', 'llm', 'mentor', 'experience', 'research', 'imported'
        )),
    CONSTRAINT beliefs_confidence_check
        CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_beliefs_belief_key
    ON beliefs.beliefs (belief_key)
    WHERE belief_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_beliefs_domain_status
    ON beliefs.beliefs (domain, status);
CREATE INDEX IF NOT EXISTS idx_beliefs_status
    ON beliefs.beliefs (status);
CREATE INDEX IF NOT EXISTS idx_beliefs_updated
    ON beliefs.beliefs (updated_at DESC);

-- Append-only mind-change history.
CREATE TABLE IF NOT EXISTS beliefs.revisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id       UUID NOT NULL REFERENCES beliefs.beliefs(id) ON DELETE CASCADE,
    revision_no     INTEGER NOT NULL,
    action          TEXT NOT NULL,                  -- create | revise | promote | weaken | falsify | supersede | dormant
    before_snapshot JSONB,
    after_snapshot  JSONB,
    reason          TEXT NOT NULL DEFAULT '',
    evidence_summary TEXT NOT NULL DEFAULT '',
    confidence_before DOUBLE PRECISION,
    confidence_after  DOUBLE PRECISION,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_revisions_action_check
        CHECK (action IN (
            'create', 'revise', 'promote', 'weaken', 'falsify',
            'supersede', 'dormant', 'reactivate'
        )),
    CONSTRAINT beliefs_revisions_unique UNIQUE (belief_id, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_beliefs_revisions_belief
    ON beliefs.revisions (belief_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS idx_beliefs_revisions_created
    ON beliefs.revisions (created_at DESC);

-- Evidence links (Knowledge / Experience / packets / URLs / notes).
CREATE TABLE IF NOT EXISTS beliefs.evidence_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id       UUID NOT NULL REFERENCES beliefs.beliefs(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL DEFAULT 'note',   -- knowledge | experience | packet | url | note | operator
    ref_id          TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    weight          DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_evidence_kind_check
        CHECK (kind IN ('knowledge', 'experience', 'packet', 'url', 'note', 'operator')),
    CONSTRAINT beliefs_evidence_weight_check
        CHECK (weight >= 0.0)
);

CREATE INDEX IF NOT EXISTS idx_beliefs_evidence_belief
    ON beliefs.evidence_links (belief_id);

-- Competing beliefs / counter-evidence.
CREATE TABLE IF NOT EXISTS beliefs.contradictions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id           UUID NOT NULL REFERENCES beliefs.beliefs(id) ON DELETE CASCADE,
    contrary_belief_id  UUID REFERENCES beliefs.beliefs(id) ON DELETE SET NULL,
    summary             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',  -- open | resolved | accepted_tension
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    CONSTRAINT beliefs_contradiction_status_check
        CHECK (status IN ('open', 'resolved', 'accepted_tension'))
);

CREATE INDEX IF NOT EXISTS idx_beliefs_contradictions_belief
    ON beliefs.contradictions (belief_id);

-- Declared influence intents (Phase 1: advice only).
CREATE TABLE IF NOT EXISTS beliefs.influence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id       UUID NOT NULL REFERENCES beliefs.beliefs(id) ON DELETE CASCADE,
    target          TEXT NOT NULL,                  -- ranking | sizing | gates | chat | research | general
    strength        TEXT NOT NULL DEFAULT 'advice', -- advice | soft | hard
    note            TEXT NOT NULL DEFAULT '',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_influence_strength_check
        CHECK (strength IN ('advice', 'soft', 'hard')),
    CONSTRAINT beliefs_influence_phase1_advice_only
        CHECK (strength = 'advice')
);

CREATE INDEX IF NOT EXISTS idx_beliefs_influence_belief
    ON beliefs.influence (belief_id);

-- Consultation counters (Belief Consultations / day honesty metric).
CREATE TABLE IF NOT EXISTS beliefs.consultations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id       UUID REFERENCES beliefs.beliefs(id) ON DELETE SET NULL,
    domain          TEXT NOT NULL DEFAULT 'cross',
    purpose         TEXT NOT NULL DEFAULT 'consult', -- consult | why | mind_change | chat | wso_projection
    day_ist         DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beliefs_consultations_domain_check
        CHECK (domain IN ('market', 'engineering', 'personal', 'cross'))
);

CREATE INDEX IF NOT EXISTS idx_beliefs_consultations_day
    ON beliefs.consultations (day_ist, domain);
