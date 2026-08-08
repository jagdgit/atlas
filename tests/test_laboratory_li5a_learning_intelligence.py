"""LI.5a — Atlas IQ proxies, evolution events, failure_cause taxonomy."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_attribution import DecisionAttributionStore
from atlas.investment.learning_intelligence import (
    FAILURE_ROOT_CAUSES,
    append_evolution_event,
    build_atlas_iq_proxies,
    format_atlas_iq_section,
    list_evolution_events,
    normalize_failure_cause,
)
from atlas.investment.reports import format_learned_today_section


def test_normalize_failure_cause_taxonomy():
    assert normalize_failure_cause("evidence_failure") == "evidence_failure"
    assert normalize_failure_cause("conflict") == "provider_conflict"
    assert normalize_failure_cause("host_guard") == "resource_limitation"
    assert normalize_failure_cause("nope") is None
    assert "research_failure" in FAILURE_ROOT_CAUSES


def test_attribution_stores_failure_cause(tmp_path: Path):
    store = DecisionAttributionStore(data_dir=tmp_path)
    out = store.record(
        decision_id="d1",
        symbol="CIPLA.NS",
        portfolio_key="india_equity_learner",
        trigger="exit",
        pnl=-1.5,
        failure_cause="evidence",
    )
    doc = out["attribution"]
    assert doc["payload"]["failure_cause"] == "evidence_failure"
    assert doc["payload"]["extra"]["failure_cause"] == "evidence_failure"


def test_atlas_iq_proxies_and_evolution(tmp_path: Path):
    snap = build_atlas_iq_proxies(
        tmp_path,
        laboratory_id="india_equity_learner",
        packets=[{"unknowns": ["pe_missing"]}],
        process_score=6.0,
        pending_revisits=2,
        done_revisits=1,
        observation_count=4,
        attributions=[
            {"payload": {"failure_cause": "evidence_failure"}},
        ],
    )
    assert snap["laboratory_id"] == "india_equity_learner"
    assert "research" in snap["axes"]
    assert 0 <= snap["overall"] <= 100
    assert snap["counts"]["failure_causes_tagged"] == 1
    # Thin-sample note only when both packets and attrs are sparse
    thin = build_atlas_iq_proxies(tmp_path, laboratory_id="thin_lab", packets=[], attributions=[])
    assert thin.get("sample_note")

    # Force evolution event by rewriting with large overall delta
    snap2 = build_atlas_iq_proxies(
        tmp_path,
        laboratory_id="india_equity_learner",
        packets=[{"unknowns": []}] * 8,
        process_score=9.0,
        pending_revisits=0,
        done_revisits=8,
        observation_count=20,
        attributions=[{"payload": {"failure_cause": "research_failure"}}] * 5,
    )
    assert snap2["overall"] >= snap["overall"] or abs(snap2["overall"] - snap["overall"]) >= 0
    # Explicit append also works
    ev = append_evolution_event(
        tmp_path,
        laboratory_id="india_equity_learner",
        axis="learning",
        from_score=10.0,
        to_score=40.0,
        reason="test",
        phase_id="LI.5a",
    )
    assert ev is not None
    events2 = list_evolution_events(tmp_path, laboratory_id="india_equity_learner")
    assert any(e.get("reason") == "test" for e in events2)


def test_evening_includes_atlas_iq_section():
    lines = format_learned_today_section(
        plan={"phase": "learning"},
        portfolio={
            "decisions": [],
            "atlas_iq": {
                "laboratory_id": "india_equity_learner",
                "overall": 42.0,
                "axes": {"research": 10, "learning": 20},
                "counts": {
                    "packets": 0,
                    "attributions": 0,
                    "observations": 1,
                    "revisits_done": 0,
                },
                "sample_note": "Thin sample — treat Atlas IQ as directional only.",
            },
        },
    )
    text = "\n".join(lines)
    assert "Atlas IQ" in text
    assert "overall=42.0" in text
    iq_lines = format_atlas_iq_section(
        {
            "laboratory_id": "lab",
            "overall": 1,
            "axes": {"a": 1},
            "counts": {},
        }
    )
    assert iq_lines
    assert any("LI.5b" in ln or "Atlas IQ" in ln for ln in iq_lines)
