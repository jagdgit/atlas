"""M4-RAG-LIVE Step 2 — RAG answers expose finding/document provenance.

Does not change retrieval ranking. Noisy hits 2–5 stay frozen.
"""

from __future__ import annotations

from atlas.agents.base import Citation
from atlas.agents.rag_agent import RagAgent
from atlas.api.schemas import CitationOut, SearchResultOut
from atlas.knowledge.access import (
    TIER_FINDINGS,
    TIER_KNOWLEDGE,
    RankedHit,
    build_context,
    finding_id_of,
    fuse_dense_lexical,
    heuristic_rerank,
    hit_provenance,
)
from atlas.llm.provider import LLMResponse
from tests.test_knowledge import FakeLLM, _service
from tests.test_lab_loop0_findings_rag import _wire_finding


class _EchoLLM(FakeLLM):
    def chat(self, messages, **kw):
        del kw
        blob = "\n".join(str(getattr(m, "content", m)) for m in messages)
        return LLMResponse(text=blob[:200], model="fake-chat", usage={"tokens": 8})


def test_citation_as_dict_exposes_m4_provenance_fields():
    cite = Citation(
        index=1,
        document_id="F-002118",
        chunk_id="finding:2c15a393-b9cc-4d7a-ac61-c4d9d8e7f628",
        similarity=0.6942,
        snippet="Setup X performed poorly when regime Y was present.",
        finding_id="2c15a393-b9cc-4d7a-ac61-c4d9d8e7f628",
        source="findings",
        timestamp="2026-09-18T12:25:31.703825+00:00",
        score=0.03985,
    )
    d = cite.as_dict()
    assert d["finding_id"] == "2c15a393-b9cc-4d7a-ac61-c4d9d8e7f628"
    assert d["document_id"] == "F-002118"
    assert d["source"] == "findings"
    assert d["timestamp"].startswith("2026-09-18")
    assert d["score"] == 0.03985
    CitationOut.model_validate(d)


def test_finding_id_parsed_from_chunk_id_when_explicit_missing():
    hit = RankedHit(
        chunk_id="finding:abc-123",
        document_id="F-000001",
        ordinal=0,
        content="validated",
        tier=TIER_FINDINGS,
        similarity=0.7,
        score=0.04,
    )
    assert finding_id_of(hit) == "abc-123"
    assert hit_provenance(hit)["source"] == "findings"


def test_fuse_and_rerank_preserve_provenance_without_reordering():
    dense = [
        {
            "chunk_id": "finding:fid-1",
            "document_id": "F-1",
            "ordinal": 0,
            "content": "Setup X performed poorly when regime Y was present.",
            "distance": 0.3,
            "finding_id": "fid-1",
            "created_at": "2026-09-18T12:25:31+00:00",
            "tier": TIER_FINDINGS,
        },
        {
            "chunk_id": "c-noise",
            "document_id": "doc-noise",
            "ordinal": 0,
            "content": "unrelated podcast transcript",
            "distance": 0.45,
            "created_at": "2026-01-01T00:00:00+00:00",
            "tier": TIER_KNOWLEDGE,
        },
    ]
    lexical = [
        {
            "chunk_id": "finding:fid-1",
            "document_id": "F-1",
            "content": "Setup X performed poorly when regime Y was present.",
            "rank": 1.0,
            "finding_id": "fid-1",
            "created_at": "2026-09-18T12:25:31+00:00",
            "tier": TIER_FINDINGS,
        }
    ]
    fused = fuse_dense_lexical(dense, lexical, rrf_k=60)
    order_before = [h.chunk_id for h in fused]
    assert order_before[0] == "finding:fid-1"
    ranked = heuristic_rerank(fused, "How did setup X perform when regime Y was present?")
    assert [h.chunk_id for h in ranked] == order_before
    top = ranked[0]
    assert top.finding_id == "fid-1"
    assert top.tier == TIER_FINDINGS
    assert top.timestamp and top.timestamp.startswith("2026-09-18")
    _, citations = build_context(ranked)
    assert citations[0]["finding_id"] == "fid-1"
    assert citations[0]["source"] == TIER_FINDINGS
    assert citations[0]["document_id"] == "F-1"
    assert citations[0]["timestamp"].startswith("2026-09-18")


def test_retrieve_finding_exposes_provenance_on_ranked_hit():
    svc, _docs, _chunks, _embs = _service()
    _wire_finding(svc, statement="Setup X performed poorly when regime Y was present.")
    ranked = svc.retrieve(
        "How did setup X perform when regime Y was present?",
        k=3,
        role="research",
        mode="hybrid",
        tiers=["findings"],
    )
    assert ranked.retrieved_at
    assert ranked.hits
    hit = ranked.hits[0]
    assert hit.tier == TIER_FINDINGS
    assert hit.finding_id == "f-cat"
    assert hit.document_id == "F-000001"
    assert hit.timestamp and "2026-09-18" in hit.timestamp
    cite = ranked.citations[0]
    assert cite["finding_id"] == "f-cat"
    assert cite["source"] == TIER_FINDINGS
    assert cite["document_id"] == "F-000001"
    SearchResultOut.model_validate(
        {
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "ordinal": hit.ordinal,
            "content": hit.content,
            "similarity": hit.similarity,
            "score": hit.score,
            "finding_id": hit.finding_id,
            "source": hit.tier,
            "timestamp": hit.timestamp,
            "tier": hit.tier,
        }
    )


def test_rag_agent_citations_carry_finding_provenance():
    svc, _docs, _chunks, _embs = _service()
    _wire_finding(svc, statement="Setup X performed poorly when regime Y was present.")
    agent = RagAgent(svc, _EchoLLM(), None, similarity_floor=0.0)
    result = agent.run(
        "How did setup X perform when regime Y was present?",
        role="research",
        k=3,
        mode="hybrid",
    )
    assert result.citations
    top = result.citations[0]
    assert top.finding_id == "f-cat"
    assert top.document_id == "F-000001"
    assert top.source == TIER_FINDINGS
    assert top.timestamp and "2026-09-18" in top.timestamp
    assert top.score is not None
    assert result.usage.get("retrieved_at")
    dumped = top.as_dict()
    CitationOut.model_validate(dumped)
