"""OI-SELF-REFLECT Phase 3 — nightly Belief Core reflection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    belief_core_jis,
    format_reflection_section,
    merge_jis,
    run_nightly_reflection,
)


def test_reflection_promotes_evidenced_candidate():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    cand = rs.propose_candidate(
        statement="Explicit interfaces beat hidden caches in flaky systems.",
        domain="engineering",
        confidence=0.55,
        evidence_summary="first note",
    )
    # Need ≥2 evidence for promotion gate
    repo.add_evidence(cand["id"], kind="note", summary="second confirming incident")
    out = run_nightly_reflection(rs, allow_llm_narrative=False)
    assert out["version"].startswith("self0.reflect")
    assert any(p["belief_id"] == cand["id"] for p in out["promoted"])
    got = rs.get_belief(cand["id"])
    assert got["status"] == "active"


def test_reflection_ages_stale_belief():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    old = datetime.now(timezone.utc) - timedelta(days=400)
    row = repo.create_belief(
        statement="Stale market heuristic awaiting revalidation.",
        domain="market",
        status="active",
        origin="operator",
        confidence=0.5,
        last_evidence_at=old,
        belief_key="test.stale.market",
    )
    # Force last_evidence_at old (create sets now by default path — update)
    repo.update_belief(row["id"], last_evidence_at=old, touch_revised=False)
    # Manually patch for aging
    with repo._lock:
        repo._beliefs[row["id"]]["last_evidence_at"] = old
        repo._beliefs[row["id"]]["confidence"] = 0.5
    out = run_nightly_reflection(rs, allow_llm_narrative=False, max_aging=3)
    assert any(a["belief_id"] == row["id"] for a in out["aged"])
    got = rs.get_belief(row["id"])
    assert got["status"] == "weakened"


def test_belief_core_jis_and_merge():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    b = rs.consult(query="hidden state", limit=1)["beliefs"][0]
    rs.revise(
        b["id"],
        reason="test",
        new_confidence=0.7,
        evidence_summary="t",
    )
    core = belief_core_jis(rs, days=7)
    assert core["period"] >= 1
    assert core["consultations_today"]["total"] >= 1
    merged = merge_jis({"today": 1, "period": 2, "by_status": {"weakened": 1}}, core)
    assert merged["period"] >= 3
    assert "belief_core" in merged
    lines = format_reflection_section(
        run_nightly_reflection(rs, allow_llm_narrative=False)
    )
    assert any("Reflection" in ln for ln in lines)


def test_thin_reflection_when_no_work():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    # Fresh seed only — candidates have 1 evidence, won't promote; no stale
    rs.ensure_seeded()
    out = run_nightly_reflection(rs, allow_llm_narrative=False, max_promotions=0, max_aging=0)
    # period may be >0 from seed create revisions — create is not material
    assert out["status"] in {"ok", "thin"}
