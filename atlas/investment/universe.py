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
INDEX_NIFTY100 = "NIFTY100"
INDEX_NIFTY500 = "NIFTY500"  # staged: same as NIFTY100 until full list lands

KNOWN_INDICES = (INDEX_NIFTY50, INDEX_NIFTY100, INDEX_NIFTY500)

# IRA.10 — staged mid/large next-50 seed (not an official NSE reconstitutions dump).
# Merged with NIFTY50 for NIFTY100 / NIFTY500 until a full membership list is curated.
_NIFTY100_EXTRA_RAW: tuple[tuple[str, str, str], ...] = (
    ("ABB", "ABB India", "Capital Goods"),
    ("ABBOTINDIA", "Abbott India", "Healthcare"),
    ("AUROPHARMA", "Aurobindo Pharma", "Healthcare"),
    ("BANKBARODA", "Bank of Baroda", "Financial Services"),
    ("BERGEPAINT", "Berger Paints", "Consumer Durables"),
    ("BIOCON", "Biocon", "Healthcare"),
    ("BOSCHLTD", "Bosch", "Automobile"),
    ("CANBK", "Canara Bank", "Financial Services"),
    ("CHOLAFIN", "Cholamandalam Investment", "Financial Services"),
    ("COLPAL", "Colgate-Palmolive", "FMCG"),
    ("CUMMINSIND", "Cummins India", "Capital Goods"),
    ("DABUR", "Dabur India", "FMCG"),
    ("DIXON", "Dixon Technologies", "Consumer Durables"),
    ("DMART", "Avenue Supermarts", "Consumer Services"),
    ("FEDERALBNK", "Federal Bank", "Financial Services"),
    ("GODREJCP", "Godrej Consumer", "FMCG"),
    ("HAVELLS", "Havells India", "Consumer Durables"),
    ("ICICIGI", "ICICI Lombard", "Financial Services"),
    ("ICICIPRULI", "ICICI Prudential Life", "Financial Services"),
    ("INDHOTEL", "Indian Hotels", "Consumer Services"),
    ("IRCTC", "IRCTC", "Services"),
    ("LICI", "Life Insurance Corp", "Financial Services"),
    ("LUPIN", "Lupin", "Healthcare"),
    ("MARICO", "Marico", "FMCG"),
    ("MUTHOOTFIN", "Muthoot Finance", "Financial Services"),
    ("NAUKRI", "Info Edge", "Consumer Services"),
    ("PAGEIND", "Page Industries", "Textiles"),
    ("PERSISTENT", "Persistent Systems", "Information Technology"),
    ("PFC", "Power Finance Corp", "Financial Services"),
    ("PIDILITIND", "Pidilite Industries", "Chemicals"),
    ("PNB", "Punjab National Bank", "Financial Services"),
    ("RECLTD", "REC Ltd", "Financial Services"),
    ("SIEMENS", "Siemens", "Capital Goods"),
    ("TORNTPHARM", "Torrent Pharma", "Healthcare"),
    ("TVSMOTOR", "TVS Motor", "Automobile"),
    ("UNITDSPR", "United Spirits", "FMCG"),
    ("VEDL", "Vedanta", "Metals & Mining"),
    ("YESBANK", "Yes Bank", "Financial Services"),
    ("ZOMATO", "Zomato", "Consumer Services"),
)


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

NIFTY100_EXTRA: tuple[dict[str, Any], ...] = tuple(
    _row(s, n, sec) for s, n, sec in _NIFTY100_EXTRA_RAW
)


def _merge_unique(*packs: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for pack in packs:
        for row in pack:
            sym = str(row.get("symbol") or "")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(dict(row))
    return out


def membership(
    index: str = INDEX_NIFTY50,
    *,
    extra_members: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return constituent rows for an index.

    NIFTY100 = NIFTY50 + staged mid/large extras (IRA.10).
    NIFTY500 currently mirrors NIFTY100 until a full list is curated.
    Optional ``extra_members`` always append (custom / pinned expansion).
    """
    key = (index or INDEX_NIFTY50).strip().upper().replace(" ", "")
    if key in {"NIFTY50", "NIFTY_50", "CNX50"}:
        rows = [dict(r) for r in NIFTY50]
    elif key in {"NIFTY100", "NIFTY_100"}:
        rows = _merge_unique(NIFTY50, NIFTY100_EXTRA)
    elif key in {"NIFTY500", "NIFTY_500"}:
        rows = _merge_unique(NIFTY50, NIFTY100_EXTRA)
    elif key in {"CUSTOM", "PINNED"}:
        rows = []
    else:
        raise KeyError(f"unknown index: {index!r} (known: {', '.join(KNOWN_INDICES)}, CUSTOM)")

    for raw in extra_members or []:
        if not isinstance(raw, dict):
            continue
        sym = str(raw.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if not sym.endswith(".NS") and "." not in sym:
            sym = f"{sym}.NS"
        if any(r.get("symbol") == sym for r in rows):
            continue
        rows.append(
            {
                "symbol": sym,
                "nse_symbol": str(raw.get("nse_symbol") or sym.replace(".NS", "")),
                "name": str(raw.get("name") or sym),
                "sector": str(raw.get("sector") or ""),
                "exchange": str(raw.get("exchange") or "NSE"),
                "asset_class": str(raw.get("asset_class") or "cash_equity"),
            }
        )
    return rows


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
