-- Atlas Migration 0016: Finding lifecycle indexes + review queue (Stage 3B.3)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Supports append-only consolidation: identity lookup for merge, and a review queue
-- for component-bug invalidation (mark stale + enqueue review/reprocess).

ALTER TABLE knowledge.findings
    ADD COLUMN IF NOT EXISTS identity_key JSONB;

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_identity_key
    ON knowledge.findings USING gin (identity_key);

CREATE INDEX IF NOT EXISTS idx_knowledge_findings_canonical_revision
    ON knowledge.findings (canonical_id, revision DESC);

CREATE TABLE IF NOT EXISTS knowledge.finding_reviews (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id      UUID NOT NULL REFERENCES knowledge.findings(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL DEFAULT '',
    component_id    TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_finding_reviews_status_check
        CHECK (status IN ('pending', 'done', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_finding_reviews_pending
    ON knowledge.finding_reviews (status, created_at DESC)
    WHERE status = 'pending';
