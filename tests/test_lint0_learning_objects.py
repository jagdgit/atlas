"""OI-LINT0 Phase 4 — learning events, prediction error, five-track lessons."""

from __future__ import annotations

from atlas.investment.learning_objects import (
    LEARNING_EVENT_KINDS,
    build_lessons,
    build_trading_experience,
    compute_prediction_error,
    infer_learning_event_kind,
    load_learning_events,
    record_learning_event,
    summarize_learning_day,
)


def test_learning_event_kinds():
    assert infer_learning_event_kind(action="buy") == "fill"
    assert infer_learning_event_kind(action="sell", strategy_tag="eod_flatten") == "eod_flatten"
    assert infer_learning_event_kind(strategy_tag="switch_advantage_cleared") == "challenger_crossed_threshold"
    assert infer_learning_event_kind(strategy_tag="lab_policy_hold") == "lab_policy_hold"
    assert infer_learning_event_kind(trigger="llm_unavailable") == "llm_failure"
    assert "eod_flatten" in LEARNING_EVENT_KINDS


def test_prediction_error_computed():
    err = compute_prediction_error(predicted_er=0.04, realized_return_pct=1.2)
    assert err["status"] == "computed"
    assert err["error_pct"] is not None
    assert abs(float(err["error_pct"]) - (1.2 - 4.0)) < 0.01


def test_prediction_error_unknown_without_inputs():
    err = compute_prediction_error(predicted_er=None, realized_return_pct=None)
    assert err["status"] == "unknown"


def test_five_track_lessons_separate():
    lessons = build_lessons(
        strategy="SMA worked in lab",
        market="unknown cause",
        thesis="watch unchanged",
        atlas="packet honest",
        relative_opportunity="cash beat CIPLA",
    )
    assert lessons["strategy"] != lessons["market"]
    assert len([v for v in lessons.values() if v]) == 5


def test_eod_flatten_experience_requires_attribution():
    exp = build_trading_experience(
        laboratory_id="equity_intraday_learner",
        symbol="ASTRAL.NS",
        event_kind="eod_flatten",
        packet={"action": "sell", "strategy_tag": "eod_flatten", "expected": {"expected_return": 0.02}},
        trade={"realized_pnl": -50.0, "quantity": 2, "price": 1400.0},
    )
    assert exp["attribution"]["required"] is True
    assert exp["lessons"]["strategy"]
    assert exp["lessons"]["atlas"]
    assert exp["prediction_error"]["status"] == "computed"


def test_outcome_check_direction_miss_lessons():
    pkt = {
        "symbol": "CIPLA.NS",
        "action": "buy",
        "expected": {"expected_return": 0.05},
    }
    oc = {
        "expected_direction": "up",
        "observed_direction": "down",
        "direction_match": "missed",
        "thesis_change": "weaken",
        "price_change_pct": -3.5,
    }
    exp = build_trading_experience(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        event_kind="outcome_check",
        packet=pkt,
        outcome_check=oc,
    )
    assert exp["prediction_error"]["direction_match"] == "missed"
    assert exp["lessons"]["strategy"]
    assert exp["lessons"]["thesis"]


def test_persist_and_summarize(tmp_path):
    exp = build_trading_experience(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        event_kind="exit",
        packet={"expected": {"expected_return": 0.03}},
        trade={"realized_pnl": 100.0, "quantity": 1, "price": 1000.0},
    )
    out = record_learning_event(tmp_path, exp)
    assert out["ok"] is True
    rows = load_learning_events(tmp_path, "india_equity_learner")
    assert len(rows) == 1
    summary = summarize_learning_day(rows)
    assert summary["experiences"] == 1
    assert summary["prediction_errors_computed"] == 1


def test_challenger_threshold_event(tmp_path):
    from atlas.investment.learning_objects import record_challenger_threshold_event

    out = record_challenger_threshold_event(
        tmp_path,
        laboratory_id="india_equity_learner",
        review={
            "hold_symbol": "CIPLA.NS",
            "challenger_symbol": "BOSCHLTD.NS",
            "expected_advantage": 0.04,
            "decision": "switch",
        },
        executed=True,
    )
    assert out["ok"] is True
    rows = load_learning_events(tmp_path, "india_equity_learner")
    assert rows[-1]["event_kind"] == "challenger_crossed_threshold"
