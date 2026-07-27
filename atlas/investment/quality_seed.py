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
    """One quality seed row for ranking / company ratios.

    Core hermetic fields: ``roe``, ``debt_to_equity``. Optional operator / screener
    fields (IRA.8) pass through when supplied: ``pe``, ``roic``, ``fcf``,
    ``operating_margin``, ``net_margin``, ``revenue_cagr``, ``promoter_holding``.
    """
    base = sector_proxy(sector)
    ov = dict(overrides or {})
    roe = ov.get("roe", base["roe"])
    de = ov.get("debt_to_equity", ov.get("debt_equity", base["debt_to_equity"]))
    row: dict[str, Any] = {
        "roe": float(roe),
        "debt_to_equity": float(de),
        "source": str(ov.get("source") or SOURCE),
        "as_of": str(ov.get("as_of") or AS_OF),
        "method": str(ov.get("method") or "sector_proxy"),
        "sector": (sector or "").strip() or None,
        "symbol": _normalize_symbol(symbol),
    }
    # Optional fundamentals — only when supplied (never invent).
    for fld in (
        "pe",
        "roic",
        "fcf",
        "operating_margin",
        "net_margin",
        "revenue_cagr",
        "earnings_cagr",
        "promoter_holding",
        "screener_score",
    ):
        if fld in ov and ov[fld] is not None:
            try:
                row[fld] = float(ov[fld])
            except (TypeError, ValueError):
                row[fld] = ov[fld]
    return row


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
    program_id: str = "market_intelligence",
    merge_operator: bool = True,
) -> dict[str, Any]:
    """Ratios dict suitable for CompanyProfile / IRA dossier (empty if unknown).

    When ``merge_operator`` is true, overlays the latest screener/research
    operator snapshot (IRA F1 ladder layer 1) so PE/FCF/price reach MVR.
    """
    pack = seed if seed is not None else nifty50_quality_seed()
    key = _normalize_symbol(symbol)
    row = dict(pack.get(key) or {})
    if merge_operator:
        try:
            from atlas.investment.screener_signals import latest_snapshot

            snap = latest_snapshot(program_id)
            op = None
            if snap and isinstance(snap.get("symbols"), dict):
                op = snap["symbols"].get(key)
            if isinstance(op, dict):
                for fld in (
                    "roe",
                    "debt_to_equity",
                    "debt_equity",
                    "pe",
                    "roic",
                    "roce",
                    "fcf",
                    "operating_margin",
                    "net_margin",
                    "revenue_cagr",
                    "earnings_cagr",
                    "promoter_holding",
                    "pledge_pct",
                    "price",
                    "shares",
                    "share_count",
                    "capex",
                    "fcf_growth",
                    "discount_rate",
                    "sector",
                    "evidence_confidence",
                    "confidence",
                    "as_of",
                    "source",
                    "method",
                ):
                    if op.get(fld) is not None:
                        row[fld] = op[fld]
                row.setdefault("source", op.get("source") or "operator_snapshot")
                row.setdefault("method", "operator_snapshot")
                if op.get("as_of"):
                    row["as_of"] = op["as_of"]
        except Exception:  # noqa: BLE001 - operator merge is best-effort
            pass
        # IIP.3 durable fundamentals store (overrides screener when present)
        try:
            from atlas.config import get_config
            from atlas.investment.fundamentals import get_symbol as fund_get

            fund = fund_get(str(get_config().paths.data), key, program_id=program_id)
            if isinstance(fund, dict):
                for fld in (
                    "roe",
                    "roce",
                    "roic",
                    "debt_to_equity",
                    "pe",
                    "pb",
                    "fcf",
                    "operating_margin",
                    "net_margin",
                    "revenue_cagr",
                    "earnings_cagr",
                    "promoter_holding",
                    "pledge_pct",
                    "price",
                    "shares",
                    "sector",
                    "as_of",
                    "source",
                    "method",
                    "evidence_sufficiency",
                    "fields_present",
                    "strengthens_sections",
                ):
                    if fund.get(fld) is not None:
                        row[fld] = fund[fld]
                # Ranking expects fraction ROE
                if row.get("roe") is not None and float(row["roe"]) > 1.5:
                    row["roe"] = float(row["roe"]) / 100.0
                if row.get("roic") is not None and float(row["roic"]) > 1.5:
                    row["roic"] = float(row["roic"]) / 100.0
                row.setdefault("method", "fundamentals_import")
        except Exception:  # noqa: BLE001
            pass
    if not row:
        return {}
    out: dict[str, Any] = {
        "roe": row.get("roe"),
        "debt_to_equity": row.get("debt_to_equity", row.get("debt_equity")),
        "source": row.get("source"),
        "as_of": row.get("as_of"),
        "method": row.get("method"),
    }
    for fld in (
        "pe",
        "roic",
        "roce",
        "fcf",
        "operating_margin",
        "net_margin",
        "revenue_cagr",
        "earnings_cagr",
        "promoter_holding",
        "pledge_pct",
        "sector",
        "price",
        "shares",
        "share_count",
        "capex",
        "fcf_growth",
        "discount_rate",
        "evidence_confidence",
        "confidence",
        "evidence_sufficiency",
        "fields_present",
        "strengthens_sections",
    ):
        if row.get(fld) is not None:
            out[fld] = row.get(fld)
    if out.get("shares") is None and out.get("share_count") is not None:
        out["shares"] = out["share_count"]
    return out
