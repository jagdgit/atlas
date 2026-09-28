"""OI-LAB-LOOP0 Step 5 — blocked_buy is an experience, not a P&L outcome."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.experience_integrity import classify_experience_kind
from atlas.investment.lab_experience import (
    ACTION_BLOCKED_BUY,
    LIFECYCLE_CREATED,
    already_recorded,
    build_blocked_buy_experience,
    is_blocked_buy_tag,
    record_blocked_buy,
)
from atlas.investment.learning_objects import (
    infer_learning_event_kind,
    load_learning_events,
    summarize_learning_day,
)


_DAY = "2026-09-17"
_L10 = (
    "laboratory_id",
    "as_of_ist",
    "instrument",
    "state",
    "features",
    "action",
    "entry",
    "exit",
    "pnl",
    "costs",
    "reward",
    "regime",
    "strategy_version",
)


def test_blocked_buy_contract_has_l10_fields_without_pnl():
    exp = build_blocked_buy_experience(
        laboratory_id="india_equity_learner",
        symbol="YESBANK.NS",
        strategy_tag="plc_a_hold",
        reason="YESBANK.NS: plc_a_hold (pe,roe,debt_to_equity)",
        reasons_against=["pe", "roe", "debt_to_equity"],
        indicators={"rsi": 62.0, "sma_fast": 21.1, "sma_slow": 20.4, "signal": "buy"},
        gate={"allowed": False, "blocks": ["pe", "roe", "debt_to_equity"]},
        price=21.5,
        as_of_ist=_DAY,
    )
    for key in _L10:
        assert key in exp
    assert exp["action"] == ACTION_BLOCKED_BUY
    assert exp["event_kind"] == ACTION_BLOCKED_BUY
    assert exp["pnl"] is None
    assert exp["reward"] is None
    assert exp["costs"] is None
    assert exp["entry"] is None
    assert exp["exit"] is None
    assert exp["lifecycle"] == LIFECYCLE_CREATED
    assert exp["not_a_trade"] is True
    assert "Not a P&L outcome" in exp["honesty"]
    assert "Step 6" in exp["honesty"]
    assert exp["features"]["rsi"] == 62.0
    assert exp["state"]["gate"] == "plc_a_hold"
    assert exp["decision"]["intended_action"] == "buy"
    assert exp["decision"]["recorded_action"] == "hold"


def test_record_once_per_lab_symbol_gate_reason_day(tmp_path: Path):
    kw = dict(
        laboratory_id="india_equity_learner",
        symbol="YESBANK.NS",
        strategy_tag="plc_a_hold",
        reason="YESBANK.NS: plc_a_hold (pe,roe,debt_to_equity)",
        indicators={"rsi": 55.0},
        as_of_ist=_DAY,
    )
    first = record_blocked_buy(tmp_path, **kw)
    second = record_blocked_buy(tmp_path, **kw)
    assert first.get("ok") is True
    assert first.get("skipped") is False
    assert second.get("skipped") is True
    assert already_recorded(
        tmp_path,
        laboratory_id="india_equity_learner",
        fingerprint_s=first["fingerprint"],
        as_of_ist=_DAY,
    )
    rows = load_learning_events(tmp_path, "india_equity_learner", as_of_ist=_DAY)
    blocked = [r for r in rows if r.get("event_kind") == ACTION_BLOCKED_BUY]
    assert len(blocked) == 1
    assert blocked[0]["pnl"] is None
    assert blocked[0]["reward"] is None


def test_different_gate_records_second_row(tmp_path: Path):
    record_blocked_buy(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WELCORP.NS",
        strategy_tag="lab_policy_hold",
        reason="WELCORP.NS: lab_policy_hold (technical=BUY thesis=AVOID)",
        as_of_ist=_DAY,
    )
    record_blocked_buy(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WELCORP.NS",
        strategy_tag="plc_a_hold",
        reason="WELCORP.NS: plc_a_hold (pe)",
        as_of_ist=_DAY,
    )
    rows = load_learning_events(tmp_path, "india_equity_learner", as_of_ist=_DAY)
    assert len(rows) == 2


def test_engine_hold_is_not_blocked_buy():
    assert is_blocked_buy_tag("engine_hold") is False
    assert is_blocked_buy_tag("eod_flatten") is False
    assert is_blocked_buy_tag("capability_gap") is False
    assert is_blocked_buy_tag("switch_blocked_cold_start") is False
    assert is_blocked_buy_tag("plc_a_hold") is True
    assert is_blocked_buy_tag("fundamentals_incomplete") is True
    assert is_blocked_buy_tag("thesis_trigger_missing") is True
    assert is_blocked_buy_tag("research_forced_hold") is True
    assert is_blocked_buy_tag("add_blocked_quarantine") is True
    assert is_blocked_buy_tag("buy_blocked_research") is True
    assert infer_learning_event_kind(strategy_tag="engine_hold") != ACTION_BLOCKED_BUY
    assert classify_experience_kind(action="hold", strategy_tag="engine_hold") == "hold_review"


def test_lab_specific_fields_pass_through():
    tape = {"ist_date": _DAY, "interval": "5m", "bar_count": 12}
    fut = {"tradingsymbol": "NIFTYNEARFUT", "instrument_type": "FUT"}
    intra = build_blocked_buy_experience(
        laboratory_id="equity_intraday_learner",
        symbol="YESBANK.NS",
        strategy_tag="pack_block",
        reason="YESBANK.NS: pack_block (qty)",
        instrument={"intraday_tape": tape},
        as_of_ist=_DAY,
    )
    assert intra["lab_fields"]["intraday_tape"] == tape
    fno = build_blocked_buy_experience(
        laboratory_id="india_fno_learner",
        symbol="NIFTY",
        strategy_tag="pack_block",
        reason="NIFTY: pack_block (lot)",
        instrument={"fno_contract": fut, "nfo_tradingsymbol": "NIFTYNEARFUT"},
        as_of_ist=_DAY,
    )
    assert fno["lab_fields"]["fno_contract"]["tradingsymbol"] == "NIFTYNEARFUT"
    assert fno["instrument"]["nfo_tradingsymbol"] == "NIFTYNEARFUT"


def test_summarize_counts_blocked_buy_separately_from_trades(tmp_path: Path):
    record_blocked_buy(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="IDEA.NS",
        strategy_tag="research_forced_hold",
        reason="IDEA.NS: research_hold (thesis_watch_insufficient)",
        as_of_ist=_DAY,
    )
    rows = load_learning_events(tmp_path, "india_equity_learner", as_of_ist=_DAY)
    summary = summarize_learning_day(rows)
    assert summary["blocked_buys"] == 1
    assert summary["experiences"] == 1
    assert summary["prediction_errors_computed"] == 0
    assert rows[0].get("prediction_error") is None
