"""Futures & options instrument packs — ready for operator-selected sim (IL.11 follow-on).

Illustrative NSE F&O rules for Decision Simulation only (P10). Not live contract
specs, and **not** autonomous F&O ranking (IL-Q7). Commodity/FX/crypto stay stubs.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable

from atlas.investment.packs.base import OrderValidation
from atlas.trading.broker_profiles import FeeBreakdown
from atlas.trading.sessions import SessionStatus, session_status as market_session_status

# Illustrative default lot sizes (units per lot) — operators override via instrument/config.
_DEFAULT_LOTS: dict[str, int] = {
    "NIFTY": 25,
    "NIFTY50": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 50,
}

# F&O fee overlays (sim approx; equity Broker Profiles still supply brokerage skeleton).
_FUT_STT_SELL = 0.0002  # ~0.02% on futures sell turnover
_OPT_STT_SELL = 0.0005  # ~0.05% on options sell (premium) — illustrative
_DEFAULT_MARGIN = 0.12  # ~12% of notional for futures / option writes
_OPT_WRITE_MARGIN = 0.20


def _sym_key(symbol: str) -> str:
    raw = (symbol or "").strip().upper()
    for sep in ("-", "_", " "):
        if sep in raw:
            raw = raw.split(sep)[0]
            break
    return raw.replace(".NS", "").replace(".BO", "")


def default_lot_size(symbol: str, context: dict[str, Any] | None = None) -> int:
    """Resolve lot size: instrument → config → symbol heuristic → 1."""
    ctx = context or {}
    for key in ("lot_size", "contract_size"):
        if ctx.get(key) is not None:
            try:
                n = int(float(ctx[key]))
                if n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    inst = ctx.get("instrument") if isinstance(ctx.get("instrument"), dict) else {}
    for key in ("lot_size", "contract_size"):
        if inst.get(key) is not None:
            try:
                n = int(float(inst[key]))
                if n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    return int(_DEFAULT_LOTS.get(_sym_key(symbol), 1))


def _margin_fraction(context: dict[str, Any] | None, *, writing: bool = False) -> float:
    ctx = context or {}
    key = "write_margin_fraction" if writing else "margin_fraction"
    raw = ctx.get(key)
    if raw is None and isinstance(ctx.get("instrument"), dict):
        raw = ctx["instrument"].get(key)
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return _OPT_WRITE_MARGIN if writing else _DEFAULT_MARGIN


def _parse_expiry(context: dict[str, Any] | None) -> date | None:
    ctx = context or {}
    raw = ctx.get("expiry") or ctx.get("expiry_date")
    if raw is None and isinstance(ctx.get("instrument"), dict):
        inst = ctx["instrument"]
        raw = inst.get("expiry") or inst.get("expiry_date")
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _expiry_block(context: dict[str, Any] | None) -> OrderValidation | None:
    exp = _parse_expiry(context)
    if exp is None:
        return None
    today = datetime.now(timezone.utc).date()
    if exp < today:
        return OrderValidation(
            ok=False,
            reason=f"contract expired on {exp.isoformat()} (sim expiry gate)",
        )
    return None


def _fno_session(
    session_id: str,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SessionStatus:
    key = (session_id or "nse_fno").strip().lower()
    # Map legacy / equity session ids; F&O hours match cash equity on NSE.
    if key in ("", "futures", "options", "fno", "nse_fo"):
        key = "nse_fno"
    return market_session_status(key, now=now, clock=clock)


def _recompute_fees(
    breakdown: FeeBreakdown,
    *,
    side: str,
    quantity: float,
    price: float,
    lot_size: int,
    stt_pct_sell: float,
) -> FeeBreakdown:
    """Rebuild fee lines on contract notional; drop equity stamp on F&O."""
    side_l = (side or breakdown.side or "").strip().lower()
    turnover = abs(float(quantity) * float(price))  # qty already in units
    if turnover <= 0 and lot_size > 1:
        # If caller passed lots-only qty somehow, scale — defensive only.
        turnover = abs(float(quantity) * float(lot_size) * float(price))
    # Preserve brokerage/exchange/gst ratios from equity profile when turnover matches;
    # otherwise scale from original breakdown turnover.
    base_to = float(breakdown.turnover) or 1.0
    scale = turnover / base_to if base_to > 0 else 1.0
    brokerage = round(float(breakdown.brokerage) * scale, 4)
    exchange = round(float(breakdown.exchange) * scale, 4)
    gst = round(float(breakdown.gst) * scale, 4)
    stt = round(turnover * stt_pct_sell, 4) if side_l == "sell" else 0.0
    stamp = 0.0  # F&O: no equity stamp duty in this approx
    tds = 0.0
    total = round(brokerage + stt + exchange + gst + stamp + tds, 4)
    return FeeBreakdown(
        turnover=round(turnover, 4),
        brokerage=brokerage,
        stt=stt,
        exchange=exchange,
        gst=gst,
        stamp=stamp,
        tds=tds,
        total=total,
        profile_id=breakdown.profile_id,
        side=side_l,
    )


class FuturesPack:
    """Index/stock futures — lot multiples, margin gate, F&O fee overlay."""

    id = "futures"
    label = "Futures"
    ready = True
    asset_classes = ("futures",)
    gap_detail = ""

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
        return _fno_session(session_id, now=now, clock=clock)

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
        expired = _expiry_block(context)
        if expired is not None:
            return expired

        lot = default_lot_size(symbol, context)
        # Quantity is in underlying units; must be a whole multiple of lot size.
        qty_i = int(round(float(quantity)))
        if abs(float(quantity) - qty_i) > 1e-6:
            return OrderValidation(
                ok=False,
                reason=f"futures quantity must be a whole number of units (got {quantity})",
            )
        if qty_i % lot != 0:
            return OrderValidation(
                ok=False,
                reason=f"futures quantity {qty_i} must be a multiple of lot_size={lot}",
            )

        held = float((context or {}).get("position_qty") or 0.0)
        if side_l == "sell":
            closing = held > 0 and qty_i <= held + 1e-9
        else:
            closing = held < 0 and qty_i <= abs(held) + 1e-9
        if not closing:
            margin_pct = _margin_fraction(context, writing=False)
            notional = qty_i * float(price)
            required = notional * margin_pct
            cash = float((context or {}).get("cash") or 0.0)
            if required > 0 and cash + 1e-6 < required:
                return OrderValidation(
                    ok=False,
                    reason=(
                        f"insufficient margin: need ~{required:.2f} "
                        f"({margin_pct:.0%} of notional {notional:.2f}); cash={cash:.2f}"
                    ),
                )
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
        lot = default_lot_size(symbol, context)
        qty = float(quantity) if quantity else 0.0
        px = float(price) if price else 0.0
        if qty <= 0 or px <= 0:
            # Fall back: adjust STT only on existing turnover.
            side_l = (side or breakdown.side or "").strip().lower()
            stt = (
                round(float(breakdown.turnover) * _FUT_STT_SELL, 4)
                if side_l == "sell"
                else 0.0
            )
            total = round(
                float(breakdown.brokerage)
                + stt
                + float(breakdown.exchange)
                + float(breakdown.gst)
                + 0.0
                + 0.0,
                4,
            )
            return FeeBreakdown(
                turnover=breakdown.turnover,
                brokerage=breakdown.brokerage,
                stt=stt,
                exchange=breakdown.exchange,
                gst=breakdown.gst,
                stamp=0.0,
                tds=0.0,
                total=total,
                profile_id=breakdown.profile_id,
                side=side_l,
            )
        return _recompute_fees(
            breakdown,
            side=side,
            quantity=qty,
            price=px,
            lot_size=lot,
            stt_pct_sell=_FUT_STT_SELL,
        )

    def default_broker_profile(self) -> str:
        return "zerodha"


class OptionsPack:
    """Equity/index options — lot multiples, premium/write margin, F&O fees."""

    id = "options"
    label = "Options"
    ready = True
    asset_classes = ("options",)
    gap_detail = ""

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
        return _fno_session(session_id, now=now, clock=clock)

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
            return OrderValidation(ok=False, reason="premium/price must be positive")
        expired = _expiry_block(context)
        if expired is not None:
            return expired

        lot = default_lot_size(symbol, context)
        qty_i = int(round(float(quantity)))
        if abs(float(quantity) - qty_i) > 1e-6:
            return OrderValidation(
                ok=False,
                reason=f"options quantity must be a whole number of units (got {quantity})",
            )
        if qty_i % lot != 0:
            return OrderValidation(
                ok=False,
                reason=f"options quantity {qty_i} must be a multiple of lot_size={lot}",
            )

        held = float((context or {}).get("position_qty") or 0.0)
        cash = float((context or {}).get("cash") or 0.0)
        premium = qty_i * float(price)

        if side_l == "buy":
            # Long premium: full debit (closing a short is also buy).
            if held >= 0 and cash + 1e-6 < premium:
                return OrderValidation(
                    ok=False,
                    reason=f"insufficient cash for premium {premium:.2f}; cash={cash:.2f}",
                )
            return OrderValidation(ok=True)

        # Sell: closing long vs writing (opening/increasing short).
        closing_long = held > 0 and qty_i <= held + 1e-9
        if closing_long:
            return OrderValidation(ok=True)
        margin_pct = _margin_fraction(context, writing=True)
        # Write margin: fraction of underlying notional when known, else 10× premium proxy.
        underlying = (context or {}).get("underlying_price")
        if underlying is None and isinstance((context or {}).get("instrument"), dict):
            underlying = context["instrument"].get("underlying_price")
        if underlying is not None:
            try:
                notional = qty_i * float(underlying)
            except (TypeError, ValueError):
                notional = premium * 10.0
        else:
            notional = premium * 10.0
        required = notional * margin_pct
        if cash + 1e-6 < required:
            return OrderValidation(
                ok=False,
                reason=(
                    f"insufficient margin to write options: need ~{required:.2f} "
                    f"({margin_pct:.0%} of notional proxy); cash={cash:.2f}"
                ),
            )
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
        lot = default_lot_size(symbol, context)
        qty = float(quantity) if quantity else 0.0
        px = float(price) if price else 0.0
        if qty <= 0 or px <= 0:
            side_l = (side or breakdown.side or "").strip().lower()
            stt = (
                round(float(breakdown.turnover) * _OPT_STT_SELL, 4)
                if side_l == "sell"
                else 0.0
            )
            total = round(
                float(breakdown.brokerage)
                + stt
                + float(breakdown.exchange)
                + float(breakdown.gst),
                4,
            )
            return FeeBreakdown(
                turnover=breakdown.turnover,
                brokerage=breakdown.brokerage,
                stt=stt,
                exchange=breakdown.exchange,
                gst=breakdown.gst,
                stamp=0.0,
                tds=0.0,
                total=total,
                profile_id=breakdown.profile_id,
                side=side_l,
            )
        return _recompute_fees(
            breakdown,
            side=side,
            quantity=qty,
            price=px,
            lot_size=lot,
            stt_pct_sell=_OPT_STT_SELL,
        )

    def default_broker_profile(self) -> str:
        return "zerodha"
