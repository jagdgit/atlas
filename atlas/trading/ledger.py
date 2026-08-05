"""Portfolio Ledger — fee/tax-aware simulation book (MI.6 / IL.7).

Promotes fee-aware fills as a library over :class:`~atlas.trading.portfolio.PortfolioService`
(Q2). Broker Profiles stay Market Program config. IL.7 adds TDS line items, persisted fee
breakdowns, and withdrawal / deposit cash movements.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from atlas.trading.broker_profiles import (
    BrokerProfile,
    compute_fees,
    compute_withdrawal_tds,
    get_broker_profile,
    list_broker_profiles,
)
from atlas.trading.portfolio import PortfolioService


class PortfolioLedgerService:
    """Fee-aware ledger façade over the virtual portfolio."""

    name = "portfolio_ledger"
    VERSION = "il.7"

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
        """Apply a sim fill with Broker Profile fees included in ``fee`` + ``fees`` JSON."""
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
            fees=breakdown.as_dict(),
            mission_id=mission_id,
            decision_id=decision_id,
        )
        return {
            "trade": trade,
            "fees": breakdown.as_dict(),
            "broker_profile": profile.as_dict(),
            "version": self.VERSION,
        }

    def withdraw(
        self,
        portfolio_id: UUID | str,
        *,
        amount: float,
        broker_profile: str | None = "paper_demo",
        tds_pct: float | None = None,
        note: str = "",
        mission_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """IL.7 — simulate withdrawing cash (optional TDS withholding)."""
        profile = self.resolve_profile(broker_profile)
        tax = compute_withdrawal_tds(profile, amount=amount, tds_pct=tds_pct)
        movement = self._portfolio.withdraw(
            portfolio_id,
            amount=tax["principal"],
            tds=tax["tds"],
            fee=0.0,
            note=note or "sim withdrawal",
            mission_id=mission_id,
            metadata={
                "broker_profile": profile.id,
                "tds_pct": tax["tds_pct"],
                "net_to_operator": tax["net_to_operator"],
            },
        )
        return {
            "movement": movement,
            "tds": tax,
            "broker_profile": profile.as_dict(),
            "version": self.VERSION,
        }

    def deposit(
        self,
        portfolio_id: UUID | str,
        *,
        amount: float,
        note: str = "",
        mission_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """IL.7 — simulate depositing cash into the book."""
        movement = self._portfolio.deposit(
            portfolio_id,
            amount=amount,
            note=note or "sim deposit",
            mission_id=mission_id,
        )
        return {"movement": movement, "version": self.VERSION}

    def statement(
        self,
        portfolio_id: UUID | str,
        *,
        prices: dict[str, float] | None = None,
        broker_profile: str | None = None,
    ) -> dict[str, Any]:
        """Operator-facing ledger snapshot + fee/TDS rollups + recent movements."""
        snap = self._portfolio.snapshot(portfolio_id, prices=prices)
        trades = self._portfolio.trades(portfolio_id, limit=50)
        fees_paid = sum(float(t.get("fee") or 0.0) for t in trades)
        components = {
            "brokerage": 0.0,
            "stt": 0.0,
            "exchange": 0.0,
            "gst": 0.0,
            "stamp": 0.0,
            "tds": 0.0,
        }
        for t in trades:
            fees = t.get("fees") if isinstance(t.get("fees"), dict) else {}
            for k in components:
                try:
                    components[k] += float(fees.get(k) or 0.0)
                except (TypeError, ValueError):
                    continue
        for k in components:
            components[k] = round(components[k], 4)

        movements: list[dict[str, Any]] = []
        list_mv = getattr(self._portfolio._repo, "list_cash_movements", None)
        if callable(list_mv):
            try:
                # Cash-flow-adjusted returns need the full movement history, not
                # only the latest page. The response still exposes just 10 rows.
                movements = list_mv(portfolio_id, limit=10_000)
            except Exception:  # noqa: BLE001
                movements = []
        withdrawn = sum(
            abs(float(m.get("amount") or 0.0))
            for m in movements
            if str(m.get("kind") or "") == "withdraw"
        )
        deposited = sum(
            float(m.get("amount") or 0.0)
            for m in movements
            if str(m.get("kind") or "") == "deposit"
        )
        withdrawal_tds = sum(
            float(m.get("tds") or 0.0)
            for m in movements
            if str(m.get("kind") or "") == "withdraw"
        )
        profile = self.resolve_profile(broker_profile) if broker_profile else None
        return {
            **snap,
            "fees_paid": round(fees_paid, 4),
            "fee_components": components,
            "trade_count": len(trades),
            "recent_trades": trades[:10],
            "cash_movements": movements[:10],
            "deposited": round(deposited, 4),
            "withdrawn": round(withdrawn, 4),
            "withdrawal_tds": round(withdrawal_tds, 4),
            "broker_profile_id": profile.id if profile else None,
            "version": self.VERSION,
        }
