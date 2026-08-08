"""LQ.2 — mandatory denser timeline + Host Guard thinning (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import (
    DecisionTimelineStore,
    checkpoints_for_personality,
    due_ist_for,
    format_evolution_section,
)
from atlas.investment.observation_cadence import evolution_cadence_budget
from atlas.investment.reports import format_learned_today_section
from atlas.workers.base import TickContext
from atlas.workers.decision_evolution import DecisionEvolutionWorker


class _DeferGuard:
    def can_run_tick(self, *, worker_type: str = ""):
        return False, "defer_pressure"


class _CriticalGuard:
    def can_run_tick(self, *, worker_type: str = ""):
        return False, "critical_memory"


def test_lq2_checkpoint_offsets_and_personality():
    assert due_ist_for("2026-08-05", "day3") == "2026-08-08"
    assert due_ist_for("2026-08-05", "day14") == "2026-08-19"
    swing = checkpoints_for_personality("swing")
    assert swing == ["day1", "day3", "week1", "day14", "month1", "quarter"]
    assert checkpoints_for_personality("intraday") == ["day1", "day3"]


def test_lq2_schedules_six_and_ensure_backfills(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    # Record without auto-schedule, then schedule legacy 4-cp set
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=None)
    out = packets.record(
        action="buy",
        symbol="MTARTECH.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-01",
        prices={"mark": 100.0, "fill_price": 100.0, "filled_qty": 1},
        reasons_for=["signal"],
    )
    packet = dict(out["packet"])
    timeline._packets = packets
    n4 = timeline.schedule_evolution(
        packet,
        checkpoints=["day1", "week1", "month1", "quarter"],
    )
    assert n4 == 4

    # Full swing start still densifies to 6
    full = DecisionTimelineStore(data_dir=tmp_path / "full")
    pkts2 = DecisionPacketStore(data_dir=tmp_path / "full", timeline=full)
    full._packets = pkts2
    out2 = pkts2.record(
        action="buy",
        symbol="APOLLOHOSP.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="x",
        ts_ist="2026-08-01",
        prices={"mark": 1.0, "fill_price": 1.0, "filled_qty": 1},
        reasons_for=["x"],
    )
    assert out2["timeline"]["scheduled"] == 6

    ensured = timeline.ensure_open_book_schedules(
        portfolio_key="india_equity_learner",
        open_symbols=["MTARTECH.NS"],
        personality_kind="swing",
    )
    assert ensured["books_ensured"] == 1
    assert ensured["scheduled_new"] >= 2  # day3 + day14 restored

    cov = timeline.open_book_timeline_coverage(
        portfolio_key="india_equity_learner",
        open_symbols=["MTARTECH.NS"],
        personality_kind="swing",
    )
    assert cov["open_books"] == 1
    assert cov["open_books_with_full_schedule"] == 1
    assert cov["books"][0]["status"] == "full"


def test_lq2_evolution_host_guard_thins(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="APOLLOHOSP.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="test",
        ts_ist="2026-07-01",
        prices={"mark": 50.0, "fill_price": 50.0, "filled_qty": 1},
        reasons_for=["x"],
    )

    budget = evolution_cadence_budget(_CriticalGuard(), requested=20, reduced=5)
    assert budget["budget"] == 0

    worker = DecisionEvolutionWorker(
        timeline=timeline,
        decision_packets=packets,
        host_guard=_DeferGuard(),
    )
    # Defer → reduced budget (not zero) — still may complete some
    result = worker.do_tick(
        TickContext(
            worker_id="evo-1",
            mission_id="m",
            config={
                "portfolio_key": "india_equity_learner",
                "max_revisits": 20,
                "open_symbols": ["APOLLOHOSP.NS"],
            },
            config_version=1,
            state={},
        )
    )
    assert "evolution" in result.note
    assert result.state.get("evolution_cadence", {}).get("budget") == 5

    worker_crit = DecisionEvolutionWorker(
        timeline=timeline,
        decision_packets=packets,
        host_guard=_CriticalGuard(),
    )
    result2 = worker_crit.do_tick(
        TickContext(
            worker_id="evo-2",
            mission_id="m",
            config={
                "portfolio_key": "india_equity_learner",
                "open_symbols": ["APOLLOHOSP.NS"],
            },
            config_version=1,
            state={},
        )
    )
    assert "thinned to 0" in result2.note
    assert result2.state["last_evolution"]["completed"] == 0
    # Pending must remain (not invented done)
    counts = timeline.learning_counts(portfolio_key="india_equity_learner")
    assert counts["pending_revisits"] >= 1


def test_lq2_evening_surfaces_coverage():
    lines = format_learned_today_section(
        portfolio={
            "evolution": {
                "pending_revisits": 4,
                "done_revisits": 1,
                "open_books": 2,
                "open_books_with_full_schedule": 1,
                "overdue_revisits": 3,
                "host_guard_reason": "host_guard:critical_memory",
                "host_guard_budget": 0,
            },
            "decisions": [],
            "recent_trades": [],
            "process_proxies": {},
            "intelligence": {},
            "fundamentals_coverage": {},
            "learner_gaps": {},
            "observations": [],
        }
    )
    text = "\n".join(lines)
    assert "Open books full schedule: 1/2" in text
    assert "overdue=3" in text
    assert "Host Guard thinned" in text

    evo_lines = format_evolution_section(
        {
            "pending_revisits": 4,
            "done_revisits": 1,
            "open_books": 2,
            "open_books_with_full_schedule": 1,
            "overdue_revisits": 3,
            "host_guard_reason": "host_guard:defer",
            "host_guard_budget": 5,
        }
    )
    assert any("Open books with full schedule" in ln for ln in evo_lines)
