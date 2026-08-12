"""PLC.D — hypothesis on buy + 7/30/90/exit checks (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.plc_hypothesis import (
    buy_hypothesis_statement,
    complete_hypothesis_check,
    create_buy_hypothesis,
    find_open_buy_hypothesis_for_symbol,
    plc_d_enabled,
    run_due_hypothesis_checks,
)


def test_plc_d_enabled_defaults():
    assert plc_d_enabled({}, "india_equity_learner") is True
    assert plc_d_enabled({"plc_d_hypothesis": False}, "india_equity_learner") is False
    assert plc_d_enabled({}, "blotter") is False


def test_create_buy_hypothesis_schedule(tmp_path: Path):
    out = create_buy_hypothesis(
        tmp_path,
        symbol="EICHERMOT.NS",
        thesis_trigger="hospital demand recovery + MoS",
        laboratory_id="india_equity_learner",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        buy_ist="2026-08-01",
    )
    hyp = out["hypothesis"]
    assert hyp["hypothesis_id"]
    assert "EICHERMOT.NS outperforms NIFTY" in hyp["statement"]
    assert "hospital demand" in hyp["statement"]
    checks = hyp["extra"]["checks"]
    by_cp = {c["checkpoint"]: c for c in checks}
    assert by_cp["7d"]["due_ist"] == "2026-08-08"
    assert by_cp["30d"]["due_ist"] == "2026-08-31"
    assert by_cp["90d"]["due_ist"] == "2026-10-30"
    assert by_cp["exit"]["due_ist"] is None
    assert by_cp["7d"]["status"] == "pending"


def test_run_due_and_exit_check(tmp_path: Path):
    out = create_buy_hypothesis(
        tmp_path,
        symbol="CIPLA.NS",
        thesis_trigger="pharma relative strength",
        laboratory_id="india_equity_learner",
        portfolio_key="india_equity_learner",
        buy_ist="2026-07-01",
    )
    hid = out["hypothesis"]["hypothesis_id"]
    due = run_due_hypothesis_checks(
        tmp_path,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-08-08",
        limit=5,
    )
    assert due["completed"] >= 1  # at least 7d and possibly 30d
    found = find_open_buy_hypothesis_for_symbol(
        tmp_path, symbol="CIPLA.NS", laboratory_id="india_equity_learner"
    )
    # may still be open until exit/90d auto-inconclusive
    assert found is None or found.get("hypothesis_id") == hid or found.get("status")

    exit_out = complete_hypothesis_check(
        tmp_path,
        hypothesis_id=hid,
        checkpoint="exit",
        laboratory_id="india_equity_learner",
        observation_links=1,
        note="test sell",
        mark_exit=True,
    )
    assert exit_out["ok"] is True
    hyp2 = exit_out["hypothesis"]
    exit_row = next(
        c for c in hyp2["extra"]["checks"] if c["checkpoint"] == "exit"
    )
    assert exit_row["status"] == "done"


def test_statement_fallback_without_trigger():
    s = buy_hypothesis_statement("TCS.NS")
    assert "SMA/RSI" in s
    assert s.startswith("TCS.NS")
