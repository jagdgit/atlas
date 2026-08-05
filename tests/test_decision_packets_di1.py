"""DI.1 Decision Packets — hermetic builder, store, evening section, plan_watch."""

from __future__ import annotations

import inspect
from pathlib import Path

from atlas.investment.decision_packets import (
    PACKET_VERSION,
    DecisionPacketStore,
    build_packet,
    completeness_score,
    emit_plan_watch_packets,
    format_decisions_section,
    feature_contributions_v1,
)
from atlas.investment.reports import format_evening_report
from atlas.repositories import decision_packet_repo as dpr


def test_build_packet_buy_and_unknowns(tmp_path: Path):
    payload = build_packet(
        action="buy",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 7921.0, "filled_qty": 2, "fill_price": 7921.0},
        indicators={"rsi": 55.0, "sma_fast": 100.0, "sma_slow": 98.0},
        investment_score={
            "overall": 0.62,
            "confidence": "medium",
            "axes": {
                "financial_health": 0.5,
                "valuation": 0.4,
                "technical": 0.7,
                "macro_theme": 0.5,
                "risk": 0.5,
            },
        },
        reasons_for=["SMA fast above slow"],
        fundamentals={},  # empty → pe/fcf unknowns
    )
    assert payload["version"] == PACKET_VERSION
    assert payload["action"] == "buy"
    assert payload["strategy_tag"] == "sma_cross_rsi"
    assert "pe_missing" in payload["unknowns"]
    assert "fcf_missing" in payload["unknowns"]
    assert payload["feature_contributions"]["technical"] != 0
    assert 0.0 <= payload["meta"]["completeness"] <= 1.0
    assert completeness_score(payload) == payload["meta"]["completeness"]


def test_watch_packet_and_json_mirror(tmp_path: Path):
    store = DecisionPacketStore(data_dir=tmp_path)
    out = store.record(
        action="watch",
        symbol="HDFCBANK.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="plan_watch",
        ts_ist="2026-08-05",
        reasons_for=["daily plan candidate"],
        prices={"mark": 1600.0},
    )
    packet = out["packet"]
    assert packet["action"] == "watch"
    assert Path(out["mirror_path"]).is_file()
    loaded = store.get(packet["decision_id"])
    assert loaded is not None
    assert loaded["decision_id"] == packet["decision_id"]
    # Mutating source dossier-like dict must not change frozen packet on disk
    packet["reasons_for"].append("should not matter after reload")
    again = store.get(packet["decision_id"])
    assert again["reasons_for"] == ["daily plan candidate"]
    day = store.list_day(portfolio_key="india_equity_learner", ts_ist="2026-08-05")
    assert len(day) == 1
    assert day[0]["symbol"] == "HDFCBANK.NS"


def test_plan_watch_idempotent(tmp_path: Path):
    store = DecisionPacketStore(data_dir=tmp_path)
    plan = {
        "as_of": "2026-08-05",
        "portfolio_key": "india_equity_learner",
        "candidates": [
            {"symbol": "TCS.NS", "rank": 1, "sector": "IT", "why": "momentum", "suggested_notional": 5000},
            {"symbol": "INFY.NS", "rank": 2, "sector": "IT", "why": "quality"},
        ],
    }
    first = emit_plan_watch_packets(
        store, daily_plan=plan, portfolio_key="india_equity_learner", ts_ist="2026-08-05"
    )
    second = emit_plan_watch_packets(
        store, daily_plan=plan, portfolio_key="india_equity_learner", ts_ist="2026-08-05"
    )
    assert len(first) == 2
    assert second == []
    day = store.list_day(portfolio_key="india_equity_learner", ts_ist="2026-08-05")
    assert len(day) == 2
    assert all(p["strategy_tag"] == "plan_watch" for p in day)


def test_evening_report_includes_decisions_section(tmp_path: Path):
    store = DecisionPacketStore(data_dir=tmp_path)
    store.record(
        action="hold",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="research_forced_hold",
        ts_ist="2026-08-05",
        reasons_for=["research_hold (mvr)"],
        fundamentals={},
    )
    packets = store.list_day(portfolio_key="india_equity_learner", ts_ist="2026-08-05")
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "test", "phase": "learning", "confidence": "low"},
        portfolio={"cash": 1000, "decisions": packets},
        decisions=packets,
    )
    assert "Decisions today (1)" in body
    assert "EICHERMOT.NS" in body
    assert "research_forced_hold" in body


def test_feature_contributions_missing_research_is_zero():
    c = feature_contributions_v1(action="buy", investment_score=None, indicators={"rsi": 50})
    assert c["business"] == 0
    assert c["valuation"] == 0
    assert "technical" in c


def test_repo_has_no_update_or_delete():
    src = inspect.getsource(dpr.DecisionPacketRepository)
    assert "UPDATE" not in src.upper()
    assert "DELETE" not in src.upper()


def test_format_decisions_section_empty():
    lines = format_decisions_section([])
    assert any("Decisions today (0)" in ln for ln in lines)
