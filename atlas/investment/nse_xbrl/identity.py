"""Sector / identity — not XBRL P&L facts (L26)."""

from __future__ import annotations

from typing import Any


def resolve_nse_code(symbol: str) -> str:
    """Listed NSE ticker for filings APIs. HBLPOWER → HBLENGINE; never invent."""
    from atlas.investment.symbol_aliases import resolve_yahoo_symbol

    raw = str(symbol or "").strip()
    if not raw:
        return ""
    resolved = resolve_yahoo_symbol(raw)
    code = str(resolved.yahoo or raw).strip().upper()
    if ":" in code:
        code = code.split(":", 1)[-1]
    if code.startswith("^"):
        return ""
    return code.replace(".NS", "").replace(".BO", "")


def resolve_identity(
    symbol: str,
    *,
    data_dir: str | None = None,
    fundamentals: dict[str, Any] | None = None,
    awareness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Universe catalog + store + awareness. Never invent a sector from ticker shape."""
    from atlas.investment.fundamentals import normalize_symbol
    from atlas.investment.universe import lookup_symbol

    sym = normalize_symbol(symbol)
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    aw = awareness if isinstance(awareness, dict) else {}
    uni = lookup_symbol(sym) or lookup_symbol(str(symbol or "").replace(".NS", ""))
    sector = (
        str(fund.get("sector") or "").strip()
        or str(aw.get("sector") or "").strip()
        or str((uni or {}).get("sector") or "").strip()
    )
    name = (
        str(fund.get("name") or "").strip()
        or str((uni or {}).get("name") or "").strip()
        or str(symbol or "").strip()
    )
    identity_ok = bool(name) and bool(uni or fund.get("name") or aw.get("identity"))
    if isinstance(aw.get("identity"), dict) and aw["identity"]:
        identity_ok = True
    if uni:
        identity_ok = True
    source = None
    if fund.get("sector"):
        source = str(fund.get("source") or "fundamentals_store")
    elif uni:
        source = "universe_catalog"
    elif aw.get("sector"):
        source = "awareness"
    return {
        "symbol": sym,
        "name": name or None,
        "sector": sector or None,
        "identity_ok": identity_ok,
        "sector_ok": bool(sector),
        "source": source,
        "nse_symbol": (uni or {}).get("nse_symbol"),
        "honesty": "Sector/identity are catalog/profile facts, not XBRL NET_INCOME concepts.",
    }
