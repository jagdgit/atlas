"""Tests for the ConversationService (Sprint 10, D3).

Hermetic: an in-memory fake repository stands in for the ``conversation`` schema,
and a fake memory service exercises context assembly. No DB/Ollama.
"""

from __future__ import annotations

import uuid

from atlas.conversation import ConversationContext, ConversationService
from atlas.llm.provider import EmbeddingResponse  # noqa: F401 (parity import)
from atlas.models import ConversationMessage, ConversationSession, MemoryItem


class FakeConvRepo:
    def __init__(self):
        self.sessions: dict[str, ConversationSession] = {}
        self.messages: dict[str, list[ConversationMessage]] = {}

    def create_session(self, *, title=None, metadata=None):
        sid = str(uuid.uuid4())
        session = ConversationSession(id=sid, title=title, metadata=metadata or {})
        self.sessions[sid] = session
        self.messages[sid] = []
        return session

    def get_session(self, session_id):
        return self.sessions.get(str(session_id))

    def list_sessions(self, *, limit=50):
        return list(self.sessions.values())[:limit]

    def touch_session(self, session_id):
        pass

    def add_message(self, session_id, role, content, *, tool_calls=None):
        sid = str(session_id)
        ordinal = len(self.messages[sid])
        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            session_id=sid,
            ordinal=ordinal,
            role=role,
            content=content,
            tool_calls=tool_calls or [],
        )
        self.messages[sid].append(msg)
        return msg

    def history(self, session_id, *, limit=None):
        msgs = self.messages.get(str(session_id), [])
        return msgs[-limit:] if limit else list(msgs)

    def count_sessions(self):
        return len(self.sessions)


class FakeMemory:
    def __init__(self, results=None, raises=False):
        self.results = results or []
        self.raises = raises
        self.recall_scope = None

    def recall(self, query, *, scope=None, limit=5, kind=None):
        self.recall_scope = scope
        if self.raises:
            raise RuntimeError("recall down")
        return self.results


def _service(repo=None, memory=None, **kw):
    return ConversationService(repo or FakeConvRepo(), memory, **kw)


def test_ensure_session_creates_when_none():
    svc = _service()
    session = svc.ensure_session(None)
    assert session.id
    assert svc.get_session(session.id) is not None


def test_ensure_session_returns_existing():
    repo = FakeConvRepo()
    svc = _service(repo)
    existing = svc.start_session()
    assert svc.ensure_session(existing.id).id == existing.id


def test_ensure_session_unknown_id_starts_new():
    svc = _service()
    session = svc.ensure_session("does-not-exist")
    assert session.id != "does-not-exist"


def test_messages_get_increasing_ordinals():
    svc = _service()
    s = svc.start_session()
    svc.add_user_message(s.id, "hello")
    svc.add_assistant_message(s.id, "hi", tool_calls=[{"action": "smalltalk"}])
    history = svc.history(s.id)
    assert [m.ordinal for m in history] == [0, 1]
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].tool_calls == [{"action": "smalltalk"}]


def test_history_limit_returns_recent_in_order():
    svc = _service(max_context_turns=2)
    s = svc.start_session()
    for i in range(5):
        svc.add_user_message(s.id, f"m{i}")
    recent = svc.history(s.id, limit=2)
    assert [m.content for m in recent] == ["m3", "m4"]


def test_build_context_includes_recent_and_memories():
    mem = FakeMemory(results=[MemoryItem(id="1", kind="semantic", content="likes tea")])
    svc = _service(memory=mem, working_memory_k=3)
    s = svc.start_session()
    svc.add_user_message(s.id, "earlier turn")
    ctx = svc.build_context(s.id, "what do I like?")
    assert isinstance(ctx, ConversationContext)
    assert mem.recall_scope == s.id  # working memory scoped to the session
    assert any("likes tea" in m.content for m in ctx.memories)
    assert ctx.as_chat_messages()[0].content == "earlier turn"
    assert "likes tea" in ctx.memory_block()


def test_build_context_survives_memory_failure():
    svc = _service(memory=FakeMemory(raises=True))
    s = svc.start_session()
    ctx = svc.build_context(s.id, "anything")
    assert ctx.memories == []  # best-effort: failure doesn't crash the turn


def test_health_reports_session_count():
    svc = _service()
    svc.start_session()
    status = svc.health_check()
    assert status.healthy
    assert "1" in status.detail
