"""OI-SELF0 Phase 1 — Belief Core + ReasoningService (hermetic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    SEED_BELIEFS,
    effective_confidence,
    seed_worldview,
)


@pytest.fixture()
def rs() -> ReasoningService:
    repo = InMemoryBeliefRepository()
    svc = ReasoningService(repo, llm=None, goals=None)
    svc.ensure_seeded()
    return svc


def test_seed_is_idempotent_and_sized():
    repo = InMemoryBeliefRepository()
    first = seed_worldview(repo)
    second = seed_worldview(repo)
    assert first["identity_created"] is True
    assert second["identity_created"] is False
    assert first["beliefs_created"] == len(SEED_BELIEFS)
    assert second["beliefs_created"] == 0
    assert second["beliefs_skipped"] == len(SEED_BELIEFS)
    assert 20 <= len(SEED_BELIEFS) <= 30
    assert repo.latest_identity() is not None


def test_why_benchmark(rs: ReasoningService):
    out = rs.why("capital preservation")
    assert out["ok"] is True
    assert out["belief"]["statement"]
    assert "stored" in out["confidence"]
    assert "effective" in out["confidence"]
    assert "Evidence" in out["answer"] or "evidence" in out["answer"].lower()
    assert out["status"] == "active"
    metrics = rs.consultation_metrics()
    assert metrics["total"] >= 1


def test_what_changed_your_mind(rs: ReasoningService):
    found = rs.consult(query="hidden state", limit=1)
    belief = found["beliefs"][0]
    revised = rs.revise(
        belief["id"],
        reason="18 engineering incidents showed hidden caches caused flaky tests",
        evidence_summary="lab notes 2026-08",
        new_confidence=0.61,
        new_status="weakened",
        actor="test",
    )
    assert revised["revision"]["action"] == "weaken"
    mind = rs.what_changed_your_mind(belief["id"])
    assert mind["ok"] is True
    assert mind["mind_changes"]
    assert "weakened" in mind["answer"].lower() or "weaken" in mind["answer"].lower()
    assert revised["revision"]["reason"]


def test_candidate_promote_and_advice_only_influence(rs: ReasoningService):
    cand = rs.propose_candidate(
        statement="Switches after macro events may require a cooldown period.",
        domain="market",
        confidence=0.32,
        evidence_summary="3 experiences",
    )
    assert cand["status"] == "candidate"
    promoted = rs.promote(cand["id"], reason="repeated pattern across 3 labs")
    assert promoted["belief"]["status"] == "active"
    with pytest.raises(ValueError, match="advice-only"):
        rs._repo.add_influence(cand["id"], target="ranking", strength="hard")


def test_aging_decays_effective_confidence():
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=400)
    eff = effective_confidence(
        0.81, domain="market", last_evidence_at=old, now=now
    )
    assert eff < 0.81
    assert eff >= 0.05


def test_consultations_metric_by_domain(rs: ReasoningService):
    rs.consult(domain="market", limit=5)
    rs.consult(domain="engineering", limit=5)
    m = rs.consultation_metrics()
    assert m["by_domain"]["market"] >= 1
    assert m["by_domain"]["engineering"] >= 1
    assert m["total"] >= 2


def test_wso_projection_advice_only(rs: ReasoningService):
    proj = rs.project_for_symbol("TCS", laboratory_id="india_equity_learner")
    assert proj["influence_strength"] == "advice"
    assert proj["symbol"] == "TCS"
    assert "market_active" in proj


def test_never_learn_twice_seed_present(rs: ReasoningService):
    out = rs.why("never learn the same lesson twice")
    assert out["ok"] is True
    assert out["belief"]["belief_key"] == "seed.cross.never_learn_twice"
