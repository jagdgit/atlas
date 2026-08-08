"""LI.3a — observation density, Host Guard cadence, revisit JSON mirror."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.observation_cadence import observation_cadence_budget
from atlas.investment.observations import DecisionObservationStore
from atlas.workers.base import TickContext
from atlas.workers.market_observer import MarketObserverWorker


class _OkGuard:
    def can_run_tick(self, *, worker_type: str | None = None):
        return True, "ok"


class _DeferGuard:
    def can_run_tick(self, *, worker_type: str | None = None):
        return False, "cpu_pressure"


class _CriticalGuard:
    def can_run_tick(self, *, worker_type: str | None = None):
        return False, "critical_memory"


def test_observation_cadence_budget_host_guard():
    assert observation_cadence_budget(None, requested=20)["budget"] == 20
    assert observation_cadence_budget(_OkGuard(), requested=20)["budget"] == 20
    defer = observation_cadence_budget(_DeferGuard(), requested=20, reduced=5)
    assert defer["allowed"] is False
    assert defer["budget"] == 5
    crit = observation_cadence_budget(_CriticalGuard(), requested=20, reduced=5)
    assert crit["budget"] == 0


def test_mark_snapshot_on_quiet_book(tmp_path: Path):
    class _QuietReader:
        def bars_for(self, symbol, **kwargs):
            return {
                "provider": "asset_replay",
                "symbol": symbol,
                "bars": [{"close": 100}, {"close": 100.5}],
                "count": 2,
                "pct_move": 0.5,
            }

    obs = DecisionObservationStore(data_dir=tmp_path)
    worker = MarketObserverWorker(
        market_reader=_QuietReader(),
        observations=obs,
        host_guard=_OkGuard(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "instruments": [{"symbol": "QUIET.NS", "asset": "demo"}],
                "move_alert_pct": 5.0,
                "mark_snapshot_budget": 10,
            },
            config_version=1,
            state={},
        )
    )
    assert result.state["last_mark_snapshots"] == 1
    assert "mark_snapshot" in result.note
    recent = obs.list_since(since_hours=24, limit=10)
    assert any(
        (r.get("payload") or {}).get("kind") == "mark_snapshot"
        or (r.get("payload") or {}).get("reason") == "session_mark_snapshot"
        for r in recent
    )


def test_host_guard_reduces_mark_snapshots(tmp_path: Path):
    class _QuietReader:
        def bars_for(self, symbol, **kwargs):
            return {
                "provider": "asset_replay",
                "symbol": symbol,
                "bars": [{"close": 10}, {"close": 10.1}],
                "count": 2,
                "pct_move": 1.0,
            }

    obs = DecisionObservationStore(data_dir=tmp_path)
    worker = MarketObserverWorker(
        market_reader=_QuietReader(),
        observations=obs,
        host_guard=_DeferGuard(),
    )
    # many symbols but reduced budget = 2
    instruments = [{"symbol": f"S{i}.NS", "asset": "demo"} for i in range(8)]
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "instruments": instruments,
                "move_alert_pct": 50.0,
                "mark_snapshot_budget": 20,
                "mark_snapshot_budget_reduced": 2,
            },
            config_version=1,
            state={},
        )
    )
    assert result.state["last_mark_snapshots"] == 2
    assert result.state["observation_cadence"]["allowed"] is False


def test_complete_revisit_mirrors_done_for_learning_counts(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="REVISIT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 100.0, "fill_price": 100.0, "filled_qty": 1},
        reasons_for=["signal"],
    )
    due = timeline.list_due(as_of_ist="2026-08-06", portfolio_key="india_equity_learner")
    assert due
    timeline.complete_revisit(
        due[0],
        diff={"price_change_pct": 2.0},
        mark=102.0,
    )
    counts = timeline.learning_counts(portfolio_key="india_equity_learner")
    assert counts["done_revisits"] >= 1
