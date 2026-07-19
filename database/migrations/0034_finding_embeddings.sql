-- Atlas Migration 0034: knowledge.finding_embeddings (Phase C · PHASE_C_PLAN §C.3, CC4 hybrid identity)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Hybrid identity (CC4): structured/engineering findings dedup on a deterministic identity_key, but
-- prose findings need semantic dedup — "Redis is required" and "the system depends on Redis" are the
-- same fact. Store one embedding per (finding, model) so the Consolidator can, when there is no
-- deterministic match, find the nearest ACTIVE finding by cosine similarity (ANN) and merge evidence
-- into it instead of creating a duplicate. Mirrors knowledge.embeddings (chunk vectors): vector(768)
-- for nomic-embed-text, HNSW cosine index. Re-embed with a new model without losing history.

CREATE TABLE IF NOT EXISTS knowledge.finding_embeddings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id   UUID NOT NULL REFERENCES knowledge.findings(id) ON DELETE CASCADE,
    model        TEXT NOT NULL,
    dim          INTEGER NOT NULL,
    embedding    vector(768) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_finding_embeddings_finding_model UNIQUE (finding_id, model)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_finding_embeddings_hnsw_cosine
    ON knowledge.finding_embeddings USING hnsw (embedding vector_cosine_ops);
