"""Ranking & movements section in investor emails."""

from __future__ import annotations

from atlas.investment.reports import (
    format_evening_report,
    format_morning_report,
    format_ranking_movements_section,
)


def test_ranking_movements_section_shows_deltas():
    ranked = [
        {
            "symbol": "AAA.NS",
            "rank": 1,
            "score": 0.72,
            "confidence": "medium",
            "rank_delta_1d": 2,
            "rank_delta_3d": 5,
            "acceleration_3d": 3,
            "last_price": 100.5,
        },
        {
            "symbol": "BBB.NS",
            "rank": 2,
            "score": 0.61,
            "confidence": "low",
            "rank_delta_1d": -1,
            "last_price": 50.0,
        },
    ]
    lines = format_ranking_movements_section(
        ranked=ranked,
        plan={"phase": "active", "confidence": "medium"},
        triage={
            "ok": True,
            "coverage": {
                "price_coverage_pct": 98.0,
                "acceleration_status": "ok",
            },
        },
        fundamentals_coverage={"with_pe": 18, "symbols": 18},
    )
    blob = "\n".join(lines)
    assert "Ranking & movements" in blob
    assert "Ranking status" in blob
    assert "AAA.NS" in blob
    assert "Δ1=+2" in blob
    assert "accel3=+3" in blob
    assert "BBB.NS" in blob


def test_morning_and_evening_include_ranking_block():
    plan = {
        "as_of": "2026-08-09",
        "phase": "learning",
        "confidence": "very_low",
        "capital": 10000,
        "deploy_fraction": 0.4,
        "summary": "test",
        "candidates": [
            {
                "symbol": "TCS.NS",
                "rank": 1,
                "score": 0.55,
                "confidence": "low",
                "suggested_notional": 800,
                "suggested_weight": 0.2,
                "why": "quality",
                "rank_delta_1d": 1,
            }
        ],
        "avoids": [],
        "notes": [],
    }
    port = {
        "portfolio_key": "india_equity_learner",
        "ranked": plan["candidates"],
        "cash": 10000,
        "positions": [],
        "triage": {
            "ok": True,
            "coverage": {
                "price_coverage_pct": 10.0,
                "acceleration_status": "pending_history",
            },
        },
        "fundamentals_coverage": {"with_pe": 5, "symbols": 18},
    }
    _subj_m, body_m = format_morning_report(plan=plan, portfolio=port)
    assert "Ranking & movements" in body_m
    assert "TCS.NS" in body_m
    assert "Δ1=+1" in body_m
    assert "NOT YET TRUSTWORTHY" in body_m

    _subj_e, body_e = format_evening_report(plan=plan, portfolio=port)
    assert "Ranking & movements" in body_e
    assert "TCS.NS" in body_e
    assert "NOT YET TRUSTWORTHY" in body_e
