"""OI-ICR4 — E[R] symmetry; no missing_er incumbent lock-in."""

from __future__ import annotations

from atlas.investment.allocation_comparison import (
    DECISION_HOLD,
    REASON_ADVANTAGE_UNCLEAR,
    build_allocation_comparison_packet,
    build_and_persist_lab_acps,
    decide_acp,
)
from atlas.investment.incumbent_capital import (
    load_acp_day_registry,
    register_acp_decision_today,
)
from atlas.investment.opportunity_switch import (
    REASON_ADVANTAGE_UNCLEAR as SW_UNCLEAR,
    REASON_BLOCKED_MISSING_ER,
    REASON_BLOCKED_PLC_A,
    review_hold_vs_challengers,
)


def _hold():
    return {
        "symbol": "CIPLA.NS",
        "qty": 15,
        "mark": 1400.0,
        "avg_price": 1450.0,
        "score": 0.6,
        "confidence": "medium",
        "components": {"momentum": 0.6},
    }


def _chal(sym: str, score: float = 0.85):
    return {
        "symbol": sym,
        "score": score,
        "confidence": "high",
        "components": {"momentum": score},
    }


def test_plc_a_blocked_still_scores_and_visible():
    hold = _hold()
    chal = _chal("INFY.NS", 0.95)
    out = review_hold_vs_challengers(
        hold,
        [chal],
        challenger_plc_a_ok={"INFY.NS": False},
        threshold=0.01,
        transaction_cost=0.01,
    )
    assert out["decision"] == "hold"
    assert out["reason_code"] == REASON_BLOCKED_PLC_A
    assert out["challenger_status"] == "plc_a_blocked"
    assert out["challenger_metrics"] is not None
    assert out["challenger_metrics"].get("expected_return") is not None
    # Advantage may be computed for display even when PLC.A blocks execute
    assert out.get("expected_advantage") is not None or out.get("evaluation") is not None


def test_acp_er_symmetry_all_legs_scored():
    acp = build_allocation_comparison_packet(
        hold=_hold(),
        challengers=[_chal("INFY.NS"), _chal("EICHERMOT.NS", 0.7)],
        cash=25_000.0,
        laboratory_id="india_equity_learner",
        awareness={
            "thesis": {
                "stance": "BUY",
                "summary": "CIPLA branded formulations India growth ROE",
                "id": "t1",
            },
            "valuation": {"margin_of_safety_pct": 10.0},
        },
        equity=100_000.0,
        challenger_plc_a_ok={"INFY.NS": False},
    )
    assert acp["er_symmetry"]["all_legs_scored"] is True
    assert acp["incumbent"]["expected_return"] is not None
    assert acp["cash"]["expected_return"] is not None
    for c in acp["challengers"]:
        assert c["expected_return"] is not None
    infy = next(c for c in acp["challengers"] if c["symbol"] == "INFY.NS")
    assert infy["challenger_status"] == "plc_a_blocked"


def test_decide_acp_maps_missing_er_to_advantage_unclear():
    decision, reason, why = decide_acp(
        stance="BUY",
        identity="VALID",
        mos=5.0,
        review={"decision": "hold", "reason_code": REASON_BLOCKED_MISSING_ER},
        incumbent_er_completeness=0.8,
    )
    assert decision == DECISION_HOLD
    assert reason == REASON_ADVANTAGE_UNCLEAR
    assert "lock-in" in why.lower() or "unclear" in why.lower()


def test_no_challengers_is_advantage_unclear_not_missing_er():
    out = review_hold_vs_challengers(_hold(), [])
    assert out["reason_code"] == SW_UNCLEAR
    assert out["reason_code"] != REASON_BLOCKED_MISSING_ER


def test_same_state_registry_once_per_day(tmp_path):
    r1 = register_acp_decision_today(
        tmp_path,
        laboratory_id="india_equity_learner",
        state_hash="abc123",
        symbol="CIPLA.NS",
        decision="HOLD",
        as_of_ist="2026-08-21",
    )
    assert r1["first"] is True
    r2 = register_acp_decision_today(
        tmp_path,
        laboratory_id="india_equity_learner",
        state_hash="abc123",
        symbol="CIPLA.NS",
        decision="HOLD",
        as_of_ist="2026-08-21",
    )
    assert r2["first"] is False
    reg = load_acp_day_registry(tmp_path, "india_equity_learner", "2026-08-21")
    assert "abc123" in reg["state_hashes"]

    batch = build_and_persist_lab_acps(
        data_dir=tmp_path,
        holds=[_hold()],
        challengers=[_chal("INFY.NS")],
        cash=10_000.0,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-08-21",
        awareness_by_symbol={
            "CIPLA.NS": {
                "thesis": {
                    "stance": "BUY",
                    "summary": "CIPLA branded formulations India growth",
                    "id": "t1",
                }
            }
        },
    )
    assert batch["count"] == 1
    # Second call same day → same_state_reused
    batch2 = build_and_persist_lab_acps(
        data_dir=tmp_path,
        holds=[_hold()],
        challengers=[_chal("INFY.NS")],
        cash=10_000.0,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-08-21",
        awareness_by_symbol={
            "CIPLA.NS": {
                "thesis": {
                    "stance": "BUY",
                    "summary": "CIPLA branded formulations India growth",
                    "id": "t1",
                }
            }
        },
    )
    assert batch2["same_state_reused"] >= 1
    assert batch2["packets"][0].get("same_state_today") is True
