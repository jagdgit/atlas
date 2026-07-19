-- Atlas Migration 0030: knowledge.candidates (Phase C · PHASE_C_PLAN §C.3, CC11 / P11/P13)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- (Planning placeholder `0036_knowledge_candidates`; assigned the next sequential slot 0030.)
--
-- P11 + P13: readers/extractors are stateless translators and MUST NOT write `knowledge.findings`
-- directly. Instead they emit **candidates** — transient, per-observation records of "I saw claim X in
-- asset A". Only the **Knowledge Consolidator** reads candidates and decides whether each one creates,
-- strengthens (evidence-merge), revises, supersedes, or contradicts an existing finding. This table is
-- the single inbox for that flow.
--
-- Retention (CC11): a candidate is marked `consumed` (with the finding it fed) when the Consolidator
-- processes it, and pruned after a configurable window so the table stays bounded. The DURABLE audit
-- trail is the lineage graph (migration 0031), NOT these rows — candidates are safe to prune.

CREATE TABLE IF NOT EXISTS knowledge.candidates (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    statement                TEXT NOT NULL,
    claim_type               TEXT NOT NULL DEFAULT 'prose',
    value                    JSONB,                       -- structured value (number/unit/kind), optional
    domain                   TEXT NOT NULL DEFAULT 'research',
    identity_key             JSONB,                       -- deterministic identity (structured); NULL ⇒ NN path (prose)
    evidence_ref             JSONB NOT NULL DEFAULT '{}', -- {asset_id, asset_version, source, reader, reader_version, ...}
    provenance               JSONB NOT NULL DEFAULT '{}',
    confidence               TEXT,
    confidence_score         DOUBLE PRECISION,
    reader                   TEXT,                        -- which reader produced it (BB8 provenance)
    reader_version           TEXT,
    mission_id               UUID,                        -- soft ref → mission (provenance, P12)
    job_id                   UUID,                        -- soft ref → job (provenance, P12)
    status                   TEXT NOT NULL DEFAULT 'pending',  -- pending | consumed | discarded
    consumed_at              TIMESTAMPTZ,
    consolidated_finding_id  UUID,                        -- soft ref → knowledge.findings(id) once consumed
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_candidates_status_check
        CHECK (status IN ('pending', 'consumed', 'discarded'))
);

-- Consolidator scans the pending inbox oldest-first; keep that lookup cheap.
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_pending
    ON knowledge.candidates (created_at)
    WHERE status = 'pending';

-- Pruning consumed candidates by age.
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_consumed_at
    ON knowledge.candidates (consumed_at)
    WHERE status = 'consumed';
