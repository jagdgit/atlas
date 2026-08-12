"""PLC.B — richer exits + failure_cause mapping (hermetic)."""

from __future__ import annotations

from atlas.investment.plc_exits import (
    evaluate_plc_b_exits,
    failure_cause_for_exit,
    plc_b_enabled,
)


def test_plc_b_enabled_defaults():
    assert plc_b_enabled({}, "india_equity_learner") is True
    assert plc_b_enabled({"plc_b_exits": False}, "india_equity_learner") is False
    assert plc_b_enabled({}, "blotter") is False


def test_stop_loss_and_time_stop_fire():
    stop = evaluate_plc_b_exits(
        symbol="EICHERMOT.NS",
        price=7000.0,
        held=2.0,
        avg_price=7921.0,
        equity=50000.0,
        cfg={"plc_b_stop_loss_pct": 0.08},
    )
    assert stop is not None
    assert stop["exit_code"] == "stop_loss"
    assert failure_cause_for_exit("stop_loss", pnl=-100.0) == "risk_failure"
    assert failure_cause_for_exit("stop_loss", pnl=50.0) is None

    timed = evaluate_plc_b_exits(
        symbol="CIPLA.NS",
        price=1500.0,
        held=1.0,
        avg_price=1469.0,
        entry_ist="2026-04-01",
        as_of_ist="2026-08-08",
        cfg={"plc_b_time_stop_days": 90, "plc_b_stop_loss_pct": 0.50},
    )
    assert timed is not None
    assert timed["exit_code"] == "time_stop"
    assert "time_stop" in (timed.get("candidates") or [timed["exit_code"]])


def test_concentration_and_thesis_broken():
    conc = evaluate_plc_b_exits(
        symbol="TCS.NS",
        price=3000.0,
        held=10.0,
        avg_price=2900.0,
        equity=50000.0,
        cfg={"plc_b_max_name_pct": 0.40, "plc_b_stop_loss_pct": 0.50},
    )
    assert conc is not None
    assert conc["exit_code"] == "concentration"
    assert failure_cause_for_exit("concentration", pnl=-1) == "portfolio_failure"

    broken = evaluate_plc_b_exits(
        symbol="INFY.NS",
        price=1500.0,
        held=1.0,
        avg_price=1490.0,
        equity=100000.0,
        awareness={"thesis": {"status": "falsified"}},
        cfg={"plc_b_stop_loss_pct": 0.50, "plc_b_max_name_pct": 0.90},
    )
    assert broken is not None
    assert broken["exit_code"] == "thesis_broken"
    assert failure_cause_for_exit("thesis_broken", pnl=-1) == "research_failure"


def test_no_invent_without_evidence():
    out = evaluate_plc_b_exits(
        symbol="RELIANCE.NS",
        price=1400.0,
        held=1.0,
        avg_price=1390.0,
        equity=100000.0,
        cfg={"plc_b_stop_loss_pct": 0.50, "plc_b_time_stop_days": 365},
    )
    assert out is None
