"""Cash equity instrument pack — first autonomous learner path (IL.11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from atlas.investment.packs.base import OrderValidation
from atlas.trading.broker_profiles import FeeBreakdown
from atlas.trading.sessions import SessionStatus, session_status as equity_session_status


class CashEquityPack:
    """NSE/BSE cash equities — delegates session/fees to existing equity helpers."""

    id = "cash_equity"
    label = "Cash equities"
    ready = True
    asset_classes = ("cash_equity",)
    gap_detail = ""

    def accepts_asset_class(self, asset_class: str) -> bool:
        ac = (asset_class or "cash_equity").strip().lower().replace(" ", "_")
        return ac in self.asset_classes or ac in ("", "mixed")

    def session_status(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> SessionStatus:
        return equity_session_status(session_id, now=now, clock=clock)

    def validate_order(
        self,
        *,
        side: str,
        symbol: str,
        quantity: float,
        price: float,
        context: dict[str, Any] | None = None,
    ) -> OrderValidation:
        side_l = (side or "").strip().lower()
        if side_l not in ("buy", "sell"):
            return OrderValidation(ok=False, reason=f"unsupported side {side!r}")
        if quantity <= 0:
            return OrderValidation(ok=False, reason="quantity must be positive")
        if price <= 0:
            return OrderValidation(ok=False, reason="price must be positive")
        return OrderValidation(ok=True)

    def fee_overlay(
        self,
        breakdown: FeeBreakdown,
        *,
        side: str,
        symbol: str,
        quantity: float = 0.0,
        price: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> FeeBreakdown:
        # Equity Broker Profiles already encode STT/stamp; no extra overlay.
        return breakdown

    def default_broker_profile(self) -> str:
        return "paper_demo"


class EtfPack(CashEquityPack):
    """Thin overlay on cash equity — same fills, ETF asset_class accepted."""

    id = "etf"
    label = "Equity ETFs"
    ready = True
    asset_classes = ("etf", "cash_equity")
    gap_detail = ""

    def accepts_asset_class(self, asset_class: str) -> bool:
        ac = (asset_class or "etf").strip().lower().replace(" ", "_")
        return ac in self.asset_classes or ac in ("", "mixed")
