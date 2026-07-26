"""IRA.20 — timing-only technical pack (never a thesis substitute)."""

from __future__ import annotations

from typing import Any

from atlas.investment.research.models import utc_now_iso
from atlas.trading.indicators import compute_indicators

LABEL = "timing_only"
HONESTY = (
    "Technicals are timing context only — not business quality, not MoS, "
    "not a substitute for MVR thesis (IRA.20 / IRA9)."
)


def timing_from_closes(
    closes: list[float] | None,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a labeled timing snapshot from close prices."""
    closes = [float(c) for c in (closes or []) if c is not None]
    if len(closes) < 5:
        return {
            "label": LABEL,
            "as_of": utc_now_iso(),
            "status": "insufficient_bars",
            "honesty": HONESTY,
            "signals": {},
            "note": "Need ≥5 closes for timing context",
            "thesis_weight": 0,
        }
    ind = compute_indicators(closes, params)
    rsi_v = ind.get("rsi")
    sma_f = ind.get("sma_fast")
    sma_s = ind.get("sma_slow")
    price = ind.get("price")
    bias = "neutral"
    notes: list[str] = []
    if rsi_v is not None:
        if float(rsi_v) >= 70:
            bias = "overbought_timing"
            notes.append(f"RSI {rsi_v:.1f} ≥ 70 — timing caution only")
        elif float(rsi_v) <= 30:
            bias = "oversold_timing"
            notes.append(f"RSI {rsi_v:.1f} ≤ 30 — timing interest only")
        else:
            notes.append(f"RSI {rsi_v:.1f} mid-range")
    if sma_f is not None and sma_s is not None and price is not None:
        if float(sma_f) > float(sma_s):
            notes.append("SMA fast > slow (momentum timing)")
        else:
            notes.append("SMA fast ≤ slow (momentum timing)")
    return {
        "label": LABEL,
        "as_of": utc_now_iso(),
        "status": "present",
        "honesty": HONESTY,
        "signals": {
            "price": price,
            "bars": ind.get("bars"),
            "sma_fast": sma_f,
            "sma_slow": sma_s,
            "rsi": rsi_v,
            "macd": (ind.get("macd") or {}).get("macd") if isinstance(ind.get("macd"), dict) else ind.get("macd"),
        },
        "bias": bias,
        "notes": notes,
        "thesis_weight": 0,
    }


def timing_from_bars(bars: list[dict[str, Any]] | None, **kwargs: Any) -> dict[str, Any]:
    closes: list[float] = []
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        try:
            closes.append(float(b.get("close")))
        except (TypeError, ValueError):
            continue
    return timing_from_closes(closes, **kwargs)
