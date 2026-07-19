-- Atlas Migration 0037: experience consolidation columns (Phase C · PHASE_C_PLAN §C.6, CC6)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- C.6 makes owner **experiences** cumulative like knowledge (P13): "used Celery" seen across many
-- projects becomes ONE experience with growing confidence + evidence, not N rows. We reuse the shared
-- Knowledge Consolidator (C.3) over `learning.experiences` via an experience-store adapter — so this
-- migration adds the same lifecycle machinery `knowledge.findings` carries: a deterministic
-- `identity_key` (skill/technology + context), a stable `canonical_id` + `revision` chain, the
-- accumulated `evidence`/`contradicting` source lists, `confidence`/`confidence_score`,
-- `corroboration_count`, the maturity axis, and a `superseded_by` back-pointer.
--
-- Existing rows (manually-remembered experiences) keep working: every column is nullable or defaulted,
-- and the pre-C.6 create path simply leaves the new columns at their defaults.

ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS identity_key       JSONB;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS canonical_id       TEXT;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS revision           INTEGER NOT NULL DEFAULT 1;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS evidence           JSONB NOT NULL DEFAULT '[]';
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS contradicting      JSONB NOT NULL DEFAULT '[]';
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS confidence         TEXT;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS confidence_score   DOUBLE PRECISION;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS corroboration_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS maturity           TEXT NOT NULL DEFAULT 'candidate';
ALTER TABLE learning.experiences ADD COLUMN IF NOT EXISTS superseded_by      UUID;

-- The consolidator drives active/contested/superseded/deprecated/archived transitions; the original
-- 0011 CHECK only admitted active/reverted. Widen it (keeping 'reverted' for the governed revert path).
ALTER TABLE learning.experiences DROP CONSTRAINT IF EXISTS learning_experiences_status_check;
ALTER TABLE learning.experiences
    ADD CONSTRAINT learning_experiences_status_check CHECK (
        status IN ('active', 'contested', 'deprecated', 'superseded', 'archived', 'reverted')
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'learning_experiences_maturity_check'
    ) THEN
        ALTER TABLE learning.experiences
            ADD CONSTRAINT learning_experiences_maturity_check
            CHECK (maturity IN ('candidate', 'verified', 'established'));
    END IF;
END $$;

-- A logical experience owns its revision chain (mirrors knowledge.findings after 0033).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'learning_experiences_canonical_revision_uniq'
    ) THEN
        ALTER TABLE learning.experiences
            ADD CONSTRAINT learning_experiences_canonical_revision_uniq
            UNIQUE (canonical_id, revision);
    END IF;
END $$;

-- find_active_by_identity is the consolidator's hot lookup.
CREATE INDEX IF NOT EXISTS idx_learning_experiences_identity
    ON learning.experiences (identity_key);
CREATE INDEX IF NOT EXISTS idx_learning_experiences_canonical
    ON learning.experiences (canonical_id);
CREATE INDEX IF NOT EXISTS idx_learning_experiences_maturity
    ON learning.experiences (maturity);
