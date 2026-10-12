"""Day P&L must not invent weekend-gap profits on same-day round-trips."""

from __future__ import annotations

from atlas.workers.investor_reports import InvestorReportsWorker


def test_same_day_round_trip_is_sell_minus_buy_not_mark_minus_previous():
    """Reproduce WELCORP email phantom: ~63 sh × (Fri−Thu) ≈ ₹19,260."""
    mark = 2311.89990234375  # Friday close used as "mark" mid-session
    previous = 2005.199951171875  # Thursday
    buy_px = 2402.0
    sell_px = 2410.0
    qty = 63.0

    # Flat after round-trip
    day_pnl = InvestorReportsWorker._compute_day_pnl(
        positions=[],
        day_trades=[
            {
                "symbol": "WELCORP.NS",
                "side": "buy",
                "quantity": qty,
                "price": buy_px,
                "fee": 0,
                "ist_day_match": True,
            },
            {
                "symbol": "WELCORP.NS",
                "side": "sell",
                "quantity": qty,
                "price": sell_px,
                "fee": 0,
                "ist_day_match": True,
            },
        ],
        marks={"WELCORP.NS": mark},
        previous={"WELCORP.NS": previous},
    )
    expected = qty * (sell_px - buy_px)  # +504
    assert day_pnl is not None
    assert abs(day_pnl - expected) < 1e-6
    # Old formula would have been expected + qty*(mark-previous) ≈ 19,760
    phantom = expected + qty * (mark - previous)
    assert abs(phantom - 19824.0) < 1.0 or phantom > 15_000
    assert day_pnl < 1_000


def test_overnight_hold_marks_to_previous():
    day_pnl = InvestorReportsWorker._compute_day_pnl(
        positions=[{"symbol": "WELCORP.NS", "quantity": 23}],
        day_trades=[],
        marks={"WELCORP.NS": 2409.2},
        previous={"WELCORP.NS": 2311.9},
    )
    assert day_pnl is not None
    assert abs(day_pnl - 23 * (2409.2 - 2311.9)) < 1e-6


def test_flat_book_still_reports_closed_day_pnl():
    """After eod_flatten, marks may be empty — day P&L must not become None."""
    day_pnl = InvestorReportsWorker._compute_day_pnl(
        positions=[],
        day_trades=[
            {
                "symbol": "WELCORP.NS",
                "side": "buy",
                "quantity": 3,
                "price": 2400.0,
                "fee": 0,
                "ist_day_match": True,
            },
            {
                "symbol": "WELCORP.NS",
                "side": "sell",
                "quantity": 3,
                "price": 2410.0,
                "fee": 0,
                "ist_day_match": True,
            },
        ],
        marks={},
        previous={},
    )
    assert day_pnl == 30.0


def test_add_cash_sell_at_mark_is_zero_not_null():
    """LM-PNL1 — concentration sell @ prior mark → day_pnl 0.0 + honesty note."""
    w = InvestorReportsWorker.__new__(InvestorReportsWorker)
    w._portfolio = None
    doc = {
        "equity": 55477.0,
        "starting_cash": 55000.0,
        "positions": [],
        "marks": {},
        "previous_closes": {},
        "recent_trades": [
            {
                "symbol": "WELCORP.NS",
                "side": "sell",
                "quantity": 23,
                "price": 2409.2,
                "fee": 0,
                "realized_pnl": 2237.9,
                "created_at": "2026-08-25T03:48:21Z",
            }
        ],
    }
    w._add_cash_and_pnl_metrics(doc, pid="x", ist_date="2026-08-25")
    assert doc.get("day_pnl") == 0.0
    assert doc.get("day_pnl_note")
    assert "prior" in doc["day_pnl_note"].lower() or "0" in doc["day_pnl_note"]


def test_add_cash_prefers_full_day_trades_over_truncated_recent():
    """F&O-style day: 16 fills, recent_trades capped at 10 must not understate P&L."""
    w = InvestorReportsWorker.__new__(InvestorReportsWorker)
    w._portfolio = None
    day_trades = []
    for i, (buy, sell, qty, rpnl) in enumerate(
        [
            (100.0, 110.0, 10.0, 100.0),
            (200.0, 220.0, 5.0, 100.0),
            (50.0, 60.0, 20.0, 200.0),
            (10.0, 12.0, 100.0, 200.0),
            (30.0, 33.0, 40.0, 120.0),
            (40.0, 44.0, 25.0, 100.0),
            (15.0, 18.0, 50.0, 150.0),
            (8.0, 10.0, 80.0, 160.0),
        ]
    ):
        sym = f"OPT{i}"
        day_trades.append(
            {
                "symbol": sym,
                "side": "buy",
                "quantity": qty,
                "price": buy,
                "fee": 0,
                "ist_day_match": True,
            }
        )
        day_trades.append(
            {
                "symbol": sym,
                "side": "sell",
                "quantity": qty,
                "price": sell,
                "fee": 0,
                "realized_pnl": rpnl,
                "ist_day_match": True,
            }
        )
    # Newest-first blotter truncation keeps only sells + 2 buys.
    recent = list(reversed(day_trades))[:10]
    doc = {
        "equity": 150000.0,
        "starting_cash": 100000.0,
        "positions": [],
        "marks": {},
        "previous_closes": {},
        "recent_trades": recent,
        "day_trades": day_trades,
    }
    w._add_cash_and_pnl_metrics(doc, pid="x", ist_date="2026-10-12")
    assert abs(float(doc["day_pnl"]) - 1130.0) < 1e-6


def test_kpi_rebuilds_day_pnl_for_flat_book_without_marks():
    from atlas.investment.trading_kpis import build_trading_kpis

    day = [
        {
            "symbol": "NIFTY26OCT22550PE",
            "side": "buy",
            "quantity": 65,
            "price": 264.5,
            "fee": 0,
            "ist_day_match": True,
        },
        {
            "symbol": "NIFTY26OCT22550PE",
            "side": "sell",
            "quantity": 65,
            "price": 342.95,
            "fee": 0,
            "realized_pnl": 5099.25,
            "ist_day_match": True,
        },
    ]
    kpis = build_trading_kpis(
        portfolio={
            "cash": 150204.68,
            "equity": 150204.68,
            "positions": [],
            "marks": {},
            "previous_closes": {},
            "day_pnl": None,
            "fees_paid": 603.26,  # lifetime — must not leak into day KPI
            "day_trades": day,
            "recent_trades": day[:1],
        },
        ist_date="2026-10-12",
    )
    assert abs(float(kpis["day_pnl"]) - 5099.25) < 1e-6
    assert float(kpis["fees_paid"]) == 0.0
    assert kpis["fills_today"] == 2
