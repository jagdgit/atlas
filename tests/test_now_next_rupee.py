"""NOW #8 — Next-₹1 economic center."""

from __future__ import annotations

from atlas.investment.capital_allocation import build_challenger_table
from atlas.investment.next_rupee import (
    build_and_persist_next_rupee,
    build_next_rupee_center,
    format_next_rupee_evening_lines,
    load_next_rupee,
)


def _hold(sym: str, qty: int = 10, **kw):
    return {"symbol": sym, "qty": qty, "score": 0.5, "confidence": "medium", **kw}


def _chal(sym: str, score: float, **kw):
    return {
        "symbol": sym,
        "score": score,
        "confidence": "high",
        "phase": "active",
        "components": {"momentum": score},
        **kw,
    }


def test_next_rupee_answers_deploy_vs_cash_and_incumbent():
    hold = _hold(
        "CIPLA.NS",
        components={"momentum": 0.4},
        rs_vs_benchmark_pct=0.0,
        pe=40.0,
        industry_pe_median=28.0,
    )
    chal = _chal(
        "PRAJIND.NS",
        0.9,
        rs_vs_benchmark_pct=8.0,
        pe=18.0,
        industry_pe_median=28.0,
        roe=0.2,
    )
    tbl = build_challenger_table(
        holds=[hold],
        challengers=[chal],
        cash=50_000,
        laboratory_id="india_equity_learner",
        threshold=0.02,
    )
    doc = build_next_rupee_center(
        tbl,
        acp_summaries=[
            {"symbol": "CIPLA.NS", "decision": "EXIT_REVIEW", "reason_code": "avoid"}
        ],
        laboratory_id="india_equity_learner",
    )
    assert doc["kind"] == "NEXT_RUPEE_CENTER"
    assert doc["never_orders"] is True
    assert doc["no_capital_increase"] is True
    assert "Next ₹1 →" in doc["operator_answer"]
    assert doc["destination"] in {"PRAJIND.NS", "CASH", "CIPLA.NS"}
    # CIPLA should appear as rejected incumbent when not destination
    if doc["destination"] != "CIPLA.NS":
        assert any(r.get("symbol") == "CIPLA.NS" for r in doc["rejected"])
        assert any(
            "EXIT_REVIEW" in (r.get("why_not") or "")
            for r in doc["rejected"]
            if r.get("symbol") == "CIPLA.NS"
        )


def test_next_rupee_cash_when_no_challengers():
    tbl = build_challenger_table(
        holds=[], challengers=[], cash=100_000, laboratory_id="lab"
    )
    doc = build_next_rupee_center(tbl, laboratory_id="lab")
    assert doc["destination"] == "CASH"
    assert doc["destination_action"] == "HOLD_CASH"
    assert "CASH" in doc["operator_answer"]


def test_persist_and_evening_lines(tmp_path):
    tbl = build_challenger_table(
        holds=[],
        challengers=[_chal("INFY.NS", 0.8)],
        cash=20_000,
        laboratory_id="india_equity_learner",
    )
    doc = build_and_persist_next_rupee(
        tmp_path, tbl, laboratory_id="india_equity_learner"
    )
    assert doc.get("path")
    loaded = load_next_rupee(tmp_path, "india_equity_learner")
    assert loaded is not None
    assert loaded["destination"] == doc["destination"]
    lines = format_next_rupee_evening_lines(loaded)
    assert any("economic center" in ln for ln in lines)
    assert any("Next ₹1 →" in ln for ln in lines)
