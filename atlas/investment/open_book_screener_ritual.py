"""DP-FUND3 — weekly Screener densify ritual for open-book holdings.

Operator exports Screener CSV (ToS-safe); Atlas never scrapes Screener HTML.
This helper stages a gap-fill template under ``imports/fundamentals/`` so the
Sunday evening (or any) ritual is one command away.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
VERSION = "dp.fund3.open_book_screener_ritual"


def stage_open_book_screener_template(
    data_dir: str | Path | None,
    *,
    portfolio: Any | None = None,
    portfolio_key: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    only_gaps: bool = True,
    limit: int = 40,
    symbols: list[str] | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Write open-book PE/FCF gap CSV into ``imports/fundamentals/``.

    Returns path + row counts. Empty cells stay empty — never invents ratios.
    """
    from atlas.investment.fundamentals import (
        import_drop_dir,
        learner_gap_fill_template,
    )
    from atlas.investment.open_book_packs import resolve_open_symbols

    root = Path(data_dir) if data_dir else None
    if root is None:
        return {
            "version": VERSION,
            "ok": False,
            "reason": "no_data_dir",
            "honesty": "Need Atlas data_dir to stage Screener gap template.",
        }

    want: list[str] = []
    if symbols:
        want = [str(s).strip() for s in symbols if str(s).strip()]
    elif portfolio is not None:
        try:
            want = resolve_open_symbols(
                portfolio=portfolio,
                portfolio_key=str(portfolio_key or "india_equity_learner"),
                limit=max(1, min(int(limit or 40), 80)),
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "version": VERSION,
                "ok": False,
                "reason": f"open_symbols:{type(exc).__name__}",
                "honesty": "Could not resolve open-book symbols from portfolio.",
            }

    # Flat book: still stage Next-₹1 / UQ challengers (Zerodha ≠ PE densify).
    if not want:
        try:
            from atlas.investment.fundamentals import resolve_material_challenger_symbols

            want = resolve_material_challenger_symbols(
                root,
                laboratory_id=str(portfolio_key or "india_equity_learner"),
                limit=max(1, min(int(limit or 40), 8)),
            )
        except Exception:  # noqa: BLE001
            want = []

    tmpl = learner_gap_fill_template(
        root,
        want,
        program_id=program_id,
        only_gaps=bool(only_gaps),
    )
    drop = import_drop_dir(root)
    drop.mkdir(parents=True, exist_ok=True)
    dt = as_of or datetime.now(_IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    else:
        dt = dt.astimezone(_IST)
    fname = f"open_book_screener_{dt.date().isoformat()}.csv"
    path = drop / fname
    csv_text = str(tmpl.get("csv") or "")
    path.write_text(csv_text, encoding="utf-8")

    return {
        "version": VERSION,
        "ok": True,
        "path": str(path),
        "filename": fname,
        "row_count": int(tmpl.get("row_count") or 0),
        "symbols_requested": int(tmpl.get("symbols_requested") or 0),
        "portfolio_key": portfolio_key,
        "program_id": program_id,
        "only_gaps": bool(only_gaps),
        "ritual": (
            "1) Fill empty pe/fcf/roe/debt_to_equity from Screener export "
            f"2) Leave file in {drop} or paste via Invest intel "
            "3) POST /v1/market/fundamentals/import-drop (or Import paste)"
        ),
        "honesty": (
            "Weekly open-book densify — Atlas does not scrape Screener.in. "
            "Empty cells stay unknown until you import."
        ),
        "template": {
            "row_count": tmpl.get("row_count"),
            "gaps": tmpl.get("gaps"),
        },
    }
