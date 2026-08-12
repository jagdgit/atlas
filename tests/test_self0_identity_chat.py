"""OI-SELF-ID Phase 4 — Living RAG + identity-first chat."""

from __future__ import annotations

from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    answer_as_atlas,
    answer_belief_benchmark,
    build_living_rag_bundle,
    detect_belief_benchmark,
    format_bundle_context,
)


def test_normalize_belief_citations_for_chat_response():
    from atlas.api.schemas import ChatResponse, CitationOut
    from atlas.services.assistant_service import _normalize_chat_citations

    raw = [
        {
            "type": "belief",
            "belief_id": "bd2d4c2e-2b69-4852-aa3e-6bc4044ee5b2",
            "statement": "Capital preservation comes before growth.",
        }
    ]
    norm = _normalize_chat_citations(raw)
    cite = CitationOut.model_validate(norm[0])
    assert cite.document_id.startswith("belief:")
    assert "Capital preservation" in cite.snippet
    # Full ChatResponse must accept the normalized cite
    ChatResponse(
        session_id="s1",
        answer="ok",
        intent="belief_benchmark",
        citations=norm,
    )


def test_living_rag_bundle_includes_identity_beliefs_goals():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    bundle = build_living_rag_bundle(rs, "capital preservation and determinism")
    assert bundle["identity"] is not None
    assert bundle["counts"]["beliefs"] >= 1
    assert any(c["type"] == "belief" for c in bundle["citations"])
    ctx = format_bundle_context(bundle)
    assert "Atlas Identity" in ctx
    assert "Active Beliefs" in ctx


def test_why_benchmark_market_and_engineering():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    assert detect_belief_benchmark("Why do you believe capital preservation?") == "why"
    market = answer_belief_benchmark(
        rs, "Why do you believe capital preservation comes before growth?"
    )
    assert market and market["ok"]
    assert market["citations"]
    assert "belief_id" in market["citations"][0]

    eng = answer_belief_benchmark(
        rs, "Why do you believe determinism is valuable?"
    )
    assert eng and eng["ok"]
    assert eng["citations"][0]["belief_id"]


def test_mind_change_benchmark_route():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    b = rs.consult(query="hidden state", limit=1)["beliefs"][0]
    revised = rs.revise(
        b["id"],
        reason="lab evidence",
        new_confidence=0.5,
        new_status="weakened",
        evidence_summary="tests",
    )
    assert revised["revision"]["action"] == "weaken"
    assert detect_belief_benchmark("What changed your mind about hidden state?") == (
        "mind_change"
    )
    # Use belief id so we hit the revised row (not a sibling search hit).
    out = answer_belief_benchmark(rs, f"What changed your mind? {b['id']}")
    assert out and out["ok"]
    assert "weaken" in out["answer"].lower() or "revision" in out["answer"].lower()


def test_answer_as_atlas_benchmark_without_llm():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()

    def _boom(*_a, **_k):
        raise AssertionError("LLM should not be called for why-benchmark")

    out = answer_as_atlas(
        rs,
        "Why do you believe evidence before conviction?",
        compose_fn=_boom,
    )
    assert out["mode"] == "benchmark"
    assert out["ok"]
    assert out["citations"]


def test_why_capital_preservation_short_phrase():
    """Exact operator phrase from chat — must not need Ollama."""
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    out = answer_as_atlas(
        rs,
        "Why do you believe capital preservation",
        compose_fn=None,
        allow_llm=False,
    )
    assert out["mode"] == "benchmark"
    assert out.get("answer")
    assert out.get("citations")
    assert "Capital preservation comes before growth" in (out.get("answer") or "")


def test_living_rag_degrades_when_compose_times_out():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()

    def _timeout(*_a, **_k):
        return (
            "Chat LLM timed out (Ollama busy or slow — market workers + "
            "inference share this host)."
        )

    out = answer_as_atlas(
        rs,
        "How should I think about risk in the lab?",
        compose_fn=_timeout,
    )
    assert out["mode"] == "living_rag"
    assert "belief:" in out["answer"].lower() or "Belief Core" in out["answer"]
    assert "Chat LLM timed out" not in out["answer"]


def test_answer_as_atlas_living_rag_uses_compose():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    seen = {}

    def _compose(system, user, **kwargs):
        seen["system"] = system
        seen["user"] = user
        return "Atlas prioritizes capital preservation (belief:demo)."

    out = answer_as_atlas(
        rs,
        "How should I think about risk in the lab?",
        compose_fn=_compose,
    )
    assert out["mode"] == "living_rag"
    assert "Atlas" in seen["system"] or "durable identity" in seen["system"]
    assert "Living RAG context" in seen["user"]
    assert out["citations"]
    assert out["identity_version"] is not None
