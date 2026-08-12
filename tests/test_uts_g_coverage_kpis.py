"""UTS.G — coverage KPIs + why-not-switch status (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.coverage_kpis import (
    build_coverage_kpis,
    format_coverage_kpi_evening_lines,
    why_not_switch_into,
)
from atlas.investment.market_status_chat import answer_market_allocation_question
from atlas.investment.switch_learning import record_switch_decision


def test_build_coverage_kpis_honest_when_empty(tmp_path: Path):
    kpis = build_coverage_kpis(
        tmp_path,
        program_id="market_intelligence",
        laboratory_id="india_equity_learner",
        as_of_ist="2026-08-09",
    )
    assert kpis["ok"] is True
    assert kpis["rank_ladder_persisted"] is False
    assert kpis["status"] in {"red", "yellow"}
    lines = format_coverage_kpi_evening_lines(kpis)
    assert any("Coverage KPIs" in ln for ln in lines)


def test_switch_eval_honesty_unique_vs_raw(tmp_path: Path):
    for i in range(6):
        record_switch_decision(
            tmp_path,
            {
                "hold_symbol": "EICHERMOT.NS",
                "challenger_symbol": "DEVYANI.NS",
                "decision": "hold",
                "reason_code": "switch_blocked_cold_start",
                "expected_advantage": 0.01,
                "threshold": 0.02,
            },
            laboratory_id="india_equity_learner",
            decision_ist="2026-08-09",
            executed=False,
        )
    # One distinct pair
    record_switch_decision(
        tmp_path,
        {
            "hold_symbol": "EICHERMOT.NS",
            "challenger_symbol": "KEI.NS",
            "decision": "hold",
            "reason_code": "switch_blocked_cold_start",
            "expected_advantage": 0.02,
            "threshold": 0.02,
        },
        laboratory_id="india_equity_learner",
        decision_ist="2026-08-09",
        executed=False,
    )
    kpis = build_coverage_kpis(
        tmp_path,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-08-09",
    )
    assert kpis["switches_evaluated"] == 7
    assert kpis["switches_unique_comparisons"] == 2
    assert kpis["switches_routine_blocks"] == 7
    assert "unique" in (kpis.get("switches_honesty") or "").lower()
    blob = "\n".join(format_coverage_kpi_evening_lines(kpis))
    assert "Switch unique comparisons" in blob
    assert "Switch honesty" in blob


def test_why_not_switch_into_from_durable(tmp_path: Path):
    record_switch_decision(
        tmp_path,
        {
            "hold_symbol": "TCS.NS",
            "challenger_symbol": "BEL.NS",
            "decision": "hold",
            "reason_code": "switch_blocked_costs",
            "expected_advantage": 0.008,
            "threshold": 0.02,
            "exploratory": False,
            "hold_metrics": {"expected_return": 0.05, "confidence": 0.6},
            "challenger_metrics": {"expected_return": 0.07, "confidence": 0.7},
        },
        laboratory_id="india_equity_learner",
        decision_ist="2026-08-09",
        executed=False,
    )
    out = why_not_switch_into(
        tmp_path, "BEL.NS", laboratory_id="india_equity_learner"
    )
    assert out["ok"] is True
    assert out["reason_code"] == "switch_blocked_costs"
    assert "BEL.NS" in out["answer"]


def test_answer_market_allocation_questions(tmp_path: Path):
    scan = answer_market_allocation_question(
        "Did we scan the universe today?",
        data_dir=tmp_path,
    )
    assert scan is not None
    assert scan["kind"] == "coverage_kpis"
    assert "scan" in scan["answer"].lower() or "Coverage" in scan["answer"]

    why = answer_market_allocation_question(
        "why not switch into RELIANCE?",
        data_dir=tmp_path,
    )
    assert why is not None
    assert why["kind"] == "why_not_switch"
    assert "RELIANCE" in why["answer"]

    assert answer_market_allocation_question("hello", data_dir=tmp_path) is None
