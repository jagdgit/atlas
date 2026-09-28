"""OI-LAB-LOOP0 Step 11 — Day-1 finding survives restart into RAG → LLM context."""

from __future__ import annotations

from pathlib import Path

from atlas.agents.rag_agent import RagAgent
from atlas.knowledge.access import TIER_FINDINGS
from atlas.knowledge.restart_canary import (
    CANARY_TOKEN,
    QUERY,
    STATEMENT,
    load_marker,
    retrieve_canary,
    run_tick,
    store_canary,
)
from atlas.knowledge.service import KnowledgeService
from atlas.llm.provider import LLMResponse
from tests.test_knowledge import FakeLLM, _service
from tests.test_lab_loop0_findings_rag import FakeFindingEmb, FakeFindingRepo, _wire_finding


class EchoLLM(FakeLLM):
    """Chat echoes the canary sentence when it is in the prompt."""

    def __init__(self):
        super().__init__()
        self.last_messages = None
        self.calls = 0

    def chat(self, messages, **kw):
        del kw
        self.calls += 1
        self.last_messages = messages
        blob = "\n".join(str(getattr(m, "content", m)) for m in messages)
        if CANARY_TOKEN in blob or "Setup X performed poorly" in blob:
            text = (
                "Setup X performed poorly when regime Y was present [1]. "
                f"{CANARY_TOKEN}"
            )
        else:
            text = "I don't have information about that in my knowledge base."
        return LLMResponse(text=text, model="fake-chat", usage={"tokens": 8})


def _restart_service(docs, chunks, embs, findings, femb):
    """New KnowledgeService on the same durable finding stores (process restart)."""
    llm = EchoLLM()
    svc = KnowledgeService(
        docs,
        chunks,
        embs,
        llm,
        embedding_model="fake-embed",
        chunk_max_words=5,
        chunk_overlap=1,
    )
    svc._findings = findings
    svc._finding_embeddings = femb
    return svc, llm


def test_store_then_restart_retrieve_and_llm_cite(tmp_path: Path):
    svc, docs, chunks, embs = _service()
    findings, femb = _wire_finding(svc, statement="unrelated cats", finding_id="f-other")
    n_chunk_vecs = len(embs.vectors)
    n_chunks = sum(len(v) for v in chunks.by_doc.values())

    day1 = store_canary(svc, tmp_path, findings=findings, finding_embeddings=femb)
    assert day1["ok"] is True
    assert day1["chunk_smash"] is False
    assert day1["not_a_trade"] is True
    marker = load_marker(tmp_path)
    assert marker["token"] == CANARY_TOKEN
    assert len(embs.vectors) == n_chunk_vecs
    assert sum(len(v) for v in chunks.by_doc.values()) == n_chunks

    svc2, llm = _restart_service(docs, chunks, embs, findings, femb)
    retrieved = retrieve_canary(svc2, query=QUERY)
    assert retrieved["retrieved"] is True
    assert any(h["tier"] == TIER_FINDINGS for h in retrieved["hits"])
    assert any(CANARY_TOKEN in h["content"] for h in retrieved["hits"])

    agent = RagAgent(svc2, llm, None, similarity_floor=0.0)
    day2 = run_tick(svc2, tmp_path, rag_agent=agent)
    assert day2["retrieved"]["retrieved"] is True
    assert day2["cited"]["in_prompt"] is True
    assert day2["cited"]["in_answer"] is True
    assert CANARY_TOKEN in day2["cited"]["answer"]
    assert llm.calls == 1
    assert len(embs.vectors) == n_chunk_vecs
    assert sum(len(v) for v in chunks.by_doc.values()) == n_chunks

    again = run_tick(svc2, tmp_path, rag_agent=agent)
    assert again.get("skipped") is True
    assert again.get("reason") == "canary_complete"


def test_run_tick_stores_on_first_call(tmp_path: Path):
    svc, _docs, _chunks, _embs = _service()
    findings = FakeFindingRepo()
    femb = FakeFindingEmb()
    svc._findings = findings
    svc._finding_embeddings = femb
    out = run_tick(svc, tmp_path)
    assert out["phase"] == "day1_stored"
    assert STATEMENT[:20] in out["statement"]
    assert FakeFindingRepo is type(findings)
    assert any(CANARY_TOKEN in str(r.get("statement")) for r in findings.rows)
