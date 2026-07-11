"""Verification Engine + Evidence Graph tests (Sprint 15, D8/§5a).

Pure, deterministic — no LLM/network. Covers convergence, calculated confidence,
the Evidence Budget decision, graph serialisation, and the service wrapper.
"""

from __future__ import annotations

from atlas.evidence.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Claim,
    ClaimValue,
    EvidenceGraph,
    EvidenceItem,
    Source,
    STANCE_CONTRADICT,
)
from atlas.verification.engine import EvidenceBudget, VerificationEngine
from atlas.verification.service import VerificationService


def _claim(values, level=4, contradict=None, cid="c1"):
    ev = [
        EvidenceItem(source_id=f"s{i}", evidence_level=level, extracted_value=v)
        for i, v in enumerate(values)
    ]
    for i, v in enumerate(contradict or []):
        ev.append(
            EvidenceItem(
                source_id=f"x{i}", evidence_level=level,
                extracted_value=v, stance=STANCE_CONTRADICT,
            )
        )
    return Claim(id=cid, statement="test", evidence=ev)


# --- convergence (§5a.3) --------------------------------------------------
def test_convergence_tight_cluster_is_high():
    eng = VerificationEngine()
    assert eng.convergence([3.7, 3.9, 4.0, 3.8]) == 1.0


def test_convergence_scattered_is_low():
    eng = VerificationEngine()
    assert eng.convergence([2, 11, 6, 4]) < 0.5


def test_convergence_single_value_cannot_converge():
    assert VerificationEngine().convergence([4.0]) == 0.0


def test_convergence_handles_negative_and_zero_magnitudes():
    eng = VerificationEngine()
    # identical values converge regardless of sign/scale
    assert eng.convergence([-5.0, -5.0, -5.0]) == 1.0


# --- calculated confidence (§5a.3) ---------------------------------------
def test_high_confidence_converging_l3plus():
    eng = VerificationEngine()
    claim = eng.verify_claim(_claim([3.7, 3.9, 4.0], level=4))
    assert claim.confidence == CONFIDENCE_HIGH
    assert claim.convergence == 1.0
    assert claim.last_verified
    assert claim.reasoning_trace


def test_low_confidence_when_diverging():
    eng = VerificationEngine()
    claim = eng.verify_claim(_claim([2, 11, 6, 4], level=4))
    assert claim.confidence == CONFIDENCE_LOW


def test_contradictions_erode_confidence():
    eng = VerificationEngine()
    # converging support but a contradicting source blocks HIGH
    claim = eng.verify_claim(_claim([3.9, 4.0, 3.8], level=4, contradict=[9.0]))
    assert claim.confidence != CONFIDENCE_HIGH


def test_no_evidence_is_insufficient():
    eng = VerificationEngine()
    claim = eng.verify_claim(Claim(id="c", statement="empty"))
    assert claim.confidence == CONFIDENCE_INSUFFICIENT


def test_single_strong_source_is_not_high():
    eng = VerificationEngine()
    claim = eng.verify_claim(_claim([4.0], level=5))
    assert claim.confidence in {CONFIDENCE_MEDIUM, CONFIDENCE_LOW}
    assert claim.confidence != CONFIDENCE_HIGH


def test_low_level_sources_do_not_reach_high():
    eng = VerificationEngine()
    # L1 forum posts that agree numerically should not be HIGH
    claim = eng.verify_claim(_claim([4.0, 4.0, 3.9], level=1))
    assert claim.confidence != CONFIDENCE_HIGH


# --- Evidence Budget (§5a.4) ---------------------------------------------
def test_budget_continues_when_criteria_unmet():
    eng = VerificationEngine()
    claim = _claim([3.9, 4.0], level=4)
    decision = eng.decide(claim, EvidenceBudget())
    assert decision.decision == "continue"
    assert not decision.should_stop
    assert any("sources" in r for r in decision.reasons)


def test_budget_stops_when_all_met():
    eng = VerificationEngine()
    ev = [
        EvidenceItem(source_id="p1", evidence_level=4, extracted_value=3.9),
        EvidenceItem(source_id="p2", evidence_level=4, extracted_value=4.0),
        EvidenceItem(source_id="p3", evidence_level=4, extracted_value=3.8),
        EvidenceItem(source_id="g1", evidence_level=3, extracted_value=4.1),
        EvidenceItem(source_id="g2", evidence_level=3, extracted_value=3.95),
    ]
    claim = Claim(id="c", statement="s", evidence=ev)
    decision = eng.decide(claim, EvidenceBudget())
    assert decision.should_stop


def test_budget_stops_at_max_iterations():
    eng = VerificationEngine()
    claim = _claim([3.9], level=4)
    decision = eng.decide(claim, EvidenceBudget(max_search_iterations=3), iteration=3)
    assert decision.should_stop
    assert any("max_search_iterations" in r for r in decision.reasons)


# --- graph serialisation (§5a.1) -----------------------------------------
def test_graph_roundtrip():
    graph = EvidenceGraph()
    graph.add_source(Source(id="s1", title="NREL", evidence_level=3, kind="government"))
    graph.add_claim(
        Claim(
            id="c1", statement="x",
            value=ClaimValue(4.0, "%", "annual_mean"),
            evidence=[EvidenceItem(source_id="s1", evidence_level=3, extracted_value=4.0)],
        )
    )
    restored = EvidenceGraph.from_dict(graph.as_dict())
    assert restored.get_claim("c1").value.number == 4.0
    assert restored.sources["s1"].kind == "government"


def test_claim_from_split_source_lists():
    claim = Claim.from_dict(
        {
            "id": "c1",
            "statement": "x",
            "supporting_sources": [{"source_id": "a", "evidence_level": 4}],
            "contradicting_sources": [{"source_id": "b", "evidence_level": 2}],
        }
    )
    assert len(claim.supporting) == 1
    assert len(claim.contradicting) == 1


# --- service wrapper ------------------------------------------------------
def test_service_verifies_and_attaches_decision():
    svc = VerificationService()
    result = svc.verify(
        {
            "claims": [
                {
                    "id": "c1",
                    "statement": "s",
                    "evidence": [
                        {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                        {"source_id": "s2", "evidence_level": 3, "extracted_value": 4.0},
                        {"source_id": "s3", "evidence_level": 4, "extracted_value": 3.8},
                    ],
                }
            ]
        }
    )
    claim = result["claims"][0]
    assert claim["confidence"] == CONFIDENCE_HIGH
    assert "budget_decision" in claim
    assert result["budget"]["min_sources"] == 5


def test_service_budget_override_merges():
    svc = VerificationService()
    result = svc.verify(
        {"claims": [{"id": "c", "statement": "s", "evidence": []}]},
        budget={"min_sources": 1, "unknown_key": 99},
    )
    assert result["budget"]["min_sources"] == 1
    assert "unknown_key" not in result["budget"]


def test_service_health_check_ok():
    status = VerificationService().health_check()
    assert status.healthy
