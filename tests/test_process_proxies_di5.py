"""DI.5 process proxies — hermetic."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.investment.process_proxies import (
    build_process_scorecard,
    detect_packet_flags,
    format_process_proxies_section,
    gap_pct_from_bars,
    recent_loss_symbols,
)
from atlas.investment.reports import format_evening_report


def test_gap_pct_from_bars():
    bars = [
        {"close": 100.0},
        {"open": 104.0, "close": 105.0},
    ]
    assert gap_pct_from_bars(bars, 1) == 4.0


def test_fomo_and_plan_violation_flags():
    pkt = build_packet(
        action="buy",
        symbol="CHASE.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        prices={"mark": 104, "gap_pct": 4.0, "suggested_qty": 10, "filled_qty": 10},
        plan_link={"in_daily_plan": False, "rank": None},
        reasons_for=["sma cross"],
        investment_score={"investment_confidence": "low"},
        process_context={"gap_pct": 4.0, "recent_losses": set()},
    )
    flags = {f["proxy"] for f in (pkt["meta"].get("process_flags") or [])}
    assert "fomo" in flags
    assert "plan_violation" in flags


def test_revenge_from_recent_loss():
    losses = recent_loss_symbols(
        [{"symbol": "INFY.NS", "side": "sell", "pnl": -50.0}]
    )
    assert "INFY.NS" in losses
    flags = detect_packet_flags(
        {
            "action": "buy",
            "symbol": "INFY.NS",
            "plan_link": {"in_daily_plan": True, "rank": 1},
            "prices": {},
            "gates": {},
            "meta": {"completeness": 0.9},
            "reasons_for": ["plan"],
            "reasons_against": [],
            "investment_score": {"investment_confidence": "high"},
            "strategy_tag": "sma_cross_rsi",
        },
        recent_losses=losses,
    )
    assert any(f["proxy"] == "revenge" for f in flags)


def test_hesitation_scorecard_from_plan_fill():
    doc = build_process_scorecard(
        portfolio_key="india_equity_learner",
        ist_date="2026-08-05",
        packets=[],
        kpis={
            "candidates_planned": 5,
            "candidates_filled": 1,
            "plan_fill_rate": 0.2,
            "fills_today": 1,
        },
    )
    assert doc["counts"]["hesitation"] >= 1
    assert doc["process_score"] < 10


def test_evening_includes_process_proxies():
    card = build_process_scorecard(
        packets=[
            build_packet(
                action="buy",
                symbol="X.NS",
                portfolio_key="india_equity_learner",
                strategy_tag="sma_cross_rsi",
                prices={"gap_pct": 5.0},
                plan_link={"in_daily_plan": False},
                reasons_for=["x"],
                process_context={"gap_pct": 5.0},
            )
        ],
        kpis={"candidates_planned": 0, "candidates_filled": 0},
        ist_date="2026-08-05",
    )
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={"cash": 1, "process_proxies": card},
    )
    assert "Process proxies" in body
    lines = format_process_proxies_section(card)
    assert any("Score" in ln for ln in lines)
