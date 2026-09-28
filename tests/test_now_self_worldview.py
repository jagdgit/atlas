"""NOW #9 — SELF worldview into Next-₹1 (advice-only)."""

from __future__ import annotations

from atlas.investment.capital_allocation import build_challenger_table
from atlas.investment.next_rupee import (
    build_and_persist_next_rupee,
    build_next_rupee_center,
    format_next_rupee_evening_lines,
)
from atlas.investment.self_worldview import (
    apply_worldview_to_evidence_packet,
    apply_worldview_to_next_rupee,
    attach_self_worldview,
)
from atlas.reasoning.cognitive_core import build_evidence_packet


def test_attach_empty_unknowns():
    wv = attach_self_worldview(symbols=["CIPLA.NS"])
    assert wv["kind"] == "SELF_WORLDVIEW"
    assert wv["advice_only"] is True
    assert wv["no_capital_influence"] is True
    assert "beliefs" in wv["unknowns"]
    assert "experience_lessons" in wv["unknowns"]


def test_attach_with_seeded_beliefs_and_lessons():
    wv = attach_self_worldview(
        symbols=["DEVYANI.NS"],
        beliefs=[
            {
                "id": "b1",
                "statement": "Never ADD under AVOID / QUARANTINED identity",
                "status": "active",
                "confidence": 0.9,
                "domain": "market",
            }
        ],
        experiences=[
            {"id": "e1", "lesson": "CIPLA ADD without Next-₹1 comparison was capital trap"}
        ],
    )
    assert len(wv["belief_claims"]) == 1
    assert "AVOID" in wv["belief_claims"][0]["claim"]
    assert wv["belief_claims"][0]["claim"] == wv["belief_claims"][0]["statement"]
    assert len(wv["experience_lessons"]) == 1
    assert not wv["unknowns"]


def test_apply_does_not_change_destination():
    tbl = build_challenger_table(
        holds=[],
        challengers=[
            {
                "symbol": "INFY.NS",
                "score": 0.8,
                "confidence": "high",
                "phase": "active",
                "components": {"momentum": 0.8},
            }
        ],
        cash=10_000,
        laboratory_id="lab",
    )
    base = build_next_rupee_center(tbl, laboratory_id="lab")
    dest = base["destination"]
    wv = attach_self_worldview(
        beliefs=[{"statement": "Prefer cash when E[R] incomplete", "status": "active"}],
        experiences=[{"lesson": "Thin completeness → HOLD not ADD"}],
    )
    doc = apply_worldview_to_next_rupee(base, wv)
    assert doc["destination"] == dest
    assert doc["worldview"]["belief_n"] == 1
    assert "Belief context" in doc["operator_answer"]
    assert doc.get("never_orders") is True


def test_persist_with_worldview(tmp_path):
    tbl = build_challenger_table(holds=[], challengers=[], cash=5_000, laboratory_id="lab")
    wv = attach_self_worldview(
        beliefs=[{"statement": "Cash is a position", "status": "active"}],
        experiences=[{"lesson": "Empty deploy pool → stay cash"}],
    )
    doc = build_and_persist_next_rupee(
        tmp_path, tbl, laboratory_id="lab", worldview=wv
    )
    assert doc["worldview"]["belief_n"] == 1
    lines = format_next_rupee_evening_lines(doc)
    assert any("worldview" in ln for ln in lines)
    assert any("Cash is a position" in ln for ln in lines)


def test_evidence_packet_gets_prior_from_statement():
    wv = attach_self_worldview(
        beliefs=[{"id": "b", "statement": "Thesis AVOID blocks ADD", "confidence": 0.8}],
        experiences=[{"lesson": "Exit densify before ADD"}],
    )
    pkt = build_evidence_packet(question="Next rupee?", symbol="CIPLA.NS")
    pkt2 = apply_worldview_to_evidence_packet(pkt, wv)
    assert pkt2["prior_belief"]
    assert "AVOID" in pkt2["prior_belief"][0]["claim"]
    assert any("belief:" in e for e in pkt2["evidence"])
    assert any("experience:" in e for e in pkt2["evidence"])


def test_lessons_from_learning_disk(tmp_path):
    from atlas.investment.learning_objects import record_learning_event
    from atlas.investment.learning_story import STORY_KIND
    from atlas.investment.self_worldview import lessons_from_learning_disk

    story = {
        "kind": STORY_KIND,
        "story_id": "s1",
        "symbol": "CIPLA.NS",
        "laboratory_id": "india_equity_learner",
        "as_of_ist": "2026-08-21",
        "belief_update": "unchanged",
        "belief_note": "Technical experiment only — no thesis update from P&L.",
        "cause": {"status": "unknown_explicit", "narrative": "Cause unknown_explicit"},
        "lessons": ["Do not ADD under AVOID without Next-₹1 packet"],
    }
    record_learning_event(tmp_path, story)
    rows = lessons_from_learning_disk(
        tmp_path,
        "india_equity_learner",
        symbols=["CIPLA.NS"],
        limit=3,
        lookback_days=3,
    )
    assert rows
    assert any("AVOID" in (r.get("lesson") or "") for r in rows)

    wv = attach_self_worldview(
        data_dir=tmp_path,
        laboratory_id="india_equity_learner",
        symbols=["CIPLA.NS"],
        beliefs=[{"statement": "Cash is a position", "status": "active"}],
    )
    assert wv["experience_lessons"]
    assert "experience_lessons" not in wv["unknowns"]
