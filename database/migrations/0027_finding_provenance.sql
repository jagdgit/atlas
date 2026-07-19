-- Atlas Migration 0027: Finding provenance — who *discovered* this (Phase C · PHASE_C_PLAN §C.1, P12)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- P12 (Knowledge is global): knowledge belongs to Atlas, not to a Mission/Job. A Mission or Job
-- *discovers* knowledge; it never *owns* it. To make "who discovered this?" queryable — and to keep
-- P9 explainability — findings gain **provenance** columns for the discovering mission/job. These
-- are provenance, NOT ownership: they are nullable, soft (no FK into mission/job schemas, matching
-- the house pattern of 0019/0024/0026), and are NEVER used as a delete/visibility filter. Archiving
-- a mission leaves its findings intact.
--
--   * mission_id — soft ref → the mission under which this finding was discovered (NULL if none).
--   * job_id     — soft ref → the job under which this finding was discovered (NULL if none).
--
-- The same descriptors also ride the `provenance` JSON (with a free-form `source`); these columns
-- are the indexed, denormalized copy for fast "discovered by this mission/job" lookups.
--
-- NOTE: `knowledge.findings` did NOT previously carry these columns (verified against 0015); this
-- migration ADDS them. All columns are nullable so pre-Phase-C rows remain valid.

ALTER TABLE knowledge.findings ADD COLUMN IF NOT EXISTS mission_id UUID;   -- soft ref → mission (provenance)
ALTER TABLE knowledge.findings ADD COLUMN IF NOT EXISTS job_id     UUID;   -- soft ref → job (provenance)

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_mission_id
    ON knowledge.findings (mission_id)
    WHERE mission_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_job_id
    ON knowledge.findings (job_id)
    WHERE job_id IS NOT NULL;
