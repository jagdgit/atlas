"""UTS.C — E[R]×confidence + expected-advantage helpers (hermetic)."""

from __future__ import annotations

from atlas.investment.daily_plan import build_daily_plan
from atlas.investment.opportunity_switch import (
    REASON_ADVANTAGE_CLEARED,
    REASON_BLOCKED_COSTS,
    REASON_BLOCKED_MISSING_ER,
    REASON_HOLD_INCUMBENT,
    attach_opportunity_metrics,
    confidence_from_label,
    confidence_penalty,
    estimate_opportunity_metrics,
    evaluate_switch,
    expected_advantage,
    expected_return_from_row,
    risk_adjusted_score,
)


def test_committee_style_risk_adjusted_scores():
    # A 10%×0.90=9.0, B 18%×0.45=8.1, C 13%×0.80=10.4 → prefer C
    assert risk_adjusted_score(0.10, 0.90) == 0.09
    assert risk_adjusted_score(0.18, 0.45) == 0.081
    assert risk_adjusted_score(0.13, 0.80) == 0.104
    assert risk_adjusted_score(None, 0.9) is None
    assert risk_adjusted_score(0.1, None) is None


def test_expected_advantage_and_threshold_switch():
    # 14% - 9% - 1% cost = 4% > 2% threshold → switch
    out = evaluate_switch(
        expected_return_challenger=0.14,
        expected_return_hold=0.09,
        confidence_challenger=0.82,
        confidence_hold=0.58,
        threshold=0.02,
        transaction_cost=0.01,
    )
    assert out["decision"] == "switch"
    assert out["reason_code"] == REASON_ADVANTAGE_CLEARED
    assert out["expected_advantage"] is not None
    assert out["expected_advantage"] > 0.02

    tiny = evaluate_switch(
        expected_return_challenger=0.098,
        expected_return_hold=0.09,
        confidence_challenger=0.7,
        confidence_hold=0.7,
        threshold=0.02,
        transaction_cost=0.01,
    )
    assert tiny["decision"] == "hold"
    assert tiny["reason_code"] in {REASON_BLOCKED_COSTS, REASON_HOLD_INCUMBENT}


def test_missing_er_fail_closed():
    out = evaluate_switch(
        expected_return_challenger=0.12,
        expected_return_hold=None,
        confidence_challenger=0.8,
        confidence_hold=0.5,
    )
    assert out["decision"] == "hold"
    assert out["reason_code"] == REASON_BLOCKED_MISSING_ER
    adv = expected_advantage(0.1, None)
    assert adv["ok"] is False
    assert adv["reason_code"] == REASON_BLOCKED_MISSING_ER


def test_confidence_penalty_punishes_downgrade():
    # Flipping away from higher-confidence hold adds penalty
    p = confidence_penalty(0.9, 0.4, k=0.02, m=0.01)
    assert p > 0
    p2 = confidence_penalty(0.5, 0.5, k=0.02, m=0.01)
    assert p2 >= 0
    assert p > p2


def test_learning_row_uses_prototype_er():
    row = {
        "symbol": "AAA.NS",
        "score": 0.7,
        "phase": "learning",
        "confidence": "very_low",
        "components": {"momentum": 0.8},
    }
    er = expected_return_from_row(row)
    assert er is not None
    assert confidence_from_label("very_low") is None  # raw label still insufficient
    m = estimate_opportunity_metrics(row)
    assert m["computable"] is True
    assert m["er_model"] == "prototype_v1"
    assert "expected_return" not in m["missing"]
    assert m["confidence"] == 0.35


def test_active_row_computable_and_attach():
    row = {
        "symbol": "BBB.NS",
        "score": 0.7,
        "phase": "active",
        "confidence": "high",
        "components": {"momentum": 0.7},
    }
    er = expected_return_from_row(row)
    assert er is not None
    assert er > 0  # momentum 0.7 → positive
    m = estimate_opportunity_metrics(row)
    assert m["computable"] is True
    assert m["risk_adjusted_score"] == risk_adjusted_score(m["expected_return"], m["confidence"])
    target: dict = {"symbol": "BBB.NS"}
    attach_opportunity_metrics(target, row)
    assert target["expected_return"] == m["expected_return"]
    assert target["risk_adjusted_score"] == m["risk_adjusted_score"]


def test_daily_plan_attaches_metrics_when_active():
    ranked = [
        {
            "symbol": "GOOD.NS",
            "name": "Good",
            "sector": "X",
            "rank": 1,
            "score": 0.72,
            "phase": "active",
            "confidence": "medium",
            "reason": "Strong momentum",
            "components": {"momentum": 0.72},
            "explanations": [],
        },
        {
            "symbol": "COLD.NS",
            "name": "Cold",
            "sector": "Y",
            "rank": 2,
            "score": 0.5,
            "phase": "learning",
            "confidence": "very_low",
            "reason": "Learning",
            "components": {},
            "explanations": [],
        },
    ]
    plan = build_daily_plan(
        ranked,
        capital=10_000,
        max_candidates=2,
        extra={"phase": "active", "confidence": "medium"},
    )
    by = {c["symbol"]: c for c in plan["candidates"]}
    assert by["GOOD.NS"].get("expected_return") is not None
    assert by["GOOD.NS"].get("risk_adjusted_score") is not None
    assert by["GOOD.NS"].get("er_model") == "prototype_v1"
    # COLD still gets a prototype number (LOOP0 L1) — not silent missing_er
    assert by["COLD.NS"].get("expected_return") is not None
    assert by["COLD.NS"].get("opportunity_metrics", {}).get("computable") is True
    assert by["COLD.NS"].get("er_basis") == "prototype"
