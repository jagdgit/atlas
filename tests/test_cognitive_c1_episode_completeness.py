"""Cognitive Loop C1 — F&O session-flat closes must produce complete episodes.

Before C1 the Lab v1 close fell through every branch of
``attribution_required_for_close`` (lab not intraday, tag not in the exit set), so
``attribution.required`` was False, ``satisfied`` was False, and the Learning Auditor
reported ``chain_complete=0`` for episodes whose attribution was in fact the strongest
kind we produce (``evidence_backed``).
"""

from __future__ import annotations

from atlas.investment.lab_experience import attach_round_trip_l10
from atlas.investment.learning_audit import classify_learning_level
from atlas.investment.learning_objects import (
    attribution_required_for_close,
    build_trading_experience,
)

_CLOSE_TAG = "fno_lab_v1_experiment_close"
_LAB = "india_fno_learner"


def test_fno_session_flat_close_requires_attribution():
    assert attribution_required_for_close(laboratory_id=_LAB, strategy_tag=_CLOSE_TAG)
    # Any close in a session-flat lab is an exit, whatever the tag.
    assert attribution_required_for_close(laboratory_id=_LAB, strategy_tag="buy")


def test_cash_equity_hold_still_does_not_require_attribution():
    assert not attribution_required_for_close(
        laboratory_id="india_equity_learner", strategy_tag="buy"
    )
    assert attribution_required_for_close(
        laboratory_id="india_equity_learner", strategy_tag="sell"
    )


def test_evidence_backed_attribution_is_satisfied_and_reaches_l2():
    exp = build_trading_experience(
        laboratory_id=_LAB,
        symbol="ADANIPORTS26OCT1760CE",
        event_kind="exit",
        packet={
            "strategy_tag": _CLOSE_TAG,
            "action": "sell",
            "expected": {"expected_return": 0.08, "expected_direction": "up"},
        },
        trade={"realized_pnl": 2707.5, "price": 47.35, "quantity": 650},
        attribution={
            "payload": {
                "causal_factors": {
                    "status": "evidence_backed",
                    "helped": ["underlier_up"],
                    "hurt": [],
                    "unknown": ["iv_path"],
                }
            }
        },
        as_of_ist="2026-10-05",
    )
    attr = exp["attribution"]
    assert attr["status"] == "evidence_backed"
    assert attr["required"] is True
    assert attr["satisfied"] is True

    rec = {
        "prediction": exp["prediction_error"],
        "attribution": attr,
        "outcome": exp["outcome"],
    }
    assert classify_learning_level(rec) == "L2"
    # A lesson lifts it to L3 — but never past L4 without a subsequent test.
    rec["lesson"] = "CE legs tracked the underlier; thin sample."
    assert classify_learning_level(rec) == "L3"


def test_round_trip_recovers_decide_time_features_and_entry_time():
    out = attach_round_trip_l10(
        {"kind": "EXPERIENCE", "event_kind": "exit", "as_of_ist": "2026-10-05"},
        laboratory_id=_LAB,
        symbol="ADANIPORTS26OCT1760CE",
        trade={
            "id": "t-exit",
            "side": "sell",
            "quantity": 650,
            "price": 47.35,
            "realized_pnl": 2707.5,
            "buy_price": 41.65,
            "sold_at": "2026-10-05T10:11:14+00:00",
        },
        packet={
            "strategy_tag": _CLOSE_TAG,
            "entry_prediction": {
                "entry_time": "2026-10-05T05:48:34+00:00",
                "sma_margin": 0.027188573536532118,
                "control_action": "buy",
                "option_type": "CE",
                "underlying_type": "stock",
                "direction": "long_premium",
                "er_model": "fno_lab_v1_control_signal.v1",
                "key_evidence": ["control=sma_cross_rsi.v1 action=buy"],
            },
        },
        as_of_ist="2026-10-05",
    )
    assert out["entry"]["at"] == "2026-10-05T05:48:34+00:00"
    feats = out["features"]
    assert feats["features_source"] == "entry_prediction"
    assert feats["sma_margin"] == 0.027188573536532118
    assert feats["option_type"] == "CE"
    assert feats["signal"] == "sma_cross_rsi.v1"
    # Missing RSI stays absent — UNKNOWN, not a neutral 0.
    assert "rsi" not in feats
    assert out["holding_minutes"] is not None
    assert out["holding_minutes"] > 0


def test_episodes_written_before_the_fix_are_reclassified_without_rewriting_them():
    """C2 — the auditor derives 'addressed' from the preserved status.

    Rows already on disk carry required=False / satisfied=False from the old status
    set. They must still reach the learning layer on their real evidence, and must
    stop at L3: no lesson becomes validated without a subsequent test.
    """
    from atlas.investment.learning_audit import _provisional_learning_from_events
    from atlas.investment.learning_objects import summarize_learning_day

    stale = {
        "kind": "EXPERIENCE",
        "event_kind": "exit",
        "laboratory_id": _LAB,
        "symbol": "ADANIPORTS26OCT1760CE",
        "as_of_ist": "2026-10-05",
        "context": {"strategy_tag": _CLOSE_TAG, "action": "sell"},
        "attribution": {
            "status": "evidence_backed",
            "required": False,
            "satisfied": False,
            "causal_factors": {"helped": ["underlier_up"], "hurt": []},
        },
        "prediction_error": {
            "status": "computed",
            "predicted_er": 0.08,
            "realized_return_pct": 12.038,
            "error_pct": 4.038,
            "direction_match": "matched",
        },
        "outcome": {"realized_pnl": 2707.5},
        "belief_update": "unchanged",
    }

    summary = summarize_learning_day([stale])
    assert summary["attribution_required"] == 1
    assert summary["attribution_satisfied"] == 1

    recs = _provisional_learning_from_events([stale])
    assert len(recs) == 1
    assert recs[0]["chain_complete"] is True
    assert recs[0]["level"] == "L3"
    assert recs[0]["status"] == "PROVISIONAL"


def test_unknown_explicit_is_required_and_does_not_satisfy():
    """Documenting the absence of a cause must not complete the chain."""
    from atlas.investment.learning_audit import _provisional_learning_from_events
    from atlas.investment.learning_objects import attribution_is_satisfied, summarize_learning_day

    exp = build_trading_experience(
        laboratory_id=_LAB,
        symbol="ICICIBANK26OCT1320PE",
        event_kind="exit",
        packet={
            "strategy_tag": _CLOSE_TAG,
            "action": "sell",
            "expected": {"expected_return": 0.05, "expected_direction": "up"},
        },
        trade={"realized_pnl": -3535.0, "price": 20.0, "quantity": 700},
        attribution={
            "status": "unknown_explicit",
            "payload": {
                "causal_factors": {
                    "status": "unknown_explicit",
                    "helped": [],
                    "hurt": [],
                    "unknown": ["cause"],
                }
            },
        },
        as_of_ist="2026-10-05",
    )
    attr = exp["attribution"]
    assert attr["required"] is True
    assert attr["status"] == "unknown_explicit"
    assert attr["satisfied"] is False
    assert attribution_is_satisfied(attr) is False
    # A stale satisfied=True from an older writer does not override the status.
    assert attribution_is_satisfied({**attr, "satisfied": True}) is False

    row = {
        "kind": "EXPERIENCE",
        "event_kind": "exit",
        "laboratory_id": _LAB,
        "symbol": "ICICIBANK26OCT1320PE",
        "context": {"strategy_tag": _CLOSE_TAG},
        "attribution": {**attr, "satisfied": True},
        "prediction_error": {
            "status": "computed",
            "error_pct": -8.0,
            "direction_match": "missed",
        },
        "outcome": {"realized_pnl": -3535.0},
        "lessons": {"strategy": "Cause unknown — do not treat this as a lesson."},
    }
    summary = summarize_learning_day([row])
    assert summary["attribution_required"] == 1
    assert summary["attribution_satisfied"] == 0
    recs = _provisional_learning_from_events([row])
    assert len(recs) == 1
    assert recs[0]["chain_complete"] is False
    assert recs[0]["level"] == "L1"


def test_partial_attribution_stays_short_of_satisfied():
    exp = build_trading_experience(
        laboratory_id=_LAB,
        symbol="HDFCBANK26OCT710CE",
        event_kind="exit",
        packet={
            "strategy_tag": _CLOSE_TAG,
            "action": "sell",
            "expected": {"expected_return": 0.04, "expected_direction": "up"},
        },
        trade={"realized_pnl": -1365.0, "price": 12.0, "quantity": 550},
        attribution={
            "payload": {
                "causal_factors": {
                    "status": "partial",
                    "helped": ["underlier_up"],
                    "hurt": [],
                    "unknown": ["iv_path"],
                }
            }
        },
        as_of_ist="2026-10-05",
    )
    assert exp["attribution"]["status"] == "partial"
    assert exp["attribution"]["required"] is True
    assert exp["attribution"]["satisfied"] is False


def test_live_indicators_win_over_decide_time_fallback():
    out = attach_round_trip_l10(
        {"kind": "EXPERIENCE", "event_kind": "exit"},
        laboratory_id=_LAB,
        symbol="ADANIPORTS26OCT1760CE",
        trade={"side": "sell", "quantity": 1, "price": 10.0},
        packet={"entry_prediction": {"sma_margin": 0.02}},
        indicators={"rsi": 56.1, "sma_fast": 100.0, "sma_slow": 98.0},
        as_of_ist="2026-10-05",
    )
    assert out["features"]["rsi"] == 56.1
    assert "features_source" not in out["features"]
