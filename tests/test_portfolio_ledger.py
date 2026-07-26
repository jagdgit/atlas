"""Broker Profiles + Portfolio Ledger (MI.6)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from atlas.trading.broker_profiles import (
    BUILTIN_BROKER_PROFILES,
    compute_fees,
    get_broker_profile,
)
from atlas.trading.ledger import PortfolioLedgerService
from atlas.trading.portfolio import PortfolioService
from atlas.workers.base import TickContext
from atlas.workers.portfolio_ledger import PortfolioLedgerWorker


class InMemorySimRepo:
    """Duck-typed stand-in for SimTradingRepository (no DB)."""

    def __init__(self) -> None:
        self.portfolios: dict[str, dict[str, Any]] = {}
        self.positions: dict[tuple[str, str], dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.cash_movements: list[dict[str, Any]] = []

    def ensure_portfolio(self, *, mission_id, name="default", base_currency="USD", starting_cash=0.0):
        for p in self.portfolios.values():
            if p["mission_id"] == (str(mission_id) if mission_id else None) and p["name"] == name:
                return dict(p)
        pid = str(uuid.uuid4())
        row = {
            "id": pid,
            "mission_id": str(mission_id) if mission_id else None,
            "name": name,
            "base_currency": base_currency,
            "starting_cash": float(starting_cash),
            "cash": float(starting_cash),
            "realized_pnl": 0.0,
            "metadata": {},
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
        row = {
            "portfolio_id": str(portfolio_id),
            "symbol": symbol,
            "quantity": float(quantity),
            "avg_price": float(avg_price),
        }
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

    def record_cash_movement(self, **kw):
        row = {"id": str(uuid.uuid4()), **kw}
        self.cash_movements.append(row)
        return dict(row)

    def list_cash_movements(self, portfolio_id, *, limit=50):
        return [
            dict(m) for m in self.cash_movements if m["portfolio_id"] == str(portfolio_id)
        ][:limit]


def test_builtin_profiles():
    assert "zerodha" in BUILTIN_BROKER_PROFILES
    assert "paper_demo" in BUILTIN_BROKER_PROFILES
    demo = get_broker_profile("paper_demo")
    assert demo.brokerage_flat == 0.0


def test_zerodha_fees_buy_vs_sell():
    profile = get_broker_profile("zerodha")
    buy = compute_fees(profile, side="buy", quantity=10, price=1000.0)
    sell = compute_fees(profile, side="sell", quantity=10, price=1000.0)
    assert buy.stamp > 0
    assert buy.stt == 0
    assert sell.stt > 0
    assert sell.stamp == 0
    assert sell.total > buy.total  # STT on sell
    assert buy.brokerage <= 20.0  # cap


def test_custom_profile():
    profile = get_broker_profile(
        None,
        custom={"id": "custom", "name": "Flat", "brokerage_flat": 5.0},
    )
    fees = compute_fees(profile, side="buy", quantity=1, price=100.0)
    assert fees.brokerage == 5.0
    assert fees.total >= 5.0


def test_ledger_apply_fill_charges_fee():
    portfolio = PortfolioService(InMemorySimRepo())
    ledger = PortfolioLedgerService(portfolio)
    p = ledger.ensure_portfolio(mission_id="m1", starting_cash=100_000.0)
    out = ledger.apply_fill(
        p["id"],
        symbol="RELIANCE.NS",
        side="buy",
        quantity=10,
        price=1000.0,
        broker_profile="zerodha",
        mission_id="m1",
    )
    assert out["fees"]["total"] > 0
    snap = portfolio.snapshot(p["id"])
    # cash = starting - notional - fees
    assert snap["cash"] < 100_000.0 - 10_000.0
    stmt = ledger.statement(p["id"], broker_profile="zerodha")
    assert stmt["fees_paid"] == pytest.approx(out["fees"]["total"])
    assert stmt["trade_count"] == 1


def test_portfolio_ledger_worker_idempotent():
    portfolio = PortfolioService(InMemorySimRepo())
    ledger = PortfolioLedgerService(portfolio)
    worker = PortfolioLedgerWorker(ledger=ledger)
    cfg = {
        "broker_profile": "zerodha",
        "starting_cash": 100_000.0,
        "pending_fills": [
            {"symbol": "DEMO", "side": "buy", "quantity": 5, "price": 100.0},
        ],
    }
    r1 = worker.do_tick(
        TickContext(worker_id="w", mission_id="m", config=cfg, config_version=1, state={})
    )
    assert "fills+=1" in r1.note
    r2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config=cfg,
            config_version=1,
            state=r1.state,
        )
    )
    assert "fills+=0" in r2.note
    assert r2.state["last_fees_paid"] > 0


def test_il7_fee_breakdown_includes_tds_field():
    profile = get_broker_profile(
        None,
        custom={
            "id": "edu",
            "name": "Edu",
            "brokerage_flat": 0.0,
            "tds_pct_sell": 0.01,
            "stt_pct_sell": 0.0,
        },
    )
    sell = compute_fees(profile, side="sell", quantity=10, price=100.0)
    assert sell.tds == pytest.approx(10.0)  # 1% of 1000
    assert "tds" in sell.as_dict()
    buy = compute_fees(profile, side="buy", quantity=10, price=100.0)
    assert buy.tds == 0.0


def test_il7_apply_fill_persists_fees_json():
    repo = InMemorySimRepo()
    portfolio = PortfolioService(repo)
    ledger = PortfolioLedgerService(portfolio)
    p = ledger.ensure_portfolio(mission_id="m1", starting_cash=100_000.0)
    out = ledger.apply_fill(
        p["id"],
        symbol="INFY.NS",
        side="buy",
        quantity=5,
        price=1500.0,
        broker_profile="zerodha",
        mission_id="m1",
    )
    trade = repo.trades[0]
    assert trade.get("fees", {}).get("total") == pytest.approx(out["fees"]["total"])
    assert trade["fees"]["stamp"] > 0
    stmt = ledger.statement(p["id"], broker_profile="zerodha")
    assert stmt["fee_components"]["stamp"] > 0
    assert stmt["version"] == "il.7"


def test_il7_withdraw_with_tds():
    repo = InMemorySimRepo()
    portfolio = PortfolioService(repo)
    ledger = PortfolioLedgerService(portfolio)
    p = ledger.ensure_portfolio(mission_id="m1", starting_cash=10_000.0, base_currency="INR")
    out = ledger.withdraw(
        p["id"],
        amount=1000.0,
        broker_profile="zerodha",
        tds_pct=0.10,
        note="take profit out",
        mission_id="m1",
    )
    assert out["tds"]["tds"] == pytest.approx(100.0)
    assert out["tds"]["total_debit"] == pytest.approx(1100.0)
    snap = portfolio.snapshot(p["id"])
    assert snap["cash"] == pytest.approx(8900.0)
    assert len(repo.cash_movements) == 1
    assert repo.cash_movements[0]["kind"] == "withdraw"
    stmt = ledger.statement(p["id"], broker_profile="zerodha")
    assert stmt["withdrawn"] == pytest.approx(1000.0)
    assert stmt["withdrawal_tds"] == pytest.approx(100.0)


def test_india_learner_uses_zerodha_profile():
    from atlas.missions.programs import india_equity_learner_overrides

    ov = india_equity_learner_overrides()
    assert ov["decision_simulation"]["broker_profile"] == "zerodha"
    assert ov["portfolio_ledger"]["broker_profile"] == "zerodha"
