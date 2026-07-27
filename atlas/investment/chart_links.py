"""IIP.9 — external chart / terminal links (never price feeds).

TradingView and Yahoo Finance chart URLs for operator convenience.
Technicals stay local from OHLCV; these links are non-primary.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def normalize_nse_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s.endswith(".NS"):
        s = s[:-3]
    if s.endswith(".BO"):
        s = s[:-3]
    return s


def tradingview_chart_url(
    symbol: str,
    *,
    exchange: str | None = None,
) -> str:
    """Build a TradingView chart deep-link (NSE default for .NS / bare India names)."""
    raw = (symbol or "").strip().upper()
    bare = normalize_nse_symbol(raw)
    if not bare:
        return "https://www.tradingview.com/"
    ex = (exchange or "").strip().upper()
    if not ex:
        if raw.endswith(".BO"):
            ex = "BSE"
        elif raw.endswith(".NS") or "." not in raw:
            ex = "NSE"
        else:
            # e.g. AAPL — leave as-is for TV search
            return f"https://www.tradingview.com/chart/?symbol={quote(bare)}"
    return f"https://www.tradingview.com/chart/?symbol={quote(f'{ex}:{bare}')}"


def yahoo_chart_url(symbol: str) -> str:
    """Yahoo Finance quote page for the symbol (usually .NS)."""
    s = (symbol or "").strip().upper()
    if not s:
        return "https://finance.yahoo.com/"
    if "." not in s:
        s = f"{s}.NS"
    return f"https://finance.yahoo.com/quote/{quote(s)}"


def screener_url(symbol: str) -> str:
    """Screener.in company page hint (operator may need slug fix)."""
    bare = normalize_nse_symbol(symbol).lower()
    if not bare:
        return "https://www.screener.in/"
    return f"https://www.screener.in/company/{quote(bare)}/"


def chart_links_for(symbol: str) -> dict[str, Any]:
    bare = normalize_nse_symbol(symbol)
    return {
        "symbol": (symbol or "").strip().upper() or None,
        "bare": bare or None,
        "tradingview": tradingview_chart_url(symbol),
        "yahoo": yahoo_chart_url(symbol),
        "screener": screener_url(symbol),
        "note": (
            "Chart links only — never the primary price feed. "
            "Technicals are computed locally from OHLCV bars."
        ),
        "version": "iip.9.chart_links",
    }
