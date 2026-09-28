"""OI-ICR1 — Allocation Comparison Packet builder + persist."""

from __future__ import annotations

from atlas.investment.allocation_comparison import (
    DECISION_EXIT_REVIEW,
    DECISION_HOLD,
    DECISION_KEEP,
    DECISION_SWITCH_REVIEW,
    build_allocation_comparison_packet,
    build_and_persist_lab_acps,
    decide_acp,
    load_latest_acp_summary,
    persist_acp,
)
from atlas.investment.incumbent_capital import REASON_ADD_BLOCKED_NO_ACP, evaluate_icr0_buy
from atlas.investment.opportunity_switch import REASON_ADVANTAGE_CLEARED, REASON_HOLD_INCUMBENT


def _hold(sym: str = "CIPLA.NS", **kw):
    return {
        "symbol": sym,
        "qty": 15,
        "avg_price": 1460.0,
        "mark": 1438.0,
        "score": 0.55,
        "confidence": "medium",
        "components": {"momentum": 0.5},
        **kw,
    }


def _chal(sym: str, score: float = 0.85, **kw):
    return {
        "symbol": sym,
        "score": score,
        "confidence": "high",
        "phase": "active",
        "components": {"momentum": score},
        "rs_vs_benchmark_pct": 5.0,
        "pe": 20.0,
        "industry_pe_median": 28.0,
        "roe": 0.18,
        **kw,
    }


def test_decide_acp_quarantine_and_avoid():
    d, code, _ = decide_acp(
        stance="WATCH",
        identity="QUARANTINED",
        mos=None,
        review=None,
        incumbent_er_completeness=0.8,
    )
    assert d == DECISION_EXIT_REVIEW
    assert "quarantine" in code

    d2, code2, _ = decide_acp(
        stance="AVOID",
        identity="VALID",
        mos=-55.0,
        review=None,
        incumbent_er_completeness=0.8,
    )
    assert d2 == DECISION_EXIT_REVIEW
    assert "avoid" in code2 or "mos" in code2


def test_build_acp_cipla_like_exit_review(tmp_path):
    aw = {
        "thesis": {
            "stance": "avoid",
            "summary": (
                "CIPLA hospital network occupancy ARPOB — contaminated identity"
            ),
            "id": "th-CIPLA.NS",
        },
        "valuation": {"margin_of_safety_pct": -55.24},
    }
    acp = build_allocation_comparison_packet(
        hold=_hold(),
        challengers=[_chal("INFY.NS"), _chal("EICHERMOT.NS", 0.7)],
        cash=25_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        equity=100_000.0,
    )
    assert acp["kind"] == "allocation_comparison_packet"
    assert acp["decision"] == DECISION_EXIT_REVIEW
    assert acp["cash"]["symbol"] == "CASH"
    assert acp["incumbent"]["symbol"] == "CIPLA.NS"
    assert acp["provenance"]["acp_id"] == acp["acp_id"]
    assert acp["operator_line"]
    assert "ADD" != acp["decision"]

    out = persist_acp(tmp_path, acp)
    assert out["ok"] is True
    summary = load_latest_acp_summary(tmp_path, "india_equity_learner", "CIPLA.NS")
    assert summary is not None
    assert summary["decision"] == DECISION_EXIT_REVIEW

    # ICR.0 still blocks ADD without decision=ADD
    gate = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=aw,
        data_dir=tmp_path,
    )
    assert gate["allowed"] is False
    assert gate["reason_code"] in {
        "add_blocked_research",
        "add_blocked_quarantine",
        REASON_ADD_BLOCKED_NO_ACP,
    }


def test_build_acp_keep_when_incumbent_wins():
    hold = _hold(
        "RELIANCE.NS",
        components={"momentum": 0.8},
        rs_vs_benchmark_pct=4.0,
        pe=22.0,
        industry_pe_median=25.0,
        roe=0.16,
    )
    chal = _chal("INFY.NS", 0.55)
    review = {
        "hold_symbol": "RELIANCE.NS",
        "challenger_symbol": "INFY.NS",
        "decision": "hold",
        "reason_code": REASON_HOLD_INCUMBENT,
        "expected_advantage": -0.01,
        "hold_metrics": {"expected_return": 0.05, "confidence": 0.55, "er_completeness": 0.7},
        "challenger_metrics": {"expected_return": 0.03, "confidence": 0.55},
    }
    aw = {
        "thesis": {
            "stance": "BUY",
            "summary": "Integrated energy franchise with retail and digital optionality.",
            "id": "th-RELIANCE",
        }
    }
    acp = build_allocation_comparison_packet(
        hold=hold,
        challengers=[chal],
        cash=10_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        review=review,
    )
    assert acp["decision"] in {DECISION_KEEP, DECISION_HOLD}
    assert acp["decision"] != DECISION_EXIT_REVIEW


def test_build_acp_switch_review_when_advantage_cleared():
    review = {
        "hold_symbol": "CIPLA.NS",
        "challenger_symbol": "INFY.NS",
        "decision": "switch",
        "reason_code": REASON_ADVANTAGE_CLEARED,
        "expected_advantage": 0.05,
    }
    aw = {
        "thesis": {
            "stance": "WATCH",
            "summary": "Cipla branded generics respiratory franchise ANDA.",
            "id": "th-CIPLA.NS",
        }
    }
    acp = build_allocation_comparison_packet(
        hold=_hold(components={"momentum": 0.4}, rs_vs_benchmark_pct=0.0, pe=40, industry_pe_median=28, roe=0.12),
        challengers=[_chal("INFY.NS", 0.9)],
        cash=5_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        review=review,
    )
    assert acp["decision"] == DECISION_SWITCH_REVIEW


def test_build_and_persist_lab_acps(tmp_path):
    aw = {
        "CIPLA.NS": {
            "thesis": {
                "stance": "avoid",
                "summary": "avoid",
                "id": "th-1",
            },
            "valuation": {"margin_of_safety_pct": -40.0},
        }
    }
    result = build_and_persist_lab_acps(
        data_dir=tmp_path,
        holds=[_hold()],
        challengers=[_chal("INFY.NS")],
        cash=20_000.0,
        laboratory_id="india_equity_learner",
        awareness_by_symbol=aw,
        equity=80_000.0,
    )
    assert result["count"] == 1
    assert result["persisted"] == 1
    assert result["lines"]
