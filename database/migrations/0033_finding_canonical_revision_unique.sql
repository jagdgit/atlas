-- Atlas Migration 0033: findings unique (canonical_id, revision) (Phase C · PHASE_C_PLAN §C.3, CC3)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Bug fix that unblocks the Consolidator as the single write path (C.3e). 0015 declared
-- `canonical_id TEXT NOT NULL UNIQUE`, but the revision model (D3B.29) keeps a STABLE canonical_id
-- across revisions — every append_revision writes a new row REUSING the canonical_id with
-- revision+1. The global UNIQUE(canonical_id) therefore makes the documented `revise` path raise a
-- UNIQUE violation on the live DB, which is why EngineeringFindingWriter worked around it by minting
-- a *new* canonical on every change. Relax the constraint to UNIQUE(canonical_id, revision) so a
-- logical finding can own its revision chain and `consolidate()` can revise in place with a stable
-- canonical_id (research promote + engineering both benefit).
--
-- Safe on existing data: revise never succeeded on the live DB, so every canonical_id currently has
-- exactly one row (revision 1) — the composite key is already satisfied.

ALTER TABLE knowledge.findings DROP CONSTRAINT IF EXISTS findings_canonical_id_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'knowledge_findings_canonical_revision_uniq'
    ) THEN
        ALTER TABLE knowledge.findings
            ADD CONSTRAINT knowledge_findings_canonical_revision_uniq
            UNIQUE (canonical_id, revision);
    END IF;
END $$;
