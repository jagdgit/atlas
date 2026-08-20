"""UTS.D — hold-vs-challenger portfolio review (hermetic)."""

from __future__ import annotations

from atlas.investment.opportunity_switch import (
    REASON_ADVANTAGE_CLEARED,
    REASON_BLOCKED_COLD_START,
    REASON_BLOCKED_COSTS,
    REASON_BLOCKED_MISSING_ER,
    REASON_BLOCKED_PLC_A,
    REASON_EXPLORATORY,
    REASON_HOLD_INCUMBENT,
    opportunity_switch_enabled,
    review_hold_vs_challengers,
    review_portfolio_switches,
)


def _active(sym: str, score: float, conf: str = "high") -> dict:
    return {
        "symbol": sym,
        "qty": 10,
        "score": score,
        "confidence": conf,
        "phase": "active",
        "components": {"momentum": score},
    }


def test_opportunity_switch_enabled_learner_default():
    assert opportunity_switch_enabled({}, "india_equity_learner") is True
    assert opportunity_switch_enabled({}, "other_book") is False
    assert opportunity_switch_enabled({"opportunity_switch_enabled": False}, "india_equity_learner") is False
    assert opportunity_switch_enabled({"opportunity_switch_enabled": True}, "cash") is True


def test_review_picks_best_challenger_when_advantage_clears():
    hold = _active("HOLD.NS", 0.55, "medium")
    weak = _active("WEAK.NS", 0.56, "medium")
    strong = _active("STRONG.NS", 0.95, "high")
    out = review_hold_vs_challengers(
        hold,
        [weak, strong],
        threshold=0.02,
        transaction_cost=0.01,
        exploratory=False,
    )
    assert out["decision"] == "switch"
    assert out["challenger_symbol"] == "STRONG.NS"
    assert out["reason_code"] == REASON_ADVANTAGE_CLEARED
    assert out["evaluated_challengers"] == 2
    assert out["expected_advantage"] is not None
    assert out["expected_advantage"] > 0.02


def test_review_exploratory_label_uses_cold_threshold():
    hold = _active("HOLD.NS", 0.60, "medium")
    # Modest edge — clears 2% but not 5% after costs/penalty in typical math
    chal = _active("CHAL.NS", 0.72, "medium")
    calibrated = review_hold_vs_challengers(
        hold,
        [chal],
        threshold=0.02,
        cold_start_threshold=0.05,
        transaction_cost=0.01,
        exploratory=False,
    )
    exploratory = review_hold_vs_challengers(
        hold,
        [chal],
        threshold=0.02,
        cold_start_threshold=0.05,
        transaction_cost=0.01,
        exploratory=True,
    )
    assert exploratory["label"] == "exploratory"
    assert exploratory["threshold"] == 0.05
    if calibrated["decision"] == "switch":
        assert exploratory["decision"] in {"switch", "hold"}
        if exploratory["decision"] == "switch":
            assert exploratory["reason_code"] == REASON_EXPLORATORY
    else:
        assert exploratory["decision"] == "hold"
        assert exploratory["reason_code"] in {
            REASON_BLOCKED_COSTS,
            REASON_HOLD_INCUMBENT,
            REASON_BLOCKED_MISSING_ER,
        }


def test_review_plc_a_blocks_challenger():
    hold = _active("HOLD.NS", 0.50, "medium")
    chal = _active("CHAL.NS", 0.95, "high")
    out = review_hold_vs_challengers(
        hold,
        [chal],
        threshold=0.02,
        transaction_cost=0.01,
        exploratory=False,
        challenger_plc_a_ok={"CHAL.NS": False},
    )
    assert out["decision"] == "hold"
    assert out["reason_code"] == REASON_BLOCKED_PLC_A
    assert out["challenger_symbol"] == "CHAL.NS"


def test_review_learning_hold_uses_prototype():
    hold = {
        "symbol": "LEARN.NS",
        "qty": 5,
        "score": 0.7,
        "confidence": "very_low",
        "phase": "learning",
        "components": {"momentum": 0.7},
    }
    chal = _active("CHAL.NS", 0.9, "high")
    out = review_hold_vs_challengers(hold, [chal], exploratory=False)
    assert out["decision"] in {"hold", "switch"}
    assert out["reason_code"] not in {REASON_BLOCKED_COLD_START, REASON_BLOCKED_MISSING_ER}
    assert out["hold_metrics"]["er_model"] == "prototype_v1"
    assert out["hold_metrics"]["expected_return"] is not None


def test_review_portfolio_one_row_per_open_hold():
    holds = [
        _active("A.NS", 0.5, "medium"),
        _active("B.NS", 0.55, "medium"),
        {"symbol": "FLAT.NS", "qty": 0, "score": 0.9, "confidence": "high", "phase": "active"},
    ]
    chals = [_active("C.NS", 0.95, "high")]
    rows = review_portfolio_switches(
        holds, chals, threshold=0.02, transaction_cost=0.01, exploratory=False
    )
    assert len(rows) == 2
    assert {r["hold_symbol"] for r in rows} == {"A.NS", "B.NS"}
    for r in rows:
        assert r["decision"] in {"switch", "hold"}
        assert r["reason_code"]
