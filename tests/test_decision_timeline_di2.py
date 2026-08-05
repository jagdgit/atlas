"""DI.2 Market Timeline + DI.4 fundamentals gaps — hermetic."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import (
    DecisionTimelineStore,
    due_ist_for,
    what_changed,
)
from atlas.investment.fundamentals import (
    fundamentals_view,
    import_json_payload,
    learner_fundamentals_gaps,
)
from atlas.investment.reports import format_evening_report


def test_packet_schedules_timeline_and_revisits(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets

    out = packets.record(
        action="buy",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 7900.0, "fill_price": 7900.0, "filled_qty": 2},
        reasons_for=["signal"],
    )
    assert out["timeline"]["events"] == 1
    assert out["timeline"]["scheduled"] == 4  # day1 week1 month1 quarter

    events = timeline.list_symbol(symbol="EICHERMOT.NS")
    assert any(e.get("kind") == "decision" for e in events)

    due_day1 = due_ist_for("2026-08-05", "day1")
    assert due_day1 == "2026-08-06"
    due = timeline.list_due(as_of_ist=due_day1, portfolio_key="india_equity_learner")
    assert len(due) >= 1
    assert due[0]["checkpoint"] == "day1"

    # Force-run revisits as of day1
    result = timeline.run_due_revisits(
        as_of_ist=due_day1,
        portfolio_key="india_equity_learner",
        limit=10,
        mark_fn=lambda _s: 8000.0,
        awareness_fn=lambda _s: {
            "investment_score": {"overall": 0.7},
            "valuation": {"margin_of_safety_pct": 5},
        },
    )
    assert result["completed"] >= 1
    events2 = timeline.list_symbol(symbol="EICHERMOT.NS", kind="revisit")
    assert len(events2) >= 1
    diff = events2[0]["payload"]["what_changed"]
    assert diff["price_change_pct"] is not None
    assert abs(diff["price_change_pct"] - round(100 * (8000 - 7900) / 7900, 3)) < 0.01

    counts = timeline.learning_counts(portfolio_key="india_equity_learner")
    assert counts["done_revisits"] >= 1
    assert counts["pending_revisits"] >= 1  # week1+ still pending


def test_hold_does_not_schedule_full_evolution(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    out = packets.record(
        action="hold",
        symbol="TCS.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="engine_hold",
        ts_ist="2026-08-05",
        reasons_for=["hold"],
    )
    assert out["timeline"]["events"] == 1
    assert out["timeline"]["scheduled"] == 0


def test_what_changed_and_observation_seam(tmp_path: Path):
    diff = what_changed(
        {
            "action": "buy",
            "prices": {"mark": 100},
            "confidence_breakdown": {"overall": 0.5},
            "unknowns": ["pe_missing"],
        },
        current_mark=110,
        current_score={"overall": 0.6},
        current_unknowns=[],
    )
    assert diff["thesis_improved"] is True
    assert "pe_missing" in diff["resolved_unknowns"]

    store = DecisionTimelineStore(data_dir=tmp_path)
    obs = store.append_observation(
        symbol="INFY.NS", kind_detail="news_headline", payload={"title": "earnings"}
    )
    assert obs["kind"] == "observation"
    assert store.list_symbol(symbol="INFY.NS", kind="observation")


def test_fundamentals_gaps_honesty(tmp_path: Path):
    import_json_payload(
        tmp_path,
        [{"symbol": "INFY.NS", "roe": 28}],
        program_id="market_intelligence",
        source="test",
    )
    gaps = learner_fundamentals_gaps(
        tmp_path,
        ["INFY.NS", "TCS.NS"],
        program_id="market_intelligence",
    )
    assert gaps["symbols_checked"] == 2
    assert gaps["symbols_with_gaps"] == 2
    infy = next(g for g in gaps["gaps"] if g["symbol"] == "INFY.NS")
    assert "pe" in infy["missing"]
    view = fundamentals_view(
        tmp_path,
        program_id="market_intelligence",
        gap_symbols=["INFY.NS", "TCS.NS"],
    )
    assert view["coverage"]["with_pe"] == 0
    assert view["learner_gaps"]["symbols_with_gaps"] == 2


def test_evening_includes_evolution_and_fundamentals():
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={
            "cash": 1,
            "decisions": [],
            "evolution": {"pending_revisits": 3, "done_revisits": 1},
            "fundamentals_coverage": {
                "symbols": 2,
                "with_pe": 0,
                "with_fcf": 0,
                "note": "Empty PE/FCF is honest incomplete evidence — not a valuation signal.",
                "learner_gaps": {"symbols_with_gaps": 2, "symbols_checked": 2},
            },
        },
    )
    assert "Decision evolution" in body
    assert "Open revisits pending: 3" in body
    assert "Fundamentals coverage" in body
    assert "never invent" in body.lower() or "Watchlist gaps" in body
