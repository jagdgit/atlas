"""OI-LINT0 Phase 3B — next-rupee challenger table + switch threshold."""

from __future__ import annotations

from atlas.investment.capital_allocation import (
    ALLOC_CASH,
    ALLOC_HOLD,
    ALLOC_KEEP,
    ALLOC_ROTATE,
    allocation_action_from_review,
    build_challenger_table,
    build_switch_threshold,
    format_allocation_evening_lines,
    merge_allocation_curiosity,
    persist_allocation_table,
)
from atlas.investment.opportunity_switch import (
    REASON_ADVANTAGE_CLEARED,
    REASON_BLOCKED_COSTS,
    REASON_HOLD_INCUMBENT,
    evaluate_switch,
)


def _hold(sym: str, qty: int = 10, **kw) -> dict:
    return {"symbol": sym, "qty": qty, "score": 0.6, "confidence": "medium", **kw}


def _chal(sym: str, score: float, **kw) -> dict:
    return {
        "symbol": sym,
        "score": score,
        "confidence": "high",
        "phase": "active",
        "components": {"momentum": score},
        **kw,
    }


def test_cash_always_in_table():
    tbl = build_challenger_table(holds=[], challengers=[_chal("BOSCHLTD.NS", 0.85)], cash=100_000)
    syms = [r["symbol"] for r in tbl["rows"]]
    assert "CASH" in syms
    assert tbl["best_deploy"]["symbol"] in {"CASH", "BOSCHLTD.NS"}


def test_holding_gets_best_challenger_and_action():
    hold = _hold(
        "CIPLA.NS",
        components={"momentum": 0.55},
        rs_vs_benchmark_pct=2.0,
        pe=30.0,
        industry_pe_median=28.0,
        roe=0.14,
    )
    chal = _chal(
        "BOSCHLTD.NS",
        0.92,
        rs_vs_benchmark_pct=6.0,
        pe=22.0,
        industry_pe_median=30.0,
        roe=0.18,
    )
    tbl = build_challenger_table(holds=[hold], challengers=[chal], cash=50_000, threshold=0.02)
    row = next(r for r in tbl["rows"] if r["symbol"] == "CIPLA.NS")
    assert row["role"] == "holding"
    assert row["best_challenger"] == "BOSCHLTD.NS"
    assert row["expected_return"] is not None
    assert row["er_completeness"] is not None
    assert row["allocation_action"] in {ALLOC_ROTATE, ALLOC_HOLD, ALLOC_KEEP}


def test_advantage_below_threshold_is_hold_not_rotate():
    ev = evaluate_switch(
        expected_return_challenger=0.06,
        expected_return_hold=0.04,
        confidence_challenger=0.75,
        confidence_hold=0.75,
        threshold=0.03,
        transaction_cost=0.01,
    )
    assert ev["decision"] == "hold"
    assert ev["reason_code"] == REASON_BLOCKED_COSTS
    assert allocation_action_from_review(ev) == ALLOC_HOLD


def test_advantage_above_threshold_is_rotate():
    ev = evaluate_switch(
        expected_return_challenger=0.12,
        expected_return_hold=0.02,
        confidence_challenger=0.75,
        confidence_hold=0.75,
        threshold=0.02,
        transaction_cost=0.01,
    )
    assert ev["decision"] == "switch"
    assert ev["reason_code"] == REASON_ADVANTAGE_CLEARED
    assert allocation_action_from_review(ev) == ALLOC_ROTATE


def test_incumbent_wins_is_keep():
    ev = evaluate_switch(
        expected_return_challenger=0.01,
        expected_return_hold=0.06,
        confidence_challenger=0.75,
        confidence_hold=0.75,
        threshold=0.02,
    )
    assert ev["reason_code"] == REASON_HOLD_INCUMBENT
    assert allocation_action_from_review(ev) == ALLOC_KEEP


def test_switch_threshold_object_explicit():
    thr = build_switch_threshold(threshold=0.02, transaction_cost=0.01, exploratory=True, cold_start_threshold=0.05)
    assert thr["min_advantage"] == 0.05
    assert thr["transaction_cost"] == 0.01


def test_persist_and_evening_lines(tmp_path):
    tbl = build_challenger_table(
        holds=[_hold("CIPLA.NS")],
        challengers=[_chal("ASTRAL.NS", 0.8)],
        cash=25_000,
        laboratory_id="india_equity_learner",
    )
    out = persist_allocation_table(tmp_path, tbl)
    assert out["ok"] is True
    lines = format_allocation_evening_lines(tbl)
    blob = "\n".join(lines)
    assert "Next ₹1" in blob
    assert "CIPLA.NS" in blob
    assert "CASH" in blob


def test_curiosity_boosts_allocation_blocking_unknowns():
    tbl = build_challenger_table(
        holds=[
            _hold(
                "CIPLA.NS",
                components={"momentum": 0.6},
                confidence="very_low",
                phase="learning",
            )
        ],
        challengers=[_chal("ASTRAL.NS", 0.9)],
        cash=10_000,
    )
    qdoc = merge_allocation_curiosity({"items": [], "ist_date": "2026-08-20"}, tbl)
    assert qdoc.get("allocation_boosted", 0) >= 1
    assert any(i.get("allocation_blocking") for i in qdoc.get("items") or [])


def test_best_deploy_can_be_cash_when_no_challengers():
    tbl = build_challenger_table(holds=[], challengers=[], cash=100_000)
    assert tbl["best_deploy"]["symbol"] == "CASH"
    cash_row = next(r for r in tbl["rows"] if r["symbol"] == "CASH")
    assert cash_row["allocation_action"] == ALLOC_CASH
