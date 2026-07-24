"""Portfolio Ledger — fee/tax-aware simulation book (MI.6).

Promotes fee-aware fills as a library over :class:`~atlas.trading.portfolio.PortfolioService`
(Q2). Broker Profiles stay Market Program config.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from atlas.trading.broker_profiles import (
    BrokerProfile,
    compute_fees,
    get_broker_profile,
    list_broker_profiles,
)
from atlas.trading.portfolio import PortfolioService


class PortfolioLedgerService:
    """Fee-aware ledger façade over the virtual portfolio."""

    name = "portfolio_ledger"
    VERSION = "mi.6"

    def __init__(
        self,
        portfolio: PortfolioService,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._portfolio = portfolio
        self._logger = logger or logging.getLogger("atlas.trading.ledger")

    def list_profiles(self) -> list[dict[str, Any]]:
        return list_broker_profiles()

    def resolve_profile(
        self,
        profile_id: str | None = None,
        *,
        custom: dict[str, Any] | None = None,
    ) -> BrokerProfile:
        return get_broker_profile(profile_id, custom=custom)

    def ensure_portfolio(
        self,
        *,
        mission_id: UUID | str | None,
        name: str = "ledger",
        starting_cash: float = 100_000.0,
        base_currency: str = "INR",
    ) -> dict[str, Any]:
        return self._portfolio.ensure_portfolio(
            mission_id=mission_id,
            name=name,
            starting_cash=starting_cash,
            base_currency=base_currency,
        )

    def apply_fill(
        self,
        portfolio_id: UUID | str,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        broker_profile: str | None = "paper_demo",
        custom_profile: dict[str, Any] | None = None,
        mission_id: UUID | str | None = None,
        decision_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Apply a sim fill with Broker Profile fees included in ``fee``."""
        profile = self.resolve_profile(broker_profile, custom=custom_profile)
        breakdown = compute_fees(
            profile, side=side, quantity=quantity, price=price
        )
        trade = self._portfolio.apply_trade(
            portfolio_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            fee=float(breakdown.total),
            mission_id=mission_id,
            decision_id=decision_id,
        )
        return {
            "trade": trade,
            "fees": breakdown.as_dict(),
            "broker_profile": profile.as_dict(),
            "version": self.VERSION,
        }

    def statement(
        self,
        portfolio_id: UUID | str,
        *,
        prices: dict[str, float] | None = None,
        broker_profile: str | None = None,
    ) -> dict[str, Any]:
        """Operator-facing ledger snapshot + fee profile id."""
        snap = self._portfolio.snapshot(portfolio_id, prices=prices)
        trades = self._portfolio.trades(portfolio_id, limit=50)
        fees_paid = sum(float(t.get("fee") or 0.0) for t in trades)
        profile = self.resolve_profile(broker_profile) if broker_profile else None
        return {
            **snap,
            "fees_paid": round(fees_paid, 4),
            "trade_count": len(trades),
            "recent_trades": trades[:10],
            "broker_profile_id": profile.id if profile else None,
            "version": self.VERSION,
        }
