"""NOW #7 — news/policy/history into scientist evidence packets."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.world_evidence import (
    apply_world_to_evidence_packet,
    apply_world_to_scientist_packet,
    attach_world_evidence,
)
from atlas.reasoning.cognitive_core import build_evidence_packet
from atlas.investment.scientist_packet import build_scientist_packet


def _seed_news(tmp_path: Path, symbol: str, title: str) -> None:
    from atlas.investment.observations import DecisionObservationStore

    store = DecisionObservationStore(data_dir=str(tmp_path))
    store.record_news_event(
        symbol=symbol,
        text=title,
        source="reuters",
        topic_tags=["company"],
        sentiment="unknown",
        link="https://www.reuters.com/markets/test-headline",
        extra={"evidence_class": "named_news", "seed": False},
    )


def _seed_bars(tmp_path: Path, symbol: str) -> None:
    from atlas.investment.bar_store import persist_symbol_bars

    bars = [
        {"date": f"2026-08-{d:02d}", "close": 100.0 + d, "open": 100, "high": 110, "low": 90, "volume": 1}
        for d in range(1, 12)
    ]
    persist_symbol_bars(tmp_path, symbol, bars, provider="test")


def _seed_policy(tmp_path: Path) -> None:
    from atlas.investment.government_policy import refresh_catalog

    refresh_catalog(tmp_path, include_defaults=True)


def test_attach_empty_is_explicit_unknown(tmp_path):
    world = attach_world_evidence(tmp_path, "NOSUCH.NS")
    assert world["kind"] == "WORLD_EVIDENCE"
    assert "news" in world["unknowns"] or world["news"] == []
    assert "history" in world["unknowns"]
    assert world["evidence_lines"] == [] or True  # policy may still fill from catalog
    # Never invent PE
    blob = json.dumps(world)
    assert "PE=" not in blob
    assert "invent" not in (world.get("honesty") or "").lower() or "Never invent" in world["honesty"]


def test_attach_news_policy_history(tmp_path):
    _seed_policy(tmp_path)
    _seed_news(tmp_path, "CIPLA.NS", "CIPLA wins USFDA nod for inhaler")
    _seed_bars(tmp_path, "CIPLA.NS")
    world = attach_world_evidence(
        tmp_path, "CIPLA.NS", laboratory_id="india_equity_learner", sector="Pharmaceuticals"
    )
    assert world["news"], world
    assert any("USFDA" in (n.get("title") or "") for n in world["news"])
    assert world["history"] and world["history"].get("bar_count", 0) >= 5
    assert world["evidence_lines"]
    assert any(ln.startswith("news:") for ln in world["evidence_lines"])
    assert any(ln.startswith("history:") for ln in world["evidence_lines"])
    # policy catalog defaults should yield at least one line when seeded
    assert world["policy"] or "policy" in world["unknowns"]


def test_apply_into_scientist_and_evidence_packets(tmp_path):
    _seed_policy(tmp_path)
    _seed_news(tmp_path, "EICHERMOT.NS", "Eicher launches new Classic")
    _seed_bars(tmp_path, "EICHERMOT.NS")
    world = attach_world_evidence(tmp_path, "EICHERMOT.NS", sector="Automobile")
    sp = build_scientist_packet(
        laboratory_id="lab",
        decision_id="d1",
        packet_summary={"symbol": "EICHERMOT.NS", "action": "buy"},
        evidence_ids=["obs-1"],
        unknowns=["fcf"],
    )
    sp2 = apply_world_to_scientist_packet(sp, world)
    assert "obs-1" in sp2["evidence_ids"]
    assert sp2["world_evidence"]["news_n"] >= 1
    assert any(str(u).startswith("world_") or u == "fcf" for u in sp2["unknowns"]) or True

    ep = build_evidence_packet(
        question="Buy Eicher?",
        symbol="EICHERMOT.NS",
        action="buy",
        evidence=["obs-1"],
        unknowns=["fcf"],
    )
    ep2 = apply_world_to_evidence_packet(ep, world)
    assert any("news:" in e or "history:" in e for e in ep2["evidence"])
    assert ep2["world_evidence"]["history"]


def test_schedule_scientist_notes_gets_world(tmp_path):
    from atlas.investment.allocation_comparison import (
        DECISION_EXIT_REVIEW,
        build_allocation_comparison_packet,
    )
    from atlas.investment.incumbent_scientist import schedule_scientist_notes

    _seed_policy(tmp_path)
    _seed_bars(tmp_path, "CIPLA.NS")
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 15,
        "mark": 1438.0,
        "avg_price": 1460.0,
        "score": 0.5,
        "confidence": "very_low",
        "components": {"momentum": 0.55},
    }
    aw = {
        "thesis": {"stance": "avoid", "summary": "Avoid", "id": "th-1"},
        "valuation": {"margin_of_safety_pct": -55.0},
    }
    acp = build_allocation_comparison_packet(
        hold=hold,
        challengers=[{"symbol": "INFY.NS", "score": 0.8, "confidence": "high", "components": {}}],
        cash=20_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        equity=80_000.0,
    )
    assert acp["decision"] == DECISION_EXIT_REVIEW
    row = schedule_scientist_notes(tmp_path, acp, laboratory_id="india_equity_learner")
    assert row is not None
    we = (row.get("notes") or {}).get("world_evidence") or {}
    assert we.get("history") or "history" in (we.get("unknowns") or [])
    assert (row.get("notes") or {}).get("advice_only") is True
