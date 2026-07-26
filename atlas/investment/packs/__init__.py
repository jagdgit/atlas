"""Simulation Engine instrument packs (IL.11).

Shared Decision Simulation engine + per-class rules. Cash equity, ETF, futures,
and options are ready; commodity/FX/crypto stubs raise capability gaps
(never silent fake fills).
"""

from __future__ import annotations

from typing import Any

from atlas.investment.packs.base import InstrumentPack, OrderValidation
from atlas.investment.packs.cash_equity import CashEquityPack, EtfPack
from atlas.investment.packs.derivatives import FuturesPack, OptionsPack
from atlas.investment.packs.stubs import (
    CommodityPack,
    CryptoPack,
    CurrencyPack,
)

_PACKS: dict[str, InstrumentPack] = {
    "cash_equity": CashEquityPack(),
    "etf": EtfPack(),
    "futures": FuturesPack(),
    "options": OptionsPack(),
    "commodity": CommodityPack(),
    "currency": CurrencyPack(),
    "fx": CurrencyPack(),  # alias
    "crypto": CryptoPack(),
}

# Normalize operator synonyms → pack id
_ALIASES: dict[str, str] = {
    "equity": "cash_equity",
    "cash": "cash_equity",
    "stocks": "cash_equity",
    "stock": "cash_equity",
    "fno": "futures",
    "f&o": "futures",
    "forex": "currency",
    "fx": "currency",
}


def normalize_pack_id(raw: str | None) -> str:
    key = (raw or "cash_equity").strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key) or "cash_equity"


class _UnknownPack:
    ready = False

    def __init__(self, pack_id: str) -> None:
        self.id = pack_id or "unknown"
        self.label = f"Unknown ({self.id})"
        self.asset_classes = (self.id,)
        self.gap_detail = f"unknown instrument_pack {self.id!r}"

    def accepts_asset_class(self, asset_class: str) -> bool:
        return False

    def session_status(self, session_id: str, *, now=None, clock=None):
        from atlas.trading.sessions import SessionStatus

        return SessionStatus(
            session_id=session_id or self.id,
            open=False,
            reason=self.gap_detail,
        )

    def validate_order(self, *, side, symbol, quantity, price, context=None) -> OrderValidation:
        return OrderValidation(
            ok=False,
            reason=self.gap_detail,
            capability_gap=True,
        )

    def fee_overlay(self, breakdown, *, side, symbol, quantity=0.0, price=0.0, context=None):
        return breakdown

    def default_broker_profile(self) -> str:
        return "paper_demo"


def resolve_pack(
    pack_or_class: str | None = None,
    *,
    asset_class: str | None = None,
    allowed_assets: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> InstrumentPack:
    """Resolve an instrument pack for a Decision Simulation book.

    Precedence: explicit ``instrument_pack`` / ``pack_or_class`` → ``asset_class``
    → first ``allowed_assets`` entry → ``cash_equity``.
    """
    cfg = config or {}
    explicit = pack_or_class or cfg.get("instrument_pack") or cfg.get("pack")
    if not explicit:
        explicit = asset_class or cfg.get("asset_class")
    if not explicit and allowed_assets:
        explicit = allowed_assets[0]
    if not explicit:
        persona = cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}
        assets = persona.get("allowed_assets") if isinstance(persona, dict) else None
        if isinstance(assets, list) and assets:
            explicit = assets[0]
    pack_id = normalize_pack_id(str(explicit) if explicit else "cash_equity")
    return resolve_pack_or_unknown(pack_id)


def resolve_pack_or_unknown(pack_id: str | None) -> InstrumentPack:
    """Like resolve_pack but unknown ids get an honest not-ready stub."""
    key = normalize_pack_id(pack_id)
    if key in _PACKS:
        return _PACKS[key]
    return _UnknownPack(key)


def list_packs() -> list[dict[str, Any]]:
    """Operator-facing pack catalogue (dedupe fx/currency)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for key, pack in _PACKS.items():
        if pack.id in seen:
            continue
        seen.add(pack.id)
        aliases = [k for k, v in _ALIASES.items() if v == pack.id]
        if pack.id == "currency":
            aliases = sorted(set(aliases + ["fx"]))
        out.append(
            {
                "id": pack.id,
                "label": pack.label,
                "ready": pack.ready,
                "asset_classes": list(pack.asset_classes),
                "gap_detail": pack.gap_detail,
                "aliases": aliases,
            }
        )
    return out


def pack_capability_need(pack: InstrumentPack) -> str:
    return f"instrument_pack:{pack.id}"


__all__ = [
    "InstrumentPack",
    "OrderValidation",
    "list_packs",
    "normalize_pack_id",
    "pack_capability_need",
    "resolve_pack",
    "resolve_pack_or_unknown",
]
