"""Ensure hermetic company profiles for open-book / required symbols (MI.5+)."""

from __future__ import annotations

import logging
from typing import Any

def load_profile(data_dir: str | None, symbol: str) -> dict[str, Any] | None:
    """Catalog identity for FEA — not a Yahoo fetch and not invented PE."""
    from atlas.investment.universe import lookup_symbol

    row = lookup_symbol(symbol)
    if not isinstance(row, dict):
        return None
    return {
        "name": row.get("name"),
        "legal_name": row.get("name"),
        "sector": row.get("sector"),
        "source": "universe_catalog",
    }


def sync_profile_to_fundamentals(
    data_dir: str | None,
    symbol: str,
    profile: dict[str, Any],
    *,
    program_id: str = "market_intelligence",
) -> dict[str, Any] | None:
    """Upsert sector-proxy ratios into durable fundamentals store (never invent PE)."""
    if not data_dir or not isinstance(profile, dict):
        return None
    sym = str(profile.get("symbol") or symbol or "").strip().upper()
    if not sym:
        return None
    ratios = profile.get("ratios") if isinstance(profile.get("ratios"), dict) else {}
    row: dict[str, Any] = {"symbol": sym}
    if profile.get("sector"):
        row["sector"] = profile.get("sector")
    for fld in ("roe", "roce", "roic", "debt_to_equity", "pe", "fcf", "operating_margin"):
        if ratios.get(fld) is not None:
            row[fld] = ratios[fld]
    if len(row) <= 1:
        return None
    meta = profile.get("metadata") if isinstance(profile.get("metadata"), dict) else {}
    row.setdefault("source", meta.get("source") or "universe_seed")
    row.setdefault("method", meta.get("method") or "sector_proxy")
    try:
        from atlas.investment.fundamentals import upsert_rows

        return upsert_rows(
            data_dir,
            [row],
            program_id=program_id,
            source=str(row.get("source") or "universe_seed"),
            note="Open-book / universe hermetic profile sync",
            merge_screener=True,
        )
    except Exception:  # noqa: BLE001
        _log.debug("fundamentals sync skipped for %s", sym, exc_info=True)
        return None


def ensure_symbol_profile(
    company_data: Any,
    symbol: str,
    *,
    data_dir: str | None = None,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Load config_seed profile for symbol; sync ratios to fundamentals when possible."""
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {"symbol": sym, "ok": False}
    if not sym or company_data is None or not hasattr(company_data, "fetch"):
        out["reason"] = "no_service"
        return out
    try:
        fetched = company_data.fetch(sym, provider="config_seed")
        profile = (fetched or {}).get("profile") or {}
        out["ok"] = bool(profile.get("name") or profile.get("sector"))
        out["profile"] = profile
        out["provider"] = (fetched or {}).get("provider")
        if data_dir and profile:
            sync_profile_to_fundamentals(data_dir, sym, profile, program_id=program_id)
        return out
    except Exception as exc:  # noqa: BLE001
        out["reason"] = type(exc).__name__
        out["detail"] = str(exc)[:200]
        return out


def ensure_symbols_profiles(
    company_data: Any,
    symbols: list[str] | None,
    *,
    data_dir: str | None = None,
    program_id: str = "market_intelligence",
    limit: int = 40,
) -> dict[str, Any]:
    """Ensure hermetic profiles for holdings + planned symbols."""
    syms = []
    for s in symbols or []:
        u = str(s or "").strip().upper()
        if u and u not in syms:
            syms.append(u)
        if len(syms) >= max(1, int(limit)):
            break
    results: list[dict[str, Any]] = []
    ok_n = 0
    for sym in syms:
        row = ensure_symbol_profile(
            company_data, sym, data_dir=data_dir, program_id=program_id
        )
        results.append(row)
        if row.get("ok"):
            ok_n += 1
    return {
        "version": "company_profiles.v1",
        "count": len(syms),
        "ok": ok_n,
        "symbols": syms,
        "results": results[:12],
    }


def ensure_open_book_profiles(
    *,
    data_dir: str | None,
    company_data: Any,
    portfolio: Any | None,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Ensure profiles for qty>0 holdings in a lab ledger."""
    from atlas.investment.open_book_packs import resolve_open_symbols

    syms = resolve_open_symbols(portfolio=portfolio, portfolio_key=laboratory_id)
    # Also include challenger-table planned symbols when available
    if data_dir:
        try:
            from pathlib import Path
            import json

            day_path = (
                Path(data_dir)
                / "investment"
                / "allocation"
                / laboratory_id
            )
            for p in sorted(day_path.glob("20*.json"), reverse=True)[:1]:
                doc = json.loads(p.read_text(encoding="utf-8"))
                for row in doc.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    sym = str(row.get("symbol") or "").upper()
                    if sym and sym not in syms:
                        syms.append(sym)
        except Exception:  # noqa: BLE001
            pass
    return ensure_symbols_profiles(
        company_data,
        syms,
        data_dir=data_dir,
        program_id=program_id,
    )
