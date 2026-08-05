"""Trading KPI scorecard — operator playbook §4."""

from __future__ import annotations

from atlas.investment.trading_kpis import build_trading_kpis, format_kpi_section


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
