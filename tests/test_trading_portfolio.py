"""Hermetic tests for the virtual PortfolioService (Phase D · §D.6, P10 — simulation only).

An in-memory fake of the sim repo exercises the money math: buys debit cash + recompute average
cost, sells realize P&L against cost + credit cash, positions close out to zero, and guards reject
insufficient cash / overselling (honesty over silent clamping). Mark-to-market snapshot reports
equity, exposure, and total return.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from atlas.trading.portfolio import PortfolioError, PortfolioService


class InMemorySimRepo:
    """Duck-typed stand-in for SimTradingRepository (no DB)."""

    def __init__(self) -> None:
        self.portfolios: dict[str, dict[str, Any]] = {}
        self.positions: dict[tuple[str, str], dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []

    def ensure_portfolio(self, *, mission_id, name="default", base_currency="USD", starting_cash=0.0):
        for p in self.portfolios.values():
            if p["mission_id"] == (str(mission_id) if mission_id else None) and p["name"] == name:
                return dict(p)
        pid = str(uuid.uuid4())
        row = {
            "id": pid, "mission_id": str(mission_id) if mission_id else None, "name": name,
            "base_currency": base_currency, "starting_cash": float(starting_cash),
            "cash": float(starting_cash), "realized_pnl": 0.0, "metadata": {},
        }
        self.portfolios[pid] = row
        return dict(row)

    def get_portfolio(self, portfolio_id):
        row = self.portfolios.get(str(portfolio_id))
        return dict(row) if row else None

    def update_portfolio_cash(self, portfolio_id, *, cash, realized_pnl_delta=0.0):
        row = self.portfolios[str(portfolio_id)]
        row["cash"] = float(cash)
        row["realized_pnl"] += float(realized_pnl_delta)
        return dict(row)

    def get_position(self, portfolio_id, symbol):
        row = self.positions.get((str(portfolio_id), symbol))
        return dict(row) if row else None

    def list_positions(self, portfolio_id):
        return [dict(v) for (pid, _), v in self.positions.items() if pid == str(portfolio_id)]

    def upsert_position(self, portfolio_id, symbol, *, quantity, avg_price):
        row = {"portfolio_id": str(portfolio_id), "symbol": symbol,
               "quantity": float(quantity), "avg_price": float(avg_price)}
        self.positions[(str(portfolio_id), symbol)] = row
        return dict(row)

    def delete_position(self, portfolio_id, symbol):
        return 1 if self.positions.pop((str(portfolio_id), symbol), None) else 0

    def record_trade(self, **kw):
        row = {"id": str(uuid.uuid4()), **kw}
        self.trades.append(row)
        return dict(row)

    def list_trades(self, portfolio_id, *, limit=200):
        return [dict(t) for t in self.trades if t["portfolio_id"] == str(portfolio_id)][:limit]

    def count_trades(self, portfolio_id):
        return sum(1 for t in self.trades if t["portfolio_id"] == str(portfolio_id))


@pytest.fixture()
def svc():
    return PortfolioService(InMemorySimRepo())


def test_buy_debits_cash_and_sets_avg_cost(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1000.0)
    svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=10, price=20.0)
    pos = svc.position(p["id"], "ACME")
    assert pos["quantity"] == 10
    assert pos["avg_price"] == 20.0
    snap = svc.snapshot(p["id"], prices={"ACME": 20.0})
    assert snap["cash"] == 800.0
    assert snap["equity"] == 1000.0  # cash 800 + holdings 200


def test_average_cost_across_two_buys(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=10000.0)
    svc.apply_trade(p["id"], symbol="X", side="buy", quantity=10, price=10.0)
    svc.apply_trade(p["id"], symbol="X", side="buy", quantity=10, price=20.0)
    pos = svc.position(p["id"], "X")
    assert pos["quantity"] == 20
    assert pos["avg_price"] == 15.0  # (100 + 200) / 20


def test_sell_realizes_pnl_and_closes_position(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1000.0)
    svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=10, price=20.0)
    trade = svc.apply_trade(p["id"], symbol="ACME", side="sell", quantity=10, price=25.0)
    assert trade["realized_pnl"] == pytest.approx(50.0)  # (25-20)*10
    assert svc.position(p["id"], "ACME") is None  # fully closed
    snap = svc.snapshot(p["id"])
    assert snap["cash"] == pytest.approx(1050.0)
    assert snap["realized_pnl"] == pytest.approx(50.0)


def test_insufficient_cash_rejected(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=100.0)
    with pytest.raises(PortfolioError):
        svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=10, price=20.0)


def test_oversell_rejected(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1000.0)
    svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=5, price=20.0)
    with pytest.raises(PortfolioError):
        svc.apply_trade(p["id"], symbol="ACME", side="sell", quantity=10, price=25.0)


def test_snapshot_total_return_and_unrealized(svc):
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1000.0)
    svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=10, price=20.0)
    snap = svc.snapshot(p["id"], prices={"ACME": 30.0})
    assert snap["unrealized_pnl"] == pytest.approx(100.0)  # (30-20)*10
    assert snap["equity"] == pytest.approx(1100.0)         # cash 800 + holdings 300
    assert snap["total_return"] == pytest.approx(0.1)
