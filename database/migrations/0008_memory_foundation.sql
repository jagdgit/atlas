-- Atlas Migration 0008: Memory Foundation (memory.items)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`
-- (atlas owns the `memory` schema from 0001 — no superuser round-trip needed).
--
-- One logical table for all three memory kinds (ADR-0048), engineered for scale:
--   working   — short-term, session-scoped, expires (expires_at)
--   episodic  — append-heavy event log, time-ordered by occurred_at
--   semantic  — durable, embedded facts recalled by similarity
--
-- Scale strategy (single table now; repo-isolated so physical layout can evolve):
--   * embedding is NULLABLE and the HNSW vector index is PARTIAL
--     (WHERE embedding IS NOT NULL), so non-embedded / working rows never bloat
--     the index that semantic recall depends on.
--   * occurred_at is the event-time "date" dimension (distinct from created_at),
--     indexed for time-ordered recall and ready for a future RANGE-by-date
--     partitioning migration if volume demands it.
--   * expires_at drives working-memory eviction; recall filters expired rows and a
--     prune job reclaims them.

CREATE TABLE IF NOT EXISTS memory.items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            TEXT NOT NULL,                 -- working | episodic | semantic
    scope           TEXT NOT NULL DEFAULT 'global', -- session id or 'global'
    content         TEXT NOT NULL,
    embedding       vector(768),                   -- NULL until/unless embedded
    embedding_model TEXT,                          -- which model produced `embedding`
    importance      REAL NOT NULL DEFAULT 0.0,     -- ranking / eviction priority
    metadata        JSONB NOT NULL DEFAULT '{}',
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(), -- event time (the date dimension)
    expires_at      TIMESTAMPTZ,                   -- NULL = never expires
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memory_items_kind_check
        CHECK (kind IN ('working', 'episodic', 'semantic'))
);

-- Partial ANN index: only embedded rows participate in vector search (keeps the
-- HNSW index small even when episodic/working rows are numerous).
CREATE INDEX IF NOT EXISTS idx_memory_items_hnsw_cosine
    ON memory.items USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

-- Time-ordered recall per kind (episodic "what happened recently / around a date").
CREATE INDEX IF NOT EXISTS idx_memory_items_kind_occurred
    ON memory.items (kind, occurred_at DESC);

-- Scope lookups (per-session working memory, etc.).
CREATE INDEX IF NOT EXISTS idx_memory_items_scope_occurred
    ON memory.items (scope, occurred_at DESC);

-- Prune support: find expired rows cheaply.
CREATE INDEX IF NOT EXISTS idx_memory_items_expires
    ON memory.items (expires_at)
    WHERE expires_at IS NOT NULL;
