-- Atlas Migration 0006: Knowledge Foundation (documents, chunks, embeddings)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Pipeline model: a document is ingested (status 'pending'), split into ordered
-- chunks (status 'chunked'), then each chunk is embedded (status 'embedded').
-- Embeddings live in their own table keyed by (chunk, model) so we can re-embed
-- with a different model without losing history. The vector dimension (768) is
-- fixed to the default embedding model 'nomic-embed-text'.

-- Documents: a source item ingested into Atlas' knowledge base.
CREATE TABLE IF NOT EXISTS knowledge.documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,                 -- 'file' | 'web' | 'note' | ...
    uri             TEXT,                          -- path / url / external id
    title           TEXT,
    content_type    TEXT NOT NULL DEFAULT 'text/plain',
    content         TEXT,                          -- original text (provenance)
    checksum        TEXT NOT NULL,                 -- sha256(content) for dedup/drift
    metadata        JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_documents_status_check
        CHECK (status IN ('pending', 'chunked', 'embedded', 'failed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_documents_checksum
    ON knowledge.documents (checksum);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status
    ON knowledge.documents (status);

-- Chunks: ordered segments of a document.
CREATE TABLE IF NOT EXISTS knowledge.chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,              -- 0-based position in document
    content         TEXT NOT NULL,
    token_count     INTEGER,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_chunks_doc_ordinal UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
    ON knowledge.chunks (document_id);

-- Embeddings: one vector per (chunk, model). 768 dims = nomic-embed-text.
CREATE TABLE IF NOT EXISTS knowledge.embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id        UUID NOT NULL REFERENCES knowledge.chunks(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    dim             INTEGER NOT NULL,
    embedding       vector(768) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_embeddings_chunk_model UNIQUE (chunk_id, model)
);

-- Approximate nearest-neighbour index (cosine). HNSW needs pgvector >= 0.5.
CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_hnsw_cosine
    ON knowledge.embeddings USING hnsw (embedding vector_cosine_ops);
