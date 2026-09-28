"""OI-LEDGER-UI1 — FIFO closed round-trips + tax/P&L rollup for Market UI."""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.trading.round_trips import build_closed_round_trips, summarize_taxes_and_pnl


def test_build_closed_round_trips_fifo_partial():
    trades = [
        {
            "id": "s1",
            "symbol": "AAA.NS",
            "side": "sell",
            "quantity": 5,
            "price": 120.0,
            "fee": 10.0,
            "realized_pnl": 40.0,
            "fees": {"stt": 1.0, "brokerage": 9.0},
            "created_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
        },
        {
            "id": "b2",
            "symbol": "AAA.NS",
            "side": "buy",
            "quantity": 4,
            "price": 105.0,
            "fee": 4.0,
            "realized_pnl": 0.0,
            "fees": {},
            "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        },
        {
            "id": "b1",
            "symbol": "AAA.NS",
            "side": "buy",
            "quantity": 10,
            "price": 100.0,
            "fee": 5.0,
            "realized_pnl": 0.0,
            "fees": {},
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ]
    closed = build_closed_round_trips(trades)
    assert len(closed) == 1
    leg = closed[0]
    assert leg["symbol"] == "AAA.NS"
    assert leg["quantity"] == 5
    assert leg["buy_price"] == 100.0
    assert leg["sell_price"] == 120.0
    assert "2026-01-01" in str(leg["bought_at"])
    assert "2026-01-03" in str(leg["sold_at"])
    assert leg["realized_pnl"] == 40.0


def test_build_closed_round_trips_two_legs():
    trades = [
        {
            "id": "s1",
            "symbol": "BBB.NS",
            "side": "sell",
            "quantity": 15,
            "price": 50.0,
            "fee": 3.0,
            "realized_pnl": 30.0,
            "created_at": datetime(2026, 2, 2, tzinfo=timezone.utc),
        },
        {
            "id": "b1",
            "symbol": "BBB.NS",
            "side": "buy",
            "quantity": 10,
            "price": 40.0,
            "fee": 1.0,
            "realized_pnl": 0.0,
            "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        },
        {
            "id": "b2",
            "symbol": "BBB.NS",
            "side": "buy",
            "quantity": 10,
            "price": 45.0,
            "fee": 1.0,
            "realized_pnl": 0.0,
            "created_at": datetime(2026, 2, 1, hour=1, tzinfo=timezone.utc),
        },
    ]
    closed = build_closed_round_trips(trades)
    assert len(closed) == 2
    qtys = sorted(c["quantity"] for c in closed)
    assert qtys == [5.0, 10.0]
    assert sum(c["realized_pnl"] for c in closed) == 30.0
    buy_prices = {c["buy_price"] for c in closed}
    assert buy_prices == {40.0, 45.0}


def test_summarize_taxes_and_pnl():
    doc = summarize_taxes_and_pnl(
        fee_components={
            "brokerage": 20.0,
            "stt": 5.0,
            "stamp": 2.0,
            "gst": 3.0,
            "exchange": 1.0,
            "tds": 0.5,
        },
        fees_paid=31.5,
        withdrawal_tds=10.0,
        realized_pnl=100.0,
        unrealized_pnl=-20.0,
        total_pnl=80.0,
        closed_round_trips=[{"realized_pnl": 40.0}, {"realized_pnl": 60.0}],
    )
    assert doc["total_taxes"] == 21.5  # trade taxes 11.5 + withdrawal 10
    assert doc["total_charges"] == 41.5
    assert doc["closed_round_trip_pnl"] == 100.0
    assert doc["total_pnl"] == 80.0
