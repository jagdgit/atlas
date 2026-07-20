"""Hermetic tests for ResearchDecisionRule (Phase D · §D.7).

Deterministic ranking of further-reading candidates: higher evidence level + gap-fit
outranks weaker sources; hold is always offered and stays policy-neutral (no venue tags)
so ``prefer ieee`` can arbitrate; empty candidates → hold-only.
"""

from __future__ import annotations

from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import DecisionRequest
from atlas.decision.rules import apply_policy_influence
from atlas.research.decision_rule import ResearchDecisionRule

RULE = ResearchDecisionRule()
CTX = IntelligenceContext()


def _req(**context) -> DecisionRequest:
    return DecisionRequest(mission_id="m1", mission_type="research", context=context)


def _keys(options):
    return {o.key.split(":")[0] for o in options}


def test_ranks_peer_reviewed_above_web():
    opts = RULE.score(
        _req(
            objective="soiling loss",
            candidates=[
                {"id": "w1", "title": "Blog post", "url": "https://example.com/blog",
                 "evidence_level": 1, "kind": "web", "why": "Additional independent source."},
                {"id": "p1", "title": "IEEE Measurement Study", "url": "https://ieeexplore.ieee.org/x",
                 "evidence_level": 3, "kind": "scholar",
                 "why": "Could fill the peer-reviewed gap."},
            ],
        ),
        CTX,
    )
    assert "read" in _keys(opts) and "hold" in _keys(opts)
    reads = [o for o in opts if o.key.startswith("read")]
    reads.sort(key=lambda o: o.score, reverse=True)
    assert reads[0].key == "read:p1"
    assert reads[0].payload["kind"] == "read_next"
    assert reads[0].side_effecting is False


def test_empty_candidates_holds():
    opts = RULE.score(_req(objective="soiling", candidates=[]), CTX)
    assert _keys(opts) == {"hold"}


def test_no_objective_no_candidates_returns_empty():
    assert RULE.score(_req(), CTX) == []


def test_policy_prefer_lifts_matching_venue():
    opts = RULE.score(
        _req(
            objective="soiling",
            candidates=[
                {"id": "a", "title": "Generic Paper", "url": "https://example.com/a",
                 "evidence_level": 2, "kind": "scholar", "why": "more sources"},
                {"id": "b", "title": "IEEE Transactions on Energy", "url": "https://ieeexplore.ieee.org/b",
                 "evidence_level": 2, "kind": "scholar", "why": "more sources"},
            ],
        ),
        CTX,
    )
    # Equal base scores (same level, no gap bonus) — policy prefer ieee should lift the IEEE one.
    apply_policy_influence(opts, [{"id": "pol-1", "terms": ["ieee", "ieeexplore"], "weight": 2.0}])
    ranked = sorted([o for o in opts if o.key.startswith("read")], key=lambda o: o.final_score, reverse=True)
    assert ranked[0].key == "read:b"
    assert "pol-1" in ranked[0].policy_ids


def test_hold_has_no_venue_tags():
    opts = RULE.score(
        _req(
            objective="x",
            candidates=[{"id": "1", "title": "IEEE Paper", "url": "u", "evidence_level": 3,
                         "kind": "scholar", "why": "peer"}],
        ),
        CTX,
    )
    hold = next(o for o in opts if o.key == "hold")
    assert hold.tags == ("hold",)
