-- Atlas Migration 0032: finding maturity axis (Phase C · PHASE_C_PLAN §C.3, CC13)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- (Planning placeholder `0038_knowledge_lifecycle`; assigned the next sequential slot 0032.)
--
-- Two-axis lifecycle: a finding has a **validity** `status` machine (active → deprecated / contested /
-- superseded → archived, locked in 0015) AND, orthogonally, a **maturity** — how well-corroborated the
-- understanding is: `candidate` (one uncorroborated observation) → `verified` (corroborated / decent
-- confidence) → `established` (N independent sources agree). Maturity rises as the Consolidator merges
-- evidence (C.3d); it is a SEPARATE column, so the 0015 `status` CHECK is intentionally left untouched
-- (stored status values are unchanged — "contradicted" remains a display label for `contested`).
--
-- Existing rows default to `candidate` (a safe floor); the Consolidator recomputes maturity from the
-- corroboration count + confidence on the next observation that touches each finding.

ALTER TABLE knowledge.findings
    ADD COLUMN IF NOT EXISTS maturity TEXT NOT NULL DEFAULT 'candidate';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_findings_maturity_check'
    ) THEN
        ALTER TABLE knowledge.findings
            ADD CONSTRAINT knowledge_findings_maturity_check
            CHECK (maturity IN ('candidate', 'verified', 'established'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_maturity
    ON knowledge.findings (maturity);
