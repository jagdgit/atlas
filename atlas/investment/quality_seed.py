"""Hermetic India quality seeds for ranking / company profiles (IL.5).

These are **illustrative sector proxies** for simulation — not live filings,
Screener scrapes, or investment advice. Operators may override any symbol via
``quality_seed`` on M0, or pin richer ``companies[].ratios`` on M2.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.universe import INDEX_NIFTY50, membership

AS_OF = "2026-07"
SOURCE = "hermetic_seed"

# Sector → illustrative ROE (fraction) and debt/equity for ranking proxies.
# Banks/NBFCs use higher D/E by design; IT/FMCG stay lightly levered.
_SECTOR_PROXY: dict[str, dict[str, float]] = {
    "Information Technology": {"roe": 0.28, "debt_to_equity": 0.12},
    "Financial Services": {"roe": 0.15, "debt_to_equity": 1.10},
    "FMCG": {"roe": 0.26, "debt_to_equity": 0.20},
    "Automobile": {"roe": 0.18, "debt_to_equity": 0.45},
    "Healthcare": {"roe": 0.16, "debt_to_equity": 0.35},
    "Oil Gas & Fuels": {"roe": 0.12, "debt_to_equity": 0.55},
    "Metals & Mining": {"roe": 0.11, "debt_to_equity": 0.70},
    "Power": {"roe": 0.13, "debt_to_equity": 0.90},
    "Telecommunication": {"roe": 0.10, "debt_to_equity": 1.40},
    "Construction": {"roe": 0.14, "debt_to_equity": 0.65},
    "Construction Materials": {"roe": 0.15, "debt_to_equity": 0.50},
    "Consumer Durables": {"roe": 0.20, "debt_to_equity": 0.25},
    "Consumer Services": {"roe": 0.17, "debt_to_equity": 0.40},
    "Capital Goods": {"roe": 0.16, "debt_to_equity": 0.30},
    "Services": {"roe": 0.14, "debt_to_equity": 0.55},
}

_DEFAULT_PROXY = {"roe": 0.14, "debt_to_equity": 0.50}


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s and not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def sector_proxy(sector: str | None) -> dict[str, float]:
    key = (sector or "").strip()
    return dict(_SECTOR_PROXY.get(key) or _DEFAULT_PROXY)


def quality_row(
    *,
    symbol: str,
    sector: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One quality seed row for ranking / company ratios."""
    base = sector_proxy(sector)
    ov = dict(overrides or {})
    roe = ov.get("roe", base["roe"])
    de = ov.get("debt_to_equity", ov.get("debt_equity", base["debt_to_equity"]))
    return {
        "roe": float(roe),
        "debt_to_equity": float(de),
        "source": str(ov.get("source") or SOURCE),
        "as_of": str(ov.get("as_of") or AS_OF),
        "method": str(ov.get("method") or "sector_proxy"),
        "sector": (sector or "").strip() or None,
        "symbol": _normalize_symbol(symbol),
    }


def nifty50_quality_seed() -> dict[str, dict[str, Any]]:
    """Full NIFTY50 hermetic quality map keyed by Yahoo ``.NS`` symbol."""
    out: dict[str, dict[str, Any]] = {}
    for row in membership(INDEX_NIFTY50):
        sym = str(row["symbol"])
        out[sym] = quality_row(symbol=sym, sector=str(row.get("sector") or ""))
    return out


def resolve_quality_seed(
    raw: Any = None,
    *,
    index: str = INDEX_NIFTY50,
    use_default: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge operator ``quality_seed`` over the hermetic index pack.

    - ``False`` / ``use_default=False`` → no seed (neutral quality in ranking)
    - empty / omitted → hermetic NIFTY pack when index is NIFTY*
    - dict → operator keys win (normalized to ``.NS``)
    """
    if raw is False:
        return {}
    if use_default is False:
        return _normalize_map(raw) if isinstance(raw, dict) else {}

    want_default = True if use_default is None else bool(use_default)
    base: dict[str, dict[str, Any]] = {}
    idx = (index or INDEX_NIFTY50).strip().upper().replace(" ", "")
    if want_default and idx.startswith("NIFTY"):
        base = nifty50_quality_seed()

    if not isinstance(raw, dict) or not raw:
        return base

    merged = dict(base)
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        sym = _normalize_symbol(str(key))
        sector = val.get("sector")
        if not sector and sym in merged:
            sector = merged[sym].get("sector")
        merged[sym] = quality_row(symbol=sym, sector=sector, overrides=val)
    return merged


def _normalize_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            sym = _normalize_symbol(str(key))
            out[sym] = quality_row(
                symbol=sym,
                sector=val.get("sector"),
                overrides=val,
            )
    return out


def ratios_for_symbol(
    symbol: str,
    *,
    seed: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ratios dict suitable for CompanyProfile ``ratios`` (empty if unknown)."""
    pack = seed if seed is not None else nifty50_quality_seed()
    row = pack.get(_normalize_symbol(symbol))
    if not row:
        return {}
    return {
        "roe": row.get("roe"),
        "debt_to_equity": row.get("debt_to_equity"),
        "source": row.get("source"),
        "as_of": row.get("as_of"),
        "method": row.get("method"),
    }
