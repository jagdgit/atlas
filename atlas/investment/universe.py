"""Indian cash-equity universes (IL.1) — static membership for autonomous learning.

NIFTY50 is a **snapshot** for hermetic ranking / M0; NSE reconstitutes periodically.
Symbols use Yahoo-style ``.NS`` suffixes to match MarketReader adapters.
"""

from __future__ import annotations

from typing import Any

# Snapshot aligned to mid-2026 Wikipedia / NSE public lists (IL-Q2 stage 1).
# Not investment advice; membership lags official reconstitutions by design.
_NIFTY50_RAW: tuple[tuple[str, str, str], ...] = (
    ("ADANIENT", "Adani Enterprises", "Metals & Mining"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Services"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare"),
    ("ASIANPAINT", "Asian Paints", "Consumer Durables"),
    ("AXISBANK", "Axis Bank", "Financial Services"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Automobile"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services"),
    ("BEL", "Bharat Electronics", "Capital Goods"),
    ("BHARTIARTL", "Bharti Airtel", "Telecommunication"),
    ("CIPLA", "Cipla", "Healthcare"),
    ("COALINDIA", "Coal India", "Oil Gas & Fuels"),
    ("DRREDDY", "Dr Reddy's Laboratories", "Healthcare"),
    ("EICHERMOT", "Eicher Motors", "Automobile"),
    ("ETERNAL", "Eternal", "Consumer Services"),
    ("GRASIM", "Grasim Industries", "Construction Materials"),
    ("HCLTECH", "HCL Technologies", "Information Technology"),
    ("HDFCBANK", "HDFC Bank", "Financial Services"),
    ("HDFCLIFE", "HDFC Life", "Financial Services"),
    ("HINDALCO", "Hindalco Industries", "Metals & Mining"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    ("ICICIBANK", "ICICI Bank", "Financial Services"),
    ("INDIGO", "InterGlobe Aviation", "Services"),
    ("INFY", "Infosys", "Information Technology"),
    ("ITC", "ITC", "FMCG"),
    ("JIOFIN", "Jio Financial Services", "Financial Services"),
    ("JSWSTEEL", "JSW Steel", "Metals & Mining"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services"),
    ("LT", "Larsen & Toubro", "Construction"),
    ("M&M", "Mahindra & Mahindra", "Automobile"),
    ("MARUTI", "Maruti Suzuki", "Automobile"),
    ("MAXHEALTH", "Max Healthcare", "Healthcare"),
    ("NESTLEIND", "Nestle India", "FMCG"),
    ("NTPC", "NTPC", "Power"),
    ("ONGC", "ONGC", "Oil Gas & Fuels"),
    ("POWERGRID", "Power Grid", "Power"),
    ("RELIANCE", "Reliance Industries", "Oil Gas & Fuels"),
    ("SBILIFE", "SBI Life", "Financial Services"),
    ("SHRIRAMFIN", "Shriram Finance", "Financial Services"),
    ("SBIN", "State Bank of India", "Financial Services"),
    ("SUNPHARMA", "Sun Pharma", "Healthcare"),
    ("TCS", "Tata Consultancy Services", "Information Technology"),
    ("TATACONSUM", "Tata Consumer Products", "FMCG"),
    ("TMPV", "Tata Motors Passenger Vehicles", "Automobile"),
    ("TATASTEEL", "Tata Steel", "Metals & Mining"),
    ("TECHM", "Tech Mahindra", "Information Technology"),
    ("TITAN", "Titan Company", "Consumer Durables"),
    ("TRENT", "Trent", "Consumer Services"),
    ("ULTRACEMCO", "UltraTech Cement", "Construction Materials"),
    ("WIPRO", "Wipro", "Information Technology"),
)

INDEX_NIFTY50 = "NIFTY50"
INDEX_NIFTY100 = "NIFTY100"  # placeholder until IL expands
INDEX_NIFTY500 = "NIFTY500"  # placeholder until IL expands

KNOWN_INDICES = (INDEX_NIFTY50, INDEX_NIFTY100, INDEX_NIFTY500)


def _row(sym: str, name: str, sector: str) -> dict[str, Any]:
    yahoo = f"{sym}.NS"
    return {
        "symbol": yahoo,
        "nse_symbol": sym,
        "name": name,
        "sector": sector,
        "exchange": "NSE",
        "asset_class": "cash_equity",
    }


NIFTY50: tuple[dict[str, Any], ...] = tuple(
    _row(s, n, sec) for s, n, sec in _NIFTY50_RAW
)


def membership(index: str = INDEX_NIFTY50) -> list[dict[str, Any]]:
    """Return constituent rows for an index (NIFTY100/500 fall back to NIFTY50 until expanded)."""
    key = (index or INDEX_NIFTY50).strip().upper().replace(" ", "")
    if key in {"NIFTY50", "NIFTY_50", "CNX50"}:
        return [dict(r) for r in NIFTY50]
    if key in {"NIFTY100", "NIFTY_100", "NIFTY500", "NIFTY_500"}:
        # IL-Q2 staged expansion: larger universes start as NIFTY50 until lists land.
        return [dict(r) for r in NIFTY50]
    raise KeyError(f"unknown index: {index!r} (known: {', '.join(KNOWN_INDICES)})")


def symbols(index: str = INDEX_NIFTY50) -> list[str]:
    return [r["symbol"] for r in membership(index)]


def sectors(index: str = INDEX_NIFTY50) -> dict[str, list[str]]:
    """Sector → list of Yahoo symbols."""
    out: dict[str, list[str]] = {}
    for row in membership(index):
        out.setdefault(str(row["sector"]), []).append(str(row["symbol"]))
    return out


def as_instruments(index: str = INDEX_NIFTY50, *, limit: int | None = None) -> list[dict[str, str]]:
    """Shape suitable for Decision Simulation ``instruments`` (auto mode)."""
    rows = membership(index)
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return [{"symbol": r["symbol"], "asset": ""} for r in rows]
