"""Virtual portfolio service (Phase D · §D.6, BB-D7 / P10) — simulation only.

Applies Decision-Engine trade decisions to a *virtual* account: cash, positions (average-cost
basis), and an append-only blotter, computing realized P&L on sells and unrealized P&L on
mark-to-market. There is **no broker and no real money** (P10) — a simulated fill changes nothing in
the world, so applies flow freely without the approval gate (DD3). Every fill links back to the
decision that caused it (P9), so the blotter is fully auditable.

Long-only, whole-and-fractional quantities, flat fees. Deterministic: the same decisions on the same
prices always yield the same portfolio (Q7).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from atlas.exceptions.base import AtlasError


class PortfolioError(AtlasError):
    """An invalid simulated trade (unknown portfolio, insufficient cash/shares)."""


class PortfolioService:
    name = "sim_portfolio"
    VERSION = "1.0.0"

    def __init__(self, repo: Any, *, logger: logging.Logger | None = None) -> None:
        self._repo = repo
        self._logger = logger or logging.getLogger("atlas.trading.portfolio")

    # --- accounts -------------------------------------------------------
    def ensure_portfolio(
        self,
        *,
        mission_id: UUID | str | None,
        name: str = "default",
        starting_cash: float = 100_000.0,
        base_currency: str = "USD",
    ) -> dict[str, Any]:
        return self._repo.ensure_portfolio(
            mission_id=mission_id,
            name=name,
            base_currency=base_currency,
            starting_cash=float(starting_cash),
        )

    # --- applying decisions ---------------------------------------------
    def apply_trade(
        self,
        portfolio_id: UUID | str,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        mission_id: UUID | str | None = None,
        decision_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Execute a simulated ``buy``/``sell`` fill; returns the recorded trade row.

        Buys add to the position (recomputing average cost) and debit cash; sells realize P&L
        against the average cost and credit cash. Raises :class:`PortfolioError` for an unknown
        portfolio, insufficient cash, or selling more than held (honesty over silent clamping).
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise PortfolioError(f"invalid side: {side!r}")
        if quantity <= 0:
            raise PortfolioError(f"quantity must be positive, got {quantity}")
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")

        cash = float(portfolio["cash"])
        position = self._repo.get_position(portfolio_id, symbol) or {"quantity": 0.0, "avg_price": 0.0}
        held = float(position["quantity"])
        avg = float(position["avg_price"])
        gross = float(quantity) * float(price)
        realized = 0.0

        if side == "buy":
            cost = gross + fee
            if cost > cash + 1e-9:
                raise PortfolioError(
                    f"insufficient cash for buy {quantity} {symbol} @ {price}: "
                    f"need {cost:.2f}, have {cash:.2f}"
                )
            new_qty = held + quantity
            new_avg = ((held * avg) + gross) / new_qty if new_qty > 0 else 0.0
            cash -= cost
            self._repo.upsert_position(portfolio_id, symbol, quantity=new_qty, avg_price=new_avg)
        else:  # sell
            if quantity > held + 1e-9:
                raise PortfolioError(
                    f"cannot sell {quantity} {symbol}: only {held} held"
                )
            realized = (float(price) - avg) * quantity - fee
            cash += gross - fee
            new_qty = held - quantity
            if new_qty <= 1e-9:
                self._repo.delete_position(portfolio_id, symbol)
            else:
                self._repo.upsert_position(portfolio_id, symbol, quantity=new_qty, avg_price=avg)

        self._repo.update_portfolio_cash(portfolio_id, cash=cash, realized_pnl_delta=realized)
        trade = self._repo.record_trade(
            portfolio_id=portfolio_id,
            mission_id=mission_id,
            decision_id=decision_id,
            symbol=symbol,
            side=side,
            quantity=float(quantity),
            price=float(price),
            fee=float(fee),
            cash_after=cash,
            realized_pnl=realized,
        )
        return trade

    # --- reads / valuation ----------------------------------------------
    def position(self, portfolio_id: UUID | str, symbol: str) -> dict[str, Any] | None:
        return self._repo.get_position(portfolio_id, symbol)

    def snapshot(
        self, portfolio_id: UUID | str, *, prices: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """Portfolio valuation: cash + positions marked to ``prices`` → equity, P&L, exposure."""
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")
        prices = prices or {}
        positions = self._repo.list_positions(portfolio_id)
        holdings_value = 0.0
        unrealized = 0.0
        rows: list[dict[str, Any]] = []
        for pos in positions:
            symbol = pos["symbol"]
            qty = float(pos["quantity"])
            avg = float(pos["avg_price"])
            mark = float(prices.get(symbol, avg))
            value = qty * mark
            pnl = (mark - avg) * qty
            holdings_value += value
            unrealized += pnl
            rows.append(
                {"symbol": symbol, "quantity": qty, "avg_price": avg, "mark": mark,
                 "value": value, "unrealized_pnl": pnl}
            )
        cash = float(portfolio["cash"])
        starting = float(portfolio["starting_cash"])
        equity = cash + holdings_value
        return {
            "portfolio_id": str(portfolio["id"]),
            "cash": cash,
            "starting_cash": starting,
            "holdings_value": holdings_value,
            "equity": equity,
            "realized_pnl": float(portfolio["realized_pnl"]),
            "unrealized_pnl": unrealized,
            "total_return": (equity - starting) / starting if starting > 0 else 0.0,
            "positions": rows,
        }

    def trades(self, portfolio_id: UUID | str, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repo.list_trades(portfolio_id, limit=limit)
