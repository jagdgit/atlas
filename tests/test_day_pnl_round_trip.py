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
