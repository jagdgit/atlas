"""Tests for the AssistantService chat orchestrator (Sprint 10).

Hermetic: a real Planner + ConversationService (in-memory repo) drive real routing
and persistence, while knowledge/memory/agent/llm are fakes. No DB/Ollama.
"""

from __future__ import annotations

import uuid

from atlas.agents.base import AgentResult, Citation
from atlas.conversation import ConversationService
from atlas.execution import ToolExecutor
from atlas.kernel.tools import ToolRegistry
from atlas.llm.provider import LLMResponse
from atlas.models import ConversationMessage, ConversationSession, MemoryItem
from atlas.planner import Planner
from atlas.services.assistant_service import AssistantService, ChatTurn


class FakeConvRepo:
    def __init__(self):
        self.sessions = {}
        self.messages = {}

    def create_session(self, *, title=None, metadata=None):
        sid = str(uuid.uuid4())
        self.sessions[sid] = ConversationSession(id=sid, title=title, metadata=metadata or {})
        self.messages[sid] = []
        return self.sessions[sid]

    def get_session(self, session_id):
        return self.sessions.get(str(session_id))

    def list_sessions(self, *, limit=50):
        return list(self.sessions.values())[:limit]

    def touch_session(self, session_id):
        pass

    def add_message(self, session_id, role, content, *, tool_calls=None):
        sid = str(session_id)
        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            session_id=sid,
            ordinal=len(self.messages[sid]),
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
    def __init__(self):
        self.remembered = []
        self.recall_results = []

    def remember(self, content, *, kind="semantic", scope="global", **kw):
        item = MemoryItem(id="mem-1", kind=kind, content=content, scope=scope)
        self.remembered.append(item)
        return item

    def recall(self, query, *, scope=None, limit=5, kind=None):
        return self.recall_results


class FakeKnowledge:
    def __init__(self, docs=None):
        self._docs = docs or []
        self.ingested = None

    def list_documents(self, *, limit=25):
        return self._docs

    def ingest_text(self, source, content, **kw):
        self.ingested = (source, content, kw)
        return {"document_id": "doc-1", "status": "embedded", "chunks": 2, "deduped": False}


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, name, query, **options):
        self.calls.append((name, query))
        if name == "rag":
            return AgentResult(
                answer="It says Atlas is an AI OS [1].",
                citations=[Citation(1, "doc-1", "chunk-1", 0.9, "Atlas is an AI OS.")],
                usage={},
                run_id="run-rag",
            )
        return AgentResult(answer="96", citations=[], usage={"tools_used": []}, run_id="run-react")


class _RoleStub:
    def chat(self, messages, **options):
        return LLMResponse(text="SUMMARY", model="fake")


class FakeLLM:
    def for_role(self, role):
        return _RoleStub()


def _assistant(
    *, memory=None, knowledge=None, agent=None, with_web=True, with_search=True,
    search_result=None, capabilities=None,
):
    tools = ToolRegistry()
    if with_web:
        tools.register("web.fetch", lambda url: f"page content for {url}")
    if with_search:
        default = {
            "query": "q",
            "provider": "duckduckgo",
            "outcome": "ok",
            "results": [
                {"title": "Result A", "url": "https://a.example", "snippet": "about x"}
            ],
        }
        payload = search_result if search_result is not None else default
        tools.register("web.search", lambda query, max_results=5: payload)
    return AssistantService(
        ConversationService(FakeConvRepo(), memory),
        Planner(),
        ToolExecutor(tools, retry_base=0.0),
        knowledge=knowledge or FakeKnowledge(),
        memory=memory,
        agent=agent or FakeAgent(),
        llm=FakeLLM(),
        tools=tools,
        capabilities=capabilities,
    )


# --- per-intent behaviour -------------------------------------------------
def test_remember_stores_and_confirms():
    mem = FakeMemory()
    turn = _assistant(memory=mem).chat("Remember that I prefer PostgreSQL over Milvus.")
    assert isinstance(turn, ChatTurn)
    assert turn.intent == "remember"
    assert mem.remembered[0].content == "I prefer PostgreSQL over Milvus."
    assert "remember" in turn.answer.lower()
    assert turn.tool_calls[0]["action"] == "remember"


def test_recall_lists_memories():
    mem = FakeMemory()
    mem.recall_results = [MemoryItem(id="m", kind="semantic", content="prefers PostgreSQL")]
    turn = _assistant(memory=mem).chat("What do you remember about my preferences?")
    assert turn.intent == "recall"
    assert "prefers PostgreSQL" in turn.answer


def test_recall_when_empty_is_honest():
    turn = _assistant(memory=FakeMemory()).chat("what do you remember about me?")
    assert turn.intent == "recall"
    assert "don't have anything" in turn.answer.lower()


def test_list_documents_lists_titles():
    docs = [_doc("Solar Report", "embedded"), _doc("Notes", "chunked")]
    turn = _assistant(knowledge=FakeKnowledge(docs)).chat("What documents do you know about?")
    assert turn.intent == "list_documents"
    assert "Solar Report" in turn.answer and "Notes" in turn.answer


def test_list_documents_empty_is_honest():
    turn = _assistant(knowledge=FakeKnowledge([])).chat("what documents do you have?")
    assert "empty" in turn.answer.lower()


def test_ask_knowledge_uses_rag_and_returns_citations():
    agent = FakeAgent()
    turn = _assistant(agent=agent).chat("What does it say?")
    assert turn.intent == "ask_knowledge"
    assert ("rag", "What does it say?") in agent.calls
    assert turn.citations[0]["document_id"] == "doc-1"
    assert turn.run_id == "run-rag"


def test_general_question_uses_react():
    agent = FakeAgent()
    turn = _assistant(agent=agent).chat("What is 12 times 8?")
    assert turn.intent == "react"
    assert agent.calls[0][0] == "assistant"


def test_smalltalk_uses_llm_composition():
    turn = _assistant().chat("hello there")
    assert turn.intent == "smalltalk"
    assert turn.answer == "SUMMARY"


def test_web_fetch_summarizes():
    turn = _assistant().chat("fetch https://example.com")
    assert turn.intent == "web_fetch"
    assert turn.answer == "SUMMARY"
    assert turn.tool_calls[0]["ok"] is True


def test_web_search_lists_results():
    turn = _assistant().chat("search the web for solar soiling losses")
    assert turn.intent == "web_search"
    assert "Result A" in turn.answer
    assert "https://a.example" in turn.answer
    assert turn.tool_calls[0]["action"] == "web.search"
    assert turn.tool_calls[0]["ok"] is True


def test_web_search_reports_blocked_outcome_honestly():
    blocked = {"query": "q", "provider": "duckduckgo", "outcome": "blocked",
               "results": [], "reason": "HTTP 403"}
    turn = _assistant(search_result=blocked).chat("search the web for anything")
    assert turn.intent == "web_search"
    assert "unavailable" in turn.answer.lower()


def test_web_search_no_results_is_honest():
    empty = {"query": "q", "provider": "duckduckgo", "outcome": "ok", "results": []}
    turn = _assistant(search_result=empty).chat("search the web for zzzz")
    assert "no web results" in turn.answer.lower()


def test_search_gap_when_no_search_tool():
    turn = _assistant(with_search=False).chat("search the web for solar soiling")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "search"


def test_ingest_without_path_asks_for_one():
    turn = _assistant().chat("Read this PDF.")
    assert turn.intent == "ingest_path"
    assert "path" in turn.answer.lower()


def test_ingest_reads_and_ingests(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# Title\n\nAtlas is great.", encoding="utf-8")
    knowledge = FakeKnowledge()
    turn = _assistant(knowledge=knowledge).chat(f"ingest {doc}")
    assert turn.intent == "ingest_path"
    assert knowledge.ingested is not None
    assert "note.md" in turn.answer


# --- capability honesty (R2) ---------------------------------------------
def test_capability_gap_when_memory_missing():
    # No memory service => the 'remember' capability is unavailable.
    turn = _assistant(memory=None).chat("Remember that I like tea.")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "memory"
    assert "missing" in turn.answer.lower()


def test_web_gap_when_no_web_tool():
    turn = _assistant(with_web=False).chat("fetch https://example.com")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "web"


def test_gap_preflight_uses_capability_registry_when_wired():
    # With a registry, it is the source of truth: 'web' isn't registered here, so a
    # fetch is a gap even though the web.fetch tool exists.
    from atlas.capabilities import MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register("memory", FakeMemory(), contract=MemoryCapability, kind="service")
    turn = _assistant(with_web=True, capabilities=reg).chat("fetch https://example.com")
    assert turn.capability_gaps
    gap = turn.capability_gaps[0]
    assert gap["missing_capability"] == "web"
    assert gap["unlocks"]  # enriched from the capability catalog
    assert gap["since"] == "S7"


def test_no_gap_when_registry_provides_capability():
    from atlas.capabilities import MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    mem = FakeMemory()
    reg.register("memory", mem, contract=MemoryCapability, kind="service")
    turn = _assistant(memory=mem, capabilities=reg).chat("Remember that I like tea.")
    assert turn.capability_gaps == []
    assert turn.intent == "remember"


# --- session persistence --------------------------------------------------
def test_turns_persist_to_same_session():
    assistant = _assistant(memory=FakeMemory())
    first = assistant.chat("hello there")
    second = assistant.chat("hello again", session_id=first.session_id)
    assert second.session_id == first.session_id
    history = assistant._conversation.history(first.session_id)
    assert len(history) == 4  # 2 user + 2 assistant turns
    assert history[-1].tool_calls  # assistant turn records what it did


def _doc(title, status):
    from atlas.models import Document

    return Document(
        id=str(uuid.uuid4()), source="chat", checksum="x", title=title, status=status
    )
