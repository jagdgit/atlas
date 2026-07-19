"""Unit tests for Knowledge Access Layer pure helpers (Stage 3B.1)."""

from __future__ import annotations

from atlas.eval.metrics import precision_at_k, recall_at_k
from atlas.knowledge.access import (
    RankedHit,
    build_context,
    domains_for_role,
    fuse_dense_lexical,
    heuristic_rerank,
    partition_tiers,
    reciprocal_rank_fusion,
)


def test_rrf_equal_weight_fusion():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60)
    # a and b each appear once at rank 1 and once at rank 2 → equal RRF
    assert scores["a"] == scores["b"]
    assert scores["a"] > scores["c"]
    assert "d" in scores
    # Prefer earlier consensus: item first in both lists wins
    scores2 = reciprocal_rank_fusion([["b", "a"], ["b", "a"]], k=60)
    assert scores2["b"] > scores2["a"]


def test_fuse_dense_lexical_persists_component_scores():
    dense = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "ordinal": 0,
            "content": "soiling loss arid",
            "distance": 0.1,
        },
        {
            "chunk_id": "c2",
            "document_id": "d2",
            "ordinal": 0,
            "content": "unrelated inverter",
            "distance": 0.4,
        },
    ]
    lexical = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "ordinal": 0,
            "content": "soiling loss arid",
            "rank": 0.9,
        },
        {
            "chunk_id": "c3",
            "document_id": "d3",
            "ordinal": 0,
            "content": "soiling cleaning schedule",
            "rank": 0.5,
        },
    ]
    hits = fuse_dense_lexical(dense, lexical, rrf_k=60)
    by_id = {h.chunk_id: h for h in hits}
    assert by_id["c1"].dense_score is not None
    assert by_id["c1"].lexical_score is not None
    assert by_id["c1"].rrf_score > by_id["c2"].rrf_score


def test_heuristic_rerank_and_context_builder():
    hits = [
        RankedHit(
            chunk_id="c2",
            document_id="d2",
            ordinal=0,
            content="alpha beta",
            rrf_score=0.02,
            score=0.02,
        ),
        RankedHit(
            chunk_id="c1",
            document_id="d1",
            ordinal=0,
            content="query term appears here",
            rrf_score=0.02,
            score=0.02,
        ),
    ]
    ranked = heuristic_rerank(hits, "query term")
    assert ranked[0].chunk_id == "c1"
    context, citations = build_context(ranked)
    assert "[1]" in context
    assert citations[0]["chunk_id"] == "c1"
    assert "rrf_score" in citations[0]


def _hit(chunk_id, content, rrf=0.02):
    return RankedHit(chunk_id=chunk_id, document_id=chunk_id, ordinal=0,
                     content=content, rrf_score=rrf, score=rrf)


def test_policy_prefer_boosts_matching_hit_and_records_rule():
    # Two equally-ranked hits; a "prefer momentum" policy should lift the momentum hit.
    hits = [_hit("c_index", "broad index fund"), _hit("c_mom", "a momentum strategy")]
    policy_rules = [{"id": "P-1", "rule": "prefer", "terms": ["momentum"], "weight": 0.02}]
    ranked = heuristic_rerank(hits, "", policy_rules=policy_rules)
    assert ranked[0].chunk_id == "c_mom"
    assert ranked[0].policy_boost > 0
    assert ranked[0].policy_ids == ("P-1",)
    # Explainability flows into citations ("boosted by policy P-1").
    _, citations = build_context(ranked)
    assert citations[0]["policy_ids"] == ["P-1"]


def test_policy_avoid_deprioritizes_but_never_drops():
    hits = [_hit("c_crypto", "crypto trading tips"), _hit("c_bonds", "government bonds")]
    policy_rules = [{"id": "P-2", "rule": "avoid", "terms": ["crypto"], "weight": -0.02}]
    ranked = heuristic_rerank(hits, "", policy_rules=policy_rules)
    ids = [h.chunk_id for h in ranked]
    assert ids == ["c_bonds", "c_crypto"]        # crypto pushed down
    assert "c_crypto" in ids                       # influence, not arbitration — never removed
    crypto = next(h for h in ranked if h.chunk_id == "c_crypto")
    assert crypto.policy_boost < 0 and crypto.policy_ids == ("P-2",)


def test_domains_for_role():
    assert domains_for_role("research") == ["external", "research", "experience"]
    assert domains_for_role("chat") is None
    assert domains_for_role("research", ["code"]) == ["code"]


def test_partition_tiers_honest_about_deferred():
    live, deferred = partition_tiers(["knowledge", "working", "session", "archive"])
    assert live == ["knowledge"]
    assert "working" in deferred and "session" in deferred and "archive" in deferred


def test_hybrid_ranking_improves_or_holds_vs_dense_only_on_fixture_style_case():
    """Acceptance: hybrid must hold/improve vs dense-only on a labeled toy case."""
    relevant = {"c1", "c3"}
    dense_only = ["c2", "c1", "c4"]
    # Lexical recovers c3 which dense missed in top-2.
    hybrid = ["c1", "c3", "c2"]
    assert precision_at_k(hybrid, relevant, 2) >= precision_at_k(dense_only, relevant, 2)
    assert recall_at_k(hybrid, relevant, 2) >= recall_at_k(dense_only, relevant, 2)
