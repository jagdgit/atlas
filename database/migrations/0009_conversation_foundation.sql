-- Atlas Migration 0009: Conversation Foundation (conversation schema)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`
-- (atlas owns the database, so it may create the schema itself — no superuser
-- round-trip needed, same pattern as 0007's `agent` schema).
--
-- Stage 2 / Sprint 10 (D3): first-class conversational context. A `session` is a
-- multi-turn thread; `messages` are its ordered transcript. This is deliberately
-- separate from `memory.items` (ADR-0048): the transcript is *what was said*,
-- while remembered facts are *what to keep* — working memory is `memory.items`
-- scoped to the session id, not a copy of the chat log.

CREATE SCHEMA IF NOT EXISTS conversation AUTHORIZATION atlas;

-- A conversation thread. `metadata` carries free-form context (client, labels).
CREATE TABLE IF NOT EXISTS conversation.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated
    ON conversation.sessions (updated_at DESC);

-- The ordered transcript. `ordinal` is a per-session, 0-based sequence so history
-- reads are deterministic and gap-detectable. `tool_calls` records what the turn
-- did (planner intent, tools invoked) for observability and later job reuse.
CREATE TABLE IF NOT EXISTS conversation.messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES conversation.sessions(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,              -- 0-based position within the session
    role            TEXT NOT NULL,                 -- 'user' | 'assistant' | 'system'
    content         TEXT NOT NULL DEFAULT '',
    tool_calls      JSONB NOT NULL DEFAULT '[]',   -- [{intent, tool, args, ok}, ...]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT conversation_messages_role_check
        CHECK (role IN ('user', 'assistant', 'system')),
    CONSTRAINT uq_conversation_messages_session_ordinal UNIQUE (session_id, ordinal)
);

-- Fast, ordered history reads per session.
CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_ordinal
    ON conversation.messages (session_id, ordinal);
