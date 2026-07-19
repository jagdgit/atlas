-- Atlas Migration 0031: knowledge.lineage evidence graph (Phase C · PHASE_C_PLAN §C.3, CC12 / P9)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- (Planning placeholder `0037_knowledge_lineage`; assigned the next sequential slot 0031.)
--
-- P9 (everything is explainable): every consolidation decision writes an **append-only** edge here
-- recording *what evidence created / strengthened / revised / superseded / contradicted* a finding.
-- This is the DURABLE audit trail — candidates (0030) may be pruned, lineage is never pruned. It lets
-- Atlas answer "what evidence made me believe this, and what changed my mind?" precisely, and lets a
-- confidence/maturity change be traced back to its cause.

CREATE TABLE IF NOT EXISTS knowledge.lineage (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id    UUID NOT NULL,               -- soft ref → knowledge.findings(id) (the affected revision)
    canonical_id  TEXT,                         -- stable finding id (survives revisions), for grouping
    revision      INTEGER,
    edge_type     TEXT NOT NULL,                -- created_by | supported_by | revised_by | superseded_by | contradicted_by
    evidence_ref  JSONB NOT NULL DEFAULT '{}',  -- {asset_id, asset_version, source, reader, candidate_id, mission_id, job_id}
    detail        JSONB NOT NULL DEFAULT '{}',  -- optional: similarity, prior_finding_id, confidence delta, note
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_lineage_edge_type_check
        CHECK (edge_type IN (
            'created_by', 'supported_by', 'revised_by', 'superseded_by', 'contradicted_by'
        ))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_lineage_finding
    ON knowledge.lineage (finding_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_lineage_canonical
    ON knowledge.lineage (canonical_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_lineage_edge_type
    ON knowledge.lineage (edge_type);
