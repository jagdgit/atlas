"""Decide-time features for an F&O Lab v1 option entry (R0 feature capture).

Everything here is computed from inputs Atlas already holds at the moment of
the BUY (spot, strike, expiry, both ATM premiums, the control indicators, the
clock). Implied volatility and Greeks are Black-Scholes *derived* from the
traded premium — a description of the price, not a model of it. Inputs Atlas
does not receive (India VIX, open interest, bid/ask) are listed as missing,
never filled in.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "fno.features.v1"
_IST = ZoneInfo("Asia/Kolkata")
RISK_FREE_RATE = 0.065
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
NOT_CAPTURED = ("india_vix", "open_interest", "oi_change", "bid_ask_spread", "pcr", "futures_basis")
_YEAR_MIN = 365.0 * 24 * 60


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(right: str, spot: float, strike: float, t: float, vol: float, r: float = RISK_FREE_RATE) -> float:
    sd = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / sd
    d2 = d1 - sd
    if right == "CE":
        return spot * _ncdf(d1) - strike * math.exp(-r * t) * _ncdf(d2)
    return strike * math.exp(-r * t) * _ncdf(-d2) - spot * _ncdf(-d1)


def implied_vol(right: str, premium: float, spot: float, strike: float, t: float, r: float = RISK_FREE_RATE) -> float | None:
    """Bisection on [1%, 500%]. None when the premium is outside no-arbitrage bounds."""
    if premium <= 0 or spot <= 0 or strike <= 0 or t <= 0:
        return None
    lo, hi = 0.01, 5.0
    if not (bs_price(right, spot, strike, t, lo, r) <= premium <= bs_price(right, spot, strike, t, hi, r)):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bs_price(right, spot, strike, t, mid, r) < premium:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def greeks(right: str, spot: float, strike: float, t: float, vol: float, r: float = RISK_FREE_RATE) -> dict[str, float]:
    sd = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / sd
    d2 = d1 - sd
    disc = strike * math.exp(-r * t)
    if right == "CE":
        delta = _ncdf(d1)
        theta = -spot * _npdf(d1) * vol / (2 * math.sqrt(t)) - r * disc * _ncdf(d2)
    else:
        delta = _ncdf(d1) - 1.0
        theta = -spot * _npdf(d1) * vol / (2 * math.sqrt(t)) + r * disc * _ncdf(-d2)
    return {
        "delta": delta,
        "gamma": _npdf(d1) / (spot * sd),
        "theta_per_day": theta / 365.0,
        "vega_per_vol_pt": spot * _npdf(d1) * math.sqrt(t) / 100.0,
    }


def _expiry_close(expiry: Any) -> datetime | None:
    try:
        d = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return None
    return datetime.combine(d, SESSION_CLOSE, tzinfo=_IST)


def entry_features(
    *,
    right: str | None,
    spot: Any,
    strike: Any,
    expiry: Any,
    premium: Any,
    other_premium: Any = None,
    indicators: dict[str, Any] | None = None,
    sma_margin: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Flat dict of decide-time features. Unavailable values are omitted and named in ``missing``."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    ist = clock.astimezone(_IST)
    r_u = str(right or "").upper()
    s, k, p, q = _f(spot), _f(strike), _f(premium), _f(other_premium)
    ind = indicators if isinstance(indicators, dict) else {}
    out: dict[str, Any] = {"features_version": VERSION}
    missing: list[str] = list(NOT_CAPTURED)

    for key in ("rsi", "sma_fast", "sma_slow"):
        v = _f(ind.get(key))
        if v is not None:
            out[key] = v
        else:
            missing.append(key)
    m = _f(sma_margin)
    if m is not None:
        out["sma_margin"] = m

    open_dt = datetime.combine(ist.date(), SESSION_OPEN, tzinfo=_IST)
    close_dt = datetime.combine(ist.date(), SESSION_CLOSE, tzinfo=_IST)
    out["minutes_since_open"] = round((ist - open_dt).total_seconds() / 60.0, 1)
    out["minutes_to_close"] = round((close_dt - ist).total_seconds() / 60.0, 1)
    out["day_of_week"] = ist.weekday()

    if s and k:
        out["moneyness"] = s / k - 1.0
    if s and p:
        out["premium_pct_spot"] = p / s
    if p and q and r_u in {"CE", "PE"}:
        ce, pe = (p, q) if r_u == "CE" else (q, p)
        out["ce_pe_skew"] = (ce - pe) / (ce + pe)

    exp_close = _expiry_close(expiry)
    t_years = None
    if exp_close is not None:
        minutes = (exp_close - ist).total_seconds() / 60.0
        out["dte_days"] = round(minutes / (24 * 60), 3)
        out["expiry_week"] = minutes <= 7 * 24 * 60
        t_years = minutes / _YEAR_MIN if minutes > 0 else None
    else:
        missing.append("dte_days")

    iv = implied_vol(r_u, p, s, k, t_years) if (r_u in {"CE", "PE"} and p and s and k and t_years) else None
    if iv is not None:
        out["iv"] = iv
        out.update(greeks(r_u, s, k, t_years, iv))
        out["iv_method"] = f"black_scholes_bisection r={RISK_FREE_RATE} no_dividend"
    else:
        missing.extend(["iv", "delta", "gamma", "theta_per_day", "vega_per_vol_pt"])
    out["missing"] = sorted(set(missing))
    return out
