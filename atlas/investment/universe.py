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
INDEX_NIFTY_NEXT50 = "NIFTY_NEXT50"
INDEX_NIFTY_MIDCAP150 = "NIFTY_MIDCAP150"
INDEX_NIFTY_SMALLCAP250 = "NIFTY_SMALLCAP250"

KNOWN_INDICES = (
    INDEX_NIFTY50,
    INDEX_NIFTY_NEXT50,
    INDEX_NIFTY100,
    INDEX_NIFTY_MIDCAP150,
    INDEX_NIFTY_SMALLCAP250,
    INDEX_NIFTY500,
)

# IRA.10 — staged mid/large next-50 seed (not an official NSE reconstitutions dump).
# Also used as NIFTY_NEXT50 membership (IIP.1).
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

# IIP.1 — staged midcap seed (not full official Nifty Midcap 150).
_MIDCAP_EXTRA_RAW: tuple[tuple[str, str, str], ...] = (
    ("ASTRAL", "Astral", "Capital Goods"),
    ("BALKRISHNA", "Balkrishna Industries", "Automobile"),
    ("BHARATFORG", "Bharat Forge", "Automobile"),
    ("COFORGE", "Coforge", "Information Technology"),
    ("CONCOR", "Container Corporation", "Services"),
    ("COROMANDEL", "Coromandel International", "Chemicals"),
    ("DEEPAKNTR", "Deepak Nitrite", "Chemicals"),
    ("ESCORTS", "Escorts Kubota", "Automobile"),
    ("EXIDEIND", "Exide Industries", "Automobile"),
    ("FACT", "FACT", "Chemicals"),
    ("FORTIS", "Fortis Healthcare", "Healthcare"),
    ("GLENMARK", "Glenmark Pharma", "Healthcare"),
    ("GODREJPROP", "Godrej Properties", "Realty"),
    ("GUJGASLTD", "Gujarat Gas", "Oil Gas & Fuels"),
    ("HFCL", "HFCL", "Telecommunication"),
    ("HUDCO", "HUDCO", "Financial Services"),
    ("IDEA", "Vodafone Idea", "Telecommunication"),
    ("IEX", "Indian Energy Exchange", "Financial Services"),
    ("IGL", "Indraprastha Gas", "Oil Gas & Fuels"),
    ("INDUSINDBK", "IndusInd Bank", "Financial Services"),
    ("INDUSTOWER", "Indus Towers", "Telecommunication"),
    ("IPCALAB", "IPCA Laboratories", "Healthcare"),
    ("JINDALSTEL", "Jindal Steel & Power", "Metals & Mining"),
    ("JSL", "Jindal Stainless", "Metals & Mining"),
    ("KEI", "KEI Industries", "Capital Goods"),
    ("KPITTECH", "KPIT Technologies", "Information Technology"),
    ("LTTS", "L&T Technology Services", "Information Technology"),
    ("MOTHERSON", "Samvardhana Motherson", "Automobile"),
    ("MPHASIS", "Mphasis", "Information Technology"),
    ("MRF", "MRF", "Automobile"),
    ("NHPC", "NHPC", "Power"),
    ("NMDC", "NMDC", "Metals & Mining"),
    ("OBEROIRLTY", "Oberoi Realty", "Realty"),
    ("OFSS", "Oracle Financial Services", "Information Technology"),
    ("OIL", "Oil India", "Oil Gas & Fuels"),
    ("PATANJALI", "Patanjali Foods", "FMCG"),
    ("PETRONET", "Petronet LNG", "Oil Gas & Fuels"),
    ("POLYCAB", "Polycab India", "Capital Goods"),
    ("PRESTIGE", "Prestige Estates", "Realty"),
    ("SAIL", "SAIL", "Metals & Mining"),
    ("SOLARINDS", "Solar Industries", "Chemicals"),
    ("SONACOMS", "Sona BLW Precision", "Automobile"),
    ("SUNTV", "Sun TV Network", "Media"),
    ("SUPREMEIND", "Supreme Industries", "Capital Goods"),
    ("SUZLON", "Suzlon Energy", "Capital Goods"),
    ("SYNGENE", "Syngene International", "Healthcare"),
    ("TATACHEM", "Tata Chemicals", "Chemicals"),
    ("TATACOMM", "Tata Communications", "Telecommunication"),
    ("TATAELXSI", "Tata Elxsi", "Information Technology"),
    ("TATAPOWER", "Tata Power", "Power"),
    ("TIINDIA", "Tube Investments", "Automobile"),
    ("TORNTPOWER", "Torrent Power", "Power"),
    ("UNOMINDA", "UNO Minda", "Automobile"),
    ("VOLTAS", "Voltas", "Consumer Durables"),
    ("ZEEL", "Zee Entertainment", "Media"),
)

# IIP.1 — staged smallcap seed (not full official Nifty Smallcap 250).
_SMALLCAP_EXTRA_RAW: tuple[tuple[str, str, str], ...] = (
    ("AFFLE", "Affle India", "Information Technology"),
    ("ANGELONE", "Angel One", "Financial Services"),
    ("BSE", "BSE Ltd", "Financial Services"),
    ("CAMS", "CAMS", "Financial Services"),
    ("CDSL", "CDSL", "Financial Services"),
    ("CLEAN", "Clean Science", "Chemicals"),
    ("CRAFTSMAN", "Craftsman Automation", "Automobile"),
    ("CYIENT", "Cyient", "Information Technology"),
    ("DATAPATTNS", "Data Patterns", "Capital Goods"),
    ("DEVYANI", "Devyani International", "Consumer Services"),
    ("EASEMYTRIP", "Easy Trip Planners", "Consumer Services"),
    ("ELECON", "Elecon Engineering", "Capital Goods"),
    ("GESHIP", "Great Eastern Shipping", "Services"),
    ("HAPPSTMNDS", "Happiest Minds", "Information Technology"),
    ("HBLPOWER", "HBL Power", "Capital Goods"),
    ("IIFL", "IIFL Finance", "Financial Services"),
    ("INTELLECT", "Intellect Design", "Information Technology"),
    ("JBCHEPHARM", "JB Chemicals", "Healthcare"),
    ("JUBLPHARMA", "Jubilant Pharmova", "Healthcare"),
    ("KAYNES", "Kaynes Technology", "Capital Goods"),
    ("LATENTVIEW", "Latent View", "Information Technology"),
    ("LXCHEM", "Laxmi Organic", "Chemicals"),
    ("MAPMYINDIA", "C.E. Info Systems", "Information Technology"),
    ("MAZDOCK", "Mazagon Dock", "Capital Goods"),
    ("MEDPLUS", "Medplus Health", "Healthcare"),
    ("METROPOLIS", "Metropolis Healthcare", "Healthcare"),
    ("NAVINFLUOR", "Navin Fluorine", "Chemicals"),
    ("NEWGEN", "Newgen Software", "Information Technology"),
    ("PPLPHARMA", "Piramal Pharma", "Healthcare"),
    ("PRAJIND", "Praj Industries", "Capital Goods"),
    ("RADICO", "Radico Khaitan", "FMCG"),
    ("ROUTE", "Route Mobile", "Telecommunication"),
    ("RVNL", "Rail Vikas Nigam", "Construction"),
    ("TANLA", "Tanla Platforms", "Telecommunication"),
    ("TEJASNET", "Tejas Networks", "Telecommunication"),
    ("TRITURBINE", "Triveni Turbine", "Capital Goods"),
    ("UJJIVANSFB", "Ujjivan Small Finance", "Financial Services"),
    ("WELCORP", "Welspun Corp", "Metals & Mining"),
    ("ZENTEC", "Zen Technologies", "Capital Goods"),
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

NIFTY_NEXT50: tuple[dict[str, Any], ...] = NIFTY100_EXTRA

MIDCAP_EXTRA: tuple[dict[str, Any], ...] = tuple(
    _row(s, n, sec) for s, n, sec in _MIDCAP_EXTRA_RAW
)

SMALLCAP_EXTRA: tuple[dict[str, Any], ...] = tuple(
    _row(s, n, sec) for s, n, sec in _SMALLCAP_EXTRA_RAW
)


def merge_unique(*packs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _merge_unique(*packs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return merge_unique(*packs)


def universe_meta(index: str) -> dict[str, Any]:
    key = (index or INDEX_NIFTY50).strip().upper().replace(" ", "")
    meta = {
        INDEX_NIFTY50: {
            "family": "index",
            "label": "Nifty 50",
            "staged": False,
            "note": "Primary India large-cap snapshot (lags official reconstitutions).",
        },
        INDEX_NIFTY_NEXT50: {
            "family": "index",
            "label": "Nifty Next 50 (staged)",
            "staged": True,
            "note": "Staged seed ≈ next-50 names — not a live NSE dump.",
        },
        INDEX_NIFTY100: {
            "family": "index",
            "label": "Nifty 100 (staged)",
            "staged": True,
            "note": "NIFTY50 ∪ Next50 seed.",
        },
        INDEX_NIFTY_MIDCAP150: {
            "family": "index",
            "label": "Nifty Midcap (staged seed)",
            "staged": True,
            "note": "Curated midcap seed for IIP.1 — not full Midcap 150 yet.",
        },
        INDEX_NIFTY_SMALLCAP250: {
            "family": "index",
            "label": "Nifty Smallcap (staged seed)",
            "staged": True,
            "note": "Curated smallcap seed for IIP.1 — not full Smallcap 250 yet.",
        },
        INDEX_NIFTY500: {
            "family": "index",
            "label": "Nifty 500 (staged)",
            "staged": True,
            "note": "Currently NIFTY100 ∪ midcap ∪ smallcap seeds until full list curated.",
        },
    }
    return dict(meta.get(key) or {"family": "index", "label": key, "staged": True, "note": ""})


def membership(
    index: str = INDEX_NIFTY50,
    *,
    extra_members: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return constituent rows for an index (IIP.1 multi-set)."""
    key = (index or INDEX_NIFTY50).strip().upper().replace(" ", "")
    aliases = {
        "NIFTYNEXT50": INDEX_NIFTY_NEXT50,
        "NEXT50": INDEX_NIFTY_NEXT50,
        "NIFTYMIDCAP150": INDEX_NIFTY_MIDCAP150,
        "MIDCAP150": INDEX_NIFTY_MIDCAP150,
        "NIFTYSMALLCAP250": INDEX_NIFTY_SMALLCAP250,
        "SMALLCAP250": INDEX_NIFTY_SMALLCAP250,
    }
    key = aliases.get(key, key)

    if key in {"NIFTY50", "NIFTY_50", "CNX50"}:
        rows = [dict(r) for r in NIFTY50]
    elif key in {INDEX_NIFTY_NEXT50, "NIFTY_NEXT_50"}:
        rows = [dict(r) for r in NIFTY_NEXT50]
    elif key in {"NIFTY100", "NIFTY_100"}:
        rows = merge_unique(NIFTY50, NIFTY_NEXT50)
    elif key in {INDEX_NIFTY_MIDCAP150, "NIFTY_MIDCAP"}:
        rows = merge_unique(MIDCAP_EXTRA)
    elif key in {INDEX_NIFTY_SMALLCAP250, "NIFTY_SMALLCAP"}:
        rows = merge_unique(SMALLCAP_EXTRA)
    elif key in {"NIFTY500", "NIFTY_500"}:
        rows = merge_unique(NIFTY50, NIFTY_NEXT50, MIDCAP_EXTRA, SMALLCAP_EXTRA)
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
