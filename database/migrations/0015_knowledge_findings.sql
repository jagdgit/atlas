-- Atlas Migration 0015: knowledge.findings (Stage 3B.2 Evidence Synthesizer)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Durable Findings live under knowledge (D3B.26), not evidence. Evidence remains
-- transient/traceable. Append-only revision columns are present now; full lifecycle
-- policies land in 3B.3. IDs: UUID + stable canonical F-###### + revision (D3B.29).

CREATE SEQUENCE IF NOT EXISTS knowledge.findings_canonical_seq;

CREATE TABLE IF NOT EXISTS knowledge.findings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id        TEXT NOT NULL UNIQUE,
    revision            INTEGER NOT NULL DEFAULT 1,
    statement           TEXT NOT NULL,
    value               JSONB,
    claim_type          TEXT NOT NULL DEFAULT 'prose',
    confidence          TEXT NOT NULL DEFAULT 'UNVERIFIED',
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    freshness           TEXT NOT NULL DEFAULT 'current',
    quality             JSONB NOT NULL DEFAULT '{}',
    supporting          JSONB NOT NULL DEFAULT '[]',
    contradicting       JSONB NOT NULL DEFAULT '[]',
    provenance          JSONB NOT NULL DEFAULT '{}',
    domain              TEXT NOT NULL DEFAULT 'research',
    supersedes          UUID REFERENCES knowledge.findings(id),
    superseded_by       UUID REFERENCES knowledge.findings(id),
    valid_from          TIMESTAMPTZ,
    valid_until         TIMESTAMPTZ,
    last_verified       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_findings_status_check
        CHECK (status IN (
            'active', 'contested', 'deprecated', 'superseded', 'archived'
        )),
    CONSTRAINT knowledge_findings_freshness_check
        CHECK (freshness IN ('current', 'aging', 'stale')),
    CONSTRAINT knowledge_findings_revision_check
        CHECK (revision >= 1)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_status_domain
    ON knowledge.findings (status, domain);

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_canonical
    ON knowledge.findings (canonical_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_claim_type
    ON knowledge.findings (claim_type);
