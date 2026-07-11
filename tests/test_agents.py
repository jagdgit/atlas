"""Tests for the agent layer: RagAgent and AgentService.

Agent logic is tested with in-memory fakes (no DB, no Ollama). An integration
test exercises the real stack (Postgres + Ollama) and skips if either is down.
"""

from __future__ import annotations

import httpx
import psycopg
import pytest

from atlas.agents.base import Agent, AgentResult
from atlas.agents.rag_agent import RagAgent, _NO_CONTEXT_ANSWER
from atlas.config import get_config
from atlas.exceptions import AgentNotFoundError
from atlas.knowledge.service import SearchResult
from atlas.llm.provider import LLMResponse
from atlas.services.agent_service import AgentService


# --- fakes ----------------------------------------------------------------
class FakeKnowledge:
    def __init__(self, results):
        self._results = results
        self.last_query = None
        self.last_limit = None

    def search(self, query, *, limit=5):
        self.last_query = query
        self.last_limit = limit
        return self._results[:limit]


class FakeLLM:
    def __init__(self, text="an answer [1]"):
        self._text = text
        self.calls = 0
        self.last_messages = None

    def chat(self, messages, **kw):
        self.calls += 1
        self.last_messages = messages
        return LLMResponse(text=self._text, model="fake-chat", usage={"tokens": 3})


def _result(cid, did, ordinal, content, similarity):
    return SearchResult(
        chunk_id=cid,
        document_id=did,
        ordinal=ordinal,
        content=content,
        distance=1.0 - similarity,
        similarity=similarity,
    )


# --- RagAgent -------------------------------------------------------------
def test_rag_answers_from_context_with_citations():
    kb = FakeKnowledge(
        [
            _result("c1", "d1", 0, "Atlas uses a scheduler for background jobs.", 0.8),
            _result("c2", "d2", 1, "Embeddings are stored in pgvector.", 0.6),
        ]
    )
    llm = FakeLLM(text="Atlas schedules jobs [1] and stores vectors [2].")
    agent = RagAgent(kb, llm, None, retrieval_k=5, similarity_floor=0.35)

    result = agent.run("How does Atlas work?")

    assert isinstance(result, AgentResult)
    assert llm.calls == 1
    assert len(result.citations) == 2
    assert result.citations[0].index == 1
    assert result.citations[0].document_id == "d1"
    assert result.citations[0].chunk_id == "c1"
    assert "Sources:" in result.answer
    assert result.usage["used"] == 2
    # The assembled context must number the chunks for the model.
    user_msg = llm.last_messages[-1].content
    assert "[1]" in user_msg and "[2]" in user_msg


def test_rag_filters_below_similarity_floor():
    kb = FakeKnowledge(
        [
            _result("c1", "d1", 0, "relevant", 0.9),
            _result("c2", "d2", 1, "weak", 0.1),
        ]
    )
    llm = FakeLLM()
    agent = RagAgent(kb, llm, None, similarity_floor=0.5)
    result = agent.run("q")
    assert len(result.citations) == 1  # weak chunk dropped
    assert result.citations[0].chunk_id == "c1"


def test_rag_strict_no_context_returns_dont_know():
    kb = FakeKnowledge([_result("c1", "d1", 0, "unrelated", 0.1)])
    llm = FakeLLM()
    agent = RagAgent(kb, llm, None, similarity_floor=0.5, grounding="strict")
    result = agent.run("q")
    assert result.answer == _NO_CONTEXT_ANSWER
    assert result.citations == []
    assert llm.calls == 0  # short-circuit: no generation


def test_rag_blended_generates_without_context():
    kb = FakeKnowledge([])
    llm = FakeLLM(text="from my own knowledge (not from knowledge base)")
    agent = RagAgent(kb, llm, None, grounding="blended")
    result = agent.run("q")
    assert llm.calls == 1
    assert result.citations == []


def test_rag_respects_max_context_chars():
    big = "word " * 100  # ~500 chars each
    kb = FakeKnowledge(
        [_result(f"c{i}", f"d{i}", i, big, 0.9) for i in range(5)]
    )
    llm = FakeLLM()
    agent = RagAgent(kb, llm, None, similarity_floor=0.0, max_context_chars=600)
    result = agent.run("q")
    # First chunk always included; the cap prevents adding all five.
    assert 1 <= len(result.citations) < 5


def test_rag_options_override_k_and_grounding():
    kb = FakeKnowledge([_result("c1", "d1", 0, "x", 0.9)])
    llm = FakeLLM()
    agent = RagAgent(kb, llm, None, retrieval_k=5)
    agent.run("q", k=2)
    assert kb.last_limit == 2


# --- AgentService ---------------------------------------------------------
class FakeAgent:
    name = "fake"
    kind = "fake"

    def __init__(self):
        self.ran = None

    def run(self, query, **options):
        self.ran = (query, options)
        return AgentResult(answer=f"echo:{query}", citations=[], usage={}, run_id=None)


def test_agent_service_registers_and_runs():
    fake = FakeAgent()
    svc = AgentService(agents=[fake])
    assert svc.list() == ["fake"]
    result = svc.run("fake", "hello")
    assert result.answer == "echo:hello"
    assert fake.ran == ("hello", {})


def test_agent_service_unknown_agent_raises():
    svc = AgentService(agents=[])
    with pytest.raises(AgentNotFoundError):
        svc.run("nope", "q")


def test_agent_service_health_reflects_registration():
    assert AgentService(agents=[]).health_check().healthy is False
    assert AgentService(agents=[FakeAgent()]).health_check().healthy is True


def test_agent_service_run_agent_task_returns_dict():
    svc = AgentService(agents=[FakeAgent()])
    out = svc.run_agent_task({"agent": "fake", "query": "hi"})
    assert out["agent"] == "fake"
    assert out["answer"] == "echo:hi"


def test_rag_agent_conforms_to_protocol():
    kb = FakeKnowledge([])
    assert isinstance(RagAgent(kb, FakeLLM(), None), Agent)


# --- integration: real Postgres + Ollama ---------------------------------
def _stack_or_skip():
    conninfo = get_config().database.conninfo
    try:
        with psycopg.connect(conninfo, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    host = get_config().llm.host
    try:
        httpx.get(f"{host}/api/tags", timeout=2.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ollama unreachable: {exc}")


def test_integration_rag_end_to_end():
    _stack_or_skip()
    from atlas.database.connection import DatabaseManager
    from atlas.llm.ollama_provider import OllamaProvider
    from atlas.llm.service import LLMService
    from atlas.knowledge.service import KnowledgeService
    from atlas.repositories.agent_run_repo import AgentRunRepository
    from atlas.repositories.chunk_repo import ChunkRepository
    from atlas.repositories.document_repo import DocumentRepository
    from atlas.repositories.embedding_repo import EmbeddingRepository

    cfg = get_config()
    db = DatabaseManager()
    provider = OllamaProvider(
        host=cfg.llm.host,
        model=cfg.llm.model,
        embedding_model=cfg.llm.embedding_model,
    )
    if not any(
        m.startswith(cfg.llm.embedding_model) for m in provider.list_models()
    ):
        provider.close()
        db.close()
        pytest.skip("embedding model not installed")

    llm = LLMService(
        provider, model=cfg.llm.model, embedding_model=cfg.llm.embedding_model
    )
    doc_repo = DocumentRepository(db)
    kb = KnowledgeService(
        doc_repo,
        ChunkRepository(db),
        EmbeddingRepository(db),
        llm,
        embedding_model=cfg.llm.embedding_model,
    )
    run_repo = AgentRunRepository(db)
    agent = RagAgent(kb, llm, run_repo, retrieval_k=3, similarity_floor=0.2)

    text = (
        "Atlas runs background work through a scheduler with worker threads. "
        "The scheduler retries failed tasks with exponential backoff and recovers "
        "interrupted tasks after a crash, so jobs survive power loss."
    )
    summary = kb.ingest_text("test_agent", text, title="scheduler notes")
    doc_id = summary["document_id"]
    try:
        result = agent.run("How does Atlas recover jobs after a crash?")
        assert result.answer
        assert result.citations  # grounded answer cites sources
        assert result.run_id
        # The run was persisted with an ordered step trace.
        run = run_repo.get_run(result.run_id)
        assert run["status"] == "completed"
        steps = run_repo.list_steps(result.run_id)
        assert [s["kind"] for s in steps] == ["retrieve", "generate"]
    finally:
        doc_repo.delete(doc_id)  # cascades chunks + embeddings
        provider.close()
        db.close()
