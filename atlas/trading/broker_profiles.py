"""Broker Profiles — Market Program fee/tax schedules (MI.6 / Q4 / MI7).

Domain config only (not a platform OS). Profiles approximate India equity costs
for **simulation**; never place real broker orders (P10). Numbers are simplified
for learning — operators can override via ``custom`` profile fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrokerProfile:
    """Fee/tax schedule applied to simulated fills."""

    id: str
    name: str
    brokerage_pct: float = 0.0  # of turnover
    brokerage_flat: float = 0.0
    brokerage_cap: float | None = None  # max brokerage per order
    stt_pct_sell: float = 0.0  # securities transaction tax (sells)
    exchange_pct: float = 0.0  # exchange txn charges
    gst_pct: float = 0.0  # GST on (brokerage + exchange)
    stamp_pct_buy: float = 0.0  # stamp duty on buys
    currency: str = "INR"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Built-in profiles (Market Program). Caps/rates are illustrative sim defaults.
BUILTIN_BROKER_PROFILES: dict[str, BrokerProfile] = {
    "paper_demo": BrokerProfile(
        id="paper_demo",
        name="Paper Demo",
        brokerage_flat=0.0,
        currency="USD",
        metadata={"note": "zero-cost sim for fixtures"},
    ),
    "zerodha": BrokerProfile(
        id="zerodha",
        name="Zerodha (sim approx)",
        brokerage_pct=0.0003,  # 0.03%
        brokerage_cap=20.0,
        stt_pct_sell=0.001,  # 0.1% on sell
        exchange_pct=0.0000325,
        gst_pct=0.18,
        stamp_pct_buy=0.00015,
        currency="INR",
    ),
    "groww": BrokerProfile(
        id="groww",
        name="Groww (sim approx)",
        brokerage_pct=0.0,
        brokerage_flat=20.0,  # simplified flat delivery brokerage
        brokerage_cap=20.0,
        stt_pct_sell=0.001,
        exchange_pct=0.0000325,
        gst_pct=0.18,
        stamp_pct_buy=0.00015,
        currency="INR",
    ),
    "angel": BrokerProfile(
        id="angel",
        name="Angel One (sim approx)",
        brokerage_pct=0.0003,
        brokerage_cap=20.0,
        stt_pct_sell=0.001,
        exchange_pct=0.0000325,
        gst_pct=0.18,
        stamp_pct_buy=0.00015,
        currency="INR",
    ),
}


def get_broker_profile(
    profile_id: str | None,
    *,
    custom: dict[str, Any] | None = None,
) -> BrokerProfile:
    """Resolve a built-in or custom Broker Profile."""
    if custom:
        base = BUILTIN_BROKER_PROFILES.get(
            str(custom.get("id") or "custom"),
            BrokerProfile(id="custom", name="Custom"),
        )
        data = {**base.as_dict(), **{k: v for k, v in custom.items() if v is not None}}
        return BrokerProfile(
            id=str(data.get("id") or "custom"),
            name=str(data.get("name") or "Custom"),
            brokerage_pct=float(data.get("brokerage_pct") or 0.0),
            brokerage_flat=float(data.get("brokerage_flat") or 0.0),
            brokerage_cap=(
                float(data["brokerage_cap"])
                if data.get("brokerage_cap") is not None
                else None
            ),
            stt_pct_sell=float(data.get("stt_pct_sell") or 0.0),
            exchange_pct=float(data.get("exchange_pct") or 0.0),
            gst_pct=float(data.get("gst_pct") or 0.0),
            stamp_pct_buy=float(data.get("stamp_pct_buy") or 0.0),
            currency=str(data.get("currency") or "INR"),
            metadata=dict(data.get("metadata") or {}),
        )
    key = (profile_id or "paper_demo").strip().lower()
    if key in BUILTIN_BROKER_PROFILES:
        return BUILTIN_BROKER_PROFILES[key]
    # Unknown id → paper_demo with note (honest default, not fabricated broker)
    return BrokerProfile(
        id=key,
        name=f"Unknown ({key}) → paper_demo fees",
        metadata={"fallback": "paper_demo"},
    )


def list_broker_profiles() -> list[dict[str, Any]]:
    return [p.as_dict() for p in BUILTIN_BROKER_PROFILES.values()]


@dataclass(frozen=True)
class FeeBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange: float
    gst: float
    stamp: float
    total: float
    profile_id: str
    side: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_fees(
    profile: BrokerProfile,
    *,
    side: str,
    quantity: float,
    price: float,
) -> FeeBreakdown:
    """Compute all-in sim fees for one fill (buy or sell)."""
    side_l = side.lower()
    qty = float(quantity)
    px = float(price)
    turnover = abs(qty * px)
    brokerage = turnover * float(profile.brokerage_pct) + float(profile.brokerage_flat)
    if profile.brokerage_cap is not None:
        brokerage = min(brokerage, float(profile.brokerage_cap))
    # If only flat and pct are zero, brokerage stays 0.
    exchange = turnover * float(profile.exchange_pct)
    gst = (brokerage + exchange) * float(profile.gst_pct)
    stt = turnover * float(profile.stt_pct_sell) if side_l == "sell" else 0.0
    stamp = turnover * float(profile.stamp_pct_buy) if side_l == "buy" else 0.0
    total = brokerage + stt + exchange + gst + stamp
    return FeeBreakdown(
        turnover=turnover,
        brokerage=round(brokerage, 4),
        stt=round(stt, 4),
        exchange=round(exchange, 4),
        gst=round(gst, 4),
        stamp=round(stamp, 4),
        total=round(total, 4),
        profile_id=profile.id,
        side=side_l,
    )
