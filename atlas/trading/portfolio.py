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
        fees: dict[str, Any] | None = None,
        mission_id: UUID | str | None = None,
        decision_id: UUID | str | None = None,
        laboratory_id: str | None = None,
        instrument_path: str = "buy",
    ) -> dict[str, Any]:
        """Execute a simulated ``buy``/``sell`` fill; returns the recorded trade row.

        Buys add to the position (recomputing average cost) and debit cash; sells realize P&L
        against the average cost and credit cash. Raises :class:`PortfolioError` for an unknown
        portfolio, insufficient cash, or selling more than held (honesty over silent clamping).
        ``fees`` (IL.7) is an optional component breakdown persisted alongside scalar ``fee``.
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise PortfolioError(f"invalid side: {side!r}")
        if quantity <= 0:
            raise PortfolioError(f"quantity must be positive, got {quantity}")
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")

        # OI-LINT0: lab identity is immutable for a position's lifetime.
        # Sells of a contaminated name remain allowed (exit / flatten).
        if side == "buy":
            try:
                from atlas.investment.lab_contracts import (
                    is_instrument_permitted,
                    reject_message,
                )

                lid = str(
                    laboratory_id
                    or (portfolio.get("name") if isinstance(portfolio, dict) else "")
                    or ""
                ).strip()
                verdict = is_instrument_permitted(
                    lid, symbol, path=str(instrument_path or "buy")
                )
                if not verdict.allowed:
                    raise PortfolioError(reject_message(verdict))
            except PortfolioError:
                raise
            except Exception:  # noqa: BLE001
                self._logger.debug("lab contract check skipped", exc_info=True)

        cash = float(portfolio["cash"])
        position = self._repo.get_position(portfolio_id, symbol) or {"quantity": 0.0, "avg_price": 0.0}
        held = float(position["quantity"])
        avg = float(position["avg_price"])
        gross = float(quantity) * float(price)
        realized = 0.0
        index_proxy = False
        try:
            from atlas.investment.index_proxy_lot import (
                close_cash_credit,
                open_cash_debit,
                uses_index_proxy_collateral,
            )

            index_proxy = uses_index_proxy_collateral(symbol, quantity)
        except Exception:  # noqa: BLE001
            index_proxy = False

        if side == "buy":
            cost = (open_cash_debit(quantity, price) if index_proxy else gross) + fee
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
            if index_proxy:
                cash += close_cash_credit(quantity, avg, price) - fee
            else:
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
            fees=dict(fees or {}),
        )
        return trade

    def withdraw(
        self,
        portfolio_id: UUID | str,
        *,
        amount: float,
        tds: float = 0.0,
        fee: float = 0.0,
        note: str = "",
        mission_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """IL.7 — debit cash for a simulated withdrawal (principal + TDS + fee)."""
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")
        principal = float(amount)
        if principal <= 0:
            raise PortfolioError(f"withdrawal amount must be positive, got {amount}")
        tds_f = max(0.0, float(tds))
        fee_f = max(0.0, float(fee))
        total = principal + tds_f + fee_f
        cash = float(portfolio["cash"])
        if total > cash + 1e-9:
            raise PortfolioError(
                f"insufficient cash for withdrawal: need {total:.2f}, have {cash:.2f}"
            )
        cash -= total
        self._repo.update_portfolio_cash(portfolio_id, cash=cash, realized_pnl_delta=0.0)
        record = getattr(self._repo, "record_cash_movement", None)
        if record is None:
            return {
                "kind": "withdraw",
                "amount": -principal,
                "tds": tds_f,
                "fee": fee_f,
                "cash_after": cash,
                "note": note,
            }
        return record(
            portfolio_id=portfolio_id,
            mission_id=mission_id,
            kind="withdraw",
            amount=-principal,
            tds=tds_f,
            fee=fee_f,
            cash_after=cash,
            note=note or "sim withdrawal",
            metadata=metadata or {},
        )

    def deposit(
        self,
        portfolio_id: UUID | str,
        *,
        amount: float,
        note: str = "",
        mission_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """IL.7 — credit cash for a simulated deposit (no TDS)."""
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")
        principal = float(amount)
        if principal <= 0:
            raise PortfolioError(f"deposit amount must be positive, got {amount}")
        cash = float(portfolio["cash"]) + principal
        self._repo.update_portfolio_cash(portfolio_id, cash=cash, realized_pnl_delta=0.0)
        record = getattr(self._repo, "record_cash_movement", None)
        if record is None:
            return {
                "kind": "deposit",
                "amount": principal,
                "tds": 0.0,
                "fee": 0.0,
                "cash_after": cash,
                "note": note,
            }
        return record(
            portfolio_id=portfolio_id,
            mission_id=mission_id,
            kind="deposit",
            amount=principal,
            tds=0.0,
            fee=0.0,
            cash_after=cash,
            note=note or "sim deposit",
            metadata=metadata or {},
        )

    # --- reads / valuation ----------------------------------------------
    def position(self, portfolio_id: UUID | str, symbol: str) -> dict[str, Any] | None:
        return self._repo.get_position(portfolio_id, symbol)

    def snapshot(
        self, portfolio_id: UUID | str, *, prices: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """Portfolio valuation: cash + positions marked to ``prices`` → equity, P&L, exposure.

        OI-STAB0 P0.3: never silently claim market marks when avg-cost was used.
        Each position gets ``mark_source`` ∈ {market, avg_cost}; ``valuation_basis``
        summarizes the book honestly (including mixed).
        """
        portfolio = self._repo.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioError(f"no such portfolio: {portfolio_id}")
        prices = prices or {}
        positions = self._repo.list_positions(portfolio_id)
        holdings_value = 0.0
        unrealized = 0.0
        rows: list[dict[str, Any]] = []
        marked = 0
        missing: list[str] = []
        index_proxy_used = False
        for pos in positions:
            symbol = pos["symbol"]
            qty = float(pos["quantity"])
            avg = float(pos["avg_price"])
            if symbol in prices and prices.get(symbol) is not None:
                try:
                    mark = float(prices[symbol])
                    mark_source = "market"
                    marked += 1
                except (TypeError, ValueError):
                    mark = avg
                    mark_source = "avg_cost"
                    missing.append(symbol)
            else:
                mark = avg
                mark_source = "avg_cost"
                missing.append(symbol)
            value = qty * mark
            pnl = (mark - avg) * qty
            try:
                from atlas.investment.index_proxy_lot import (
                    position_lab_value,
                    uses_index_proxy_collateral,
                )

                if uses_index_proxy_collateral(symbol, qty):
                    value, pnl = position_lab_value(qty, avg, mark)
                    index_proxy_used = True
            except Exception:  # noqa: BLE001
                pass
            holdings_value += value
            unrealized += pnl
            rows.append(
                {
                    "symbol": symbol,
                    "quantity": qty,
                    "avg_price": avg,
                    "mark": mark,
                    "mark_source": mark_source,
                    "value": value,
                    "unrealized_pnl": pnl,
                }
            )
        n_pos = len(rows)
        if n_pos == 0:
            valuation_basis = "no_open_positions"
            marks_pct = 100.0
        elif index_proxy_used:
            from atlas.investment.index_proxy_lot import VALUATION_BASIS

            marks_pct = 100.0 if marked == n_pos else round(100.0 * marked / n_pos, 1)
            if marked == 0:
                valuation_basis = f"{VALUATION_BASIS} (average cost — market marks unavailable)"
            elif marked < n_pos:
                valuation_basis = f"{VALUATION_BASIS} (mixed {marked}/{n_pos} market)"
            else:
                valuation_basis = VALUATION_BASIS
        elif marked == n_pos:
            valuation_basis = "latest daily market bars"
            marks_pct = 100.0
        elif marked == 0:
            valuation_basis = "average cost (market marks unavailable)"
            marks_pct = 0.0
        else:
            valuation_basis = (
                f"mixed ({marked}/{n_pos} market, rest avg cost)"
            )
            marks_pct = round(100.0 * marked / n_pos, 1)
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
            "valuation_basis": valuation_basis,
            "marks_available": marked,
            "marks_total": n_pos,
            "marks_pct": marks_pct,
            "marks_missing_symbols": missing[:40],
        }

    def trades(self, portfolio_id: UUID | str, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repo.list_trades(portfolio_id, limit=limit)
