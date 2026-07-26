"""Instrument pack protocol (IL.11) — rules overlay on the shared Simulation Engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from atlas.trading.broker_profiles import FeeBreakdown
from atlas.trading.sessions import SessionStatus


@dataclass(frozen=True)
class OrderValidation:
    """Result of pack-level order checks before a sim fill."""

    ok: bool
    reason: str = ""
    capability_gap: bool = False


class InstrumentPack(Protocol):
    """Domain rules for one asset class. Shared engine stays in paper_trading."""

    id: str
    label: str
    ready: bool
    asset_classes: tuple[str, ...]
    gap_detail: str

    def accepts_asset_class(self, asset_class: str) -> bool:
        """Whether an instrument row with this class may enter the tick."""
        ...

    def session_status(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> SessionStatus:
        ...

    def validate_order(
        self,
        *,
        side: str,
        symbol: str,
        quantity: float,
        price: float,
        context: dict[str, Any] | None = None,
    ) -> OrderValidation:
        ...

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
        ...

    def default_broker_profile(self) -> str:
        ...
