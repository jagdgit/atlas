"""PLC.E remainder — revisit honesty + deepened what_changed."""

from __future__ import annotations

from atlas.investment.decision_timeline import (
    DecisionTimelineStore,
    format_evolution_section,
    what_changed,
)
from atlas.investment.reports import format_learned_today_section


def test_learning_counts_split_due_vs_future(tmp_path):
    store = DecisionTimelineStore(data_dir=tmp_path)
    store._mem_revisits = [  # noqa: SLF001
        {
            "id": "r1",
            "decision_id": "d1",
            "checkpoint": "day1",
            "due_ist": "2026-08-01",
            "status": "pending",
            "portfolio_key": "india_equity_learner",
        },
        {
            "id": "r2",
            "decision_id": "d1",
            "checkpoint": "month1",
            "due_ist": "2026-09-01",
            "status": "pending",
            "portfolio_key": "india_equity_learner",
        },
        {
            "id": "r3",
            "decision_id": "d2",
            "checkpoint": "day1",
            "due_ist": "2026-07-01",
            "status": "done",
            "portfolio_key": "india_equity_learner",
        },
    ]
    # Force as_of via monkeypatch of ist_today inside counts — set due relative
    # to real today by using far past / far future already.
    counts = store.learning_counts(portfolio_key="india_equity_learner")
    assert counts["pending_revisits"] == 2
    assert counts["done_revisits"] == 1
    assert counts["revisits_due_today"] >= 1  # day1 2026-08-01 is past
    assert counts["pending_future"] >= 1
    text = "\n".join(format_evolution_section(counts))
    assert "Due today" in text
    assert "Pending future" in text


def test_evening_does_not_call_mission_dead_when_only_future():
    lines = format_learned_today_section(
        plan={"phase": "learning"},
        portfolio={
            "evolution": {
                "pending_revisits": 16,
                "done_revisits": 0,
                "revisits_due_today": 0,
                "pending_future": 16,
            },
            "kpis": {"phase": "learning"},
            "fundamentals_coverage": {"symbols": 1, "with_pe": 1},
            "decisions": [
                {
                    "action": "buy",
                    "symbol": "X",
                    "unknowns": [],
                    "meta": {},
                }
            ],
            "recent_trades": [
                {"side": "sell", "symbol": "X", "ist_day_match": True}
            ],
        },
    )
    text = "\n".join(lines)
    assert "not dead" in text.lower() or "not yet due" in text.lower()
    assert "Start/confirm Decision Evolution mission" not in text
    assert "due today / future / done" in text.lower() or "Revisits due today" in text


def test_what_changed_open_book_and_early_pain():
    packet = {
        "action": "buy",
        "prices": {"mark": 100.0},
        "confidence_breakdown": {"overall": 0.6},
        "observation_ids": [],
        "unknowns": ["pe_missing"],
    }
    diff = what_changed(
        packet,
        current_mark=90.0,
        current_score={"overall": 0.5},
        current_unknowns=["pe_missing"],
        recent_observations=[
            {
                "id": "obs-1",
                "kind": "market_event",
                "payload": {
                    "kind": "open_book_daily_pack",
                    "thesis": {"status": "weakening"},
                },
            },
            {"id": "obs-2", "kind": "policy_event", "payload": {"title": "RBI"}},
        ],
        checkpoint="day3",
    )
    assert diff["price_change_pct"] == -10.0
    assert diff["early_vs_wrong"] == "early_pain"
    assert "obs-1" in (diff.get("open_book_pack_ids") or [])
    assert diff.get("policy_event_count") == 1
    assert diff.get("thesis_status") == "weakening"
