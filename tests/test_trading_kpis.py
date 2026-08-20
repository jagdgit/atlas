"""Trading KPI scorecard — operator playbook §4."""

from __future__ import annotations

from atlas.investment.trading_kpis import (
    build_trading_kpis,
    format_kpi_section,
    tag_trades_ist_day,
)


def test_build_trading_kpis_plan_fill_and_pnl():
    kpis = build_trading_kpis(
        portfolio={
            "cash": 34000,
            "holdings_value": 16000,
            "equity": 50000,
            "day_pnl": 120,
            "day_return_pct": 0.24,
            "total_pnl": 120,
            "total_return_pct": 0.24,
            "net_contributed_capital": 50000,
            "fees_paid": 45,
            "positions": [{"symbol": "EICHERMOT.NS", "qty": 2}],
            "recent_trades": [
                {
                    "side": "buy",
                    "symbol": "EICHERMOT.NS",
                    "quantity": 2,
                    "ist_day_match": True,
                }
            ],
        },
        plan={
            "phase": "learning",
            "confidence": "very_low",
            "candidates": [
                {"symbol": "EICHERMOT.NS"},
                {"symbol": "HDFCBANK.NS"},
                {"symbol": "TCS.NS"},
            ],
        },
        session_note={"reason_counts": {"research_hold": 4, "session_closed": 12}},
        research_digest={"studied": [{"symbol": "EICHERMOT.NS"}], "lessons": ["x"]},
        ist_date="2026-08-05",
    )
    assert kpis["buys_today"] == 1
    assert kpis["candidates_planned"] == 3
    assert kpis["candidates_filled"] == 1
    assert kpis["plan_fill_rate"] == round(1 / 3, 4)
    assert kpis["day_pnl"] == 120
    assert kpis["open_positions"] == 1
    assert kpis["research_studied"] == 1
    assert kpis["top_no_fill_reasons"][0]["reason"] == "session_closed"

    lines = format_kpi_section(kpis)
    blob = "\n".join(lines)
    assert "Trading KPIs" in blob
    assert "plan→fill" in blob.lower() or "Plan→fill" in blob


def test_untagged_historical_blotter_is_not_today():
    kpis = build_trading_kpis(
        portfolio={
            "cash": 15000,
            "equity": 50000,
            "positions": [{"symbol": "CIPLA.NS", "qty": 13}],
            "recent_trades": [
                {
                    "side": "buy",
                    "symbol": "APOLLOHOSP.NS",
                    "quantity": 1,
                    "created_at": "2026-08-10T04:00:00+00:00",
                },
                {
                    "side": "sell",
                    "symbol": "ASIANPAINT.NS",
                    "quantity": 1,
                    "created_at": "2026-08-11T04:00:00+00:00",
                },
            ],
        },
        ist_date="2026-08-13",
    )
    assert kpis["fills_today"] == 0
    assert kpis["buys_today"] == 0
    assert kpis["sells_today"] == 0
    assert kpis["filled_symbols"] == []


def test_tag_trades_ist_day_match():
    tagged = tag_trades_ist_day(
        [
            {"side": "buy", "created_at": "2026-08-13T04:30:00+00:00"},
            {"side": "sell", "created_at": "2026-08-12T10:00:00+00:00"},
        ],
        ist_date="2026-08-13",
    )
    assert tagged[0]["ist_day_match"] is True
    assert tagged[1]["ist_day_match"] is False
