"""Stub instrument packs — operator-selected sim; not ready until rules wired (IL.11).

Futures/options moved to ``derivatives.py`` (ready). Commodity / FX / crypto remain stubs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from atlas.investment.packs.base import OrderValidation
from atlas.trading.broker_profiles import FeeBreakdown
from atlas.trading.sessions import SessionStatus


class StubInstrumentPack:
    """Shared stub: journals capability_gap; never silent fake fills."""

    id: str = "stub"
    label: str = "Stub"
    ready: bool = False
    asset_classes: tuple[str, ...] = ()
    gap_detail: str = "instrument pack rules not implemented"

    def accepts_asset_class(self, asset_class: str) -> bool:
        ac = (asset_class or "").strip().lower().replace(" ", "_")
        return ac in self.asset_classes or ac == "mixed"

    def session_status(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> SessionStatus:
        return SessionStatus(
            session_id=session_id or self.id,
            open=False,
            reason=f"instrument_pack:{self.id} not ready",
            local_now=None,
        )

    def validate_order(
        self,
        *,
        side: str,
        symbol: str,
        quantity: float,
        price: float,
        context: dict[str, Any] | None = None,
    ) -> OrderValidation:
        return OrderValidation(
            ok=False,
            reason=f"instrument_pack:{self.id} not ready — {self.gap_detail}",
            capability_gap=True,
        )

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
        return breakdown

    def default_broker_profile(self) -> str:
        return "paper_demo"


class CommodityPack(StubInstrumentPack):
    id = "commodity"
    label = "Commodities"
    asset_classes = ("commodity",)
    gap_detail = "Commodity session/lot rules not wired yet"


class CurrencyPack(StubInstrumentPack):
    id = "currency"
    label = "Currency / FX"
    asset_classes = ("currency", "fx")
    gap_detail = "FX pip/session rules not wired yet"


class CryptoPack(StubInstrumentPack):
    id = "crypto"
    label = "Crypto"
    asset_classes = ("crypto",)
    gap_detail = "Crypto pack not wired yet"
