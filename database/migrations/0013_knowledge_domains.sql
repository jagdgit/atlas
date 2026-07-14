-- Atlas Migration 0013: Knowledge Domains (Stage 3 / D3.13 / A3)
-- Idempotent: safe to re-run.
--
-- Adds a single indexed ``domain`` column to knowledge.documents so retrieval can
-- filter by universe (external / research / experience / …). Existing rows backfill
-- to ``external`` (world knowledge was the only content before Stage 3).

ALTER TABLE knowledge.documents
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'external';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'knowledge_documents_domain_check'
    ) THEN
        ALTER TABLE knowledge.documents
            ADD CONSTRAINT knowledge_documents_domain_check
            CHECK (domain IN (
                'external', 'research', 'experience',
                'code', 'personal', 'professional'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_domain
    ON knowledge.documents (domain);
