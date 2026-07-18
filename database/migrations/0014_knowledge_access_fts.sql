-- Atlas Migration 0014: Knowledge Access Layer FTS + retrieval diagnostics (Stage 3B.1)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Adds Postgres full-text search on chunk content (A3B.3) and a diagnostics table
-- that persists dense/lexical/rrf scores for later hybrid weight tuning (D3B.30).

ALTER TABLE knowledge.chunks
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_tsv
    ON knowledge.chunks USING gin (content_tsv);

CREATE TABLE IF NOT EXISTS knowledge.retrieval_diagnostics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query           TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'research',
    mode            TEXT NOT NULL DEFAULT 'hybrid',
    domains         TEXT[],
    tiers           TEXT[],
    hits            JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_diagnostics_created
    ON knowledge.retrieval_diagnostics (created_at DESC);
