"""IIP.5 Market Knowledge Graph — Market Program domain graph."""

from __future__ import annotations

from typing import Any

from atlas.investment.mkg.schema import VERSION
from atlas.investment.mkg.seed import ensure_seeded
from atlas.investment.mkg.service import graph_view, neighborhood, who_benefits, why_own
from atlas.investment.mkg.store import load_graph

__all__ = [
    "VERSION",
    "ensure_seeded",
    "financial_cites_for",
    "graph_view",
    "load_graph",
    "mkg_bundle",
    "neighborhood",
    "who_benefits",
    "why_own",
]


def financial_cites_for(
    data_dir: str | None,
    symbol: str,
    *,
    program_id: str = "market_intelligence",
) -> list[dict[str, Any]]:
    """Read-only join to fundamentals store — never invent ratios."""
    if not data_dir:
        return []
    try:
        from atlas.investment.fundamentals import get_symbol

        row = get_symbol(data_dir, symbol, program_id=program_id)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(row, dict):
        return []
    cites: list[dict[str, Any]] = []
    for fld in (
        "roe",
        "roce",
        "roic",
        "debt_to_equity",
        "pe",
        "operating_margin",
        "fcf",
        "promoter_holding",
    ):
        if row.get(fld) is not None:
            cites.append(
                {
                    "field": fld,
                    "value": row[fld],
                    "source": row.get("source") or "fundamentals_import",
                    "as_of": row.get("as_of"),
                }
            )
    return cites


def mkg_bundle(
    data_dir: str | None,
    *,
    symbol: str | None = None,
    theme_id: str | None = None,
    force_reseed: bool = False,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Operator/API helper: ensure seed + optional why-own / who-benefits."""
    graph = ensure_seeded(data_dir, force=force_reseed)
    out: dict[str, Any] = {
        "version": VERSION,
        "graph": graph_view(graph),
    }
    if symbol:
        fin = financial_cites_for(data_dir, symbol, program_id=program_id)
        out["why_own"] = why_own(graph, symbol, financial_cites=fin)
        out["neighborhood"] = neighborhood(graph, symbol=symbol, depth=1)
    if theme_id:
        out["who_benefits"] = who_benefits(graph, theme_id=theme_id)
    return out
