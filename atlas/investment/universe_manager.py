"""IIP.1 Universe Manager — list / union / enable multi-set membership.

Extends static packs in ``universe.py``. Enabled sets are durable under
``data/investment/universes/enabled.json`` so Programs can watch NEXT50∪Midcap
without rewriting paper-trading instrument lists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.investment import universe as uni

_log = logging.getLogger("atlas.investment.universe_manager")

STORE_REL = Path("investment") / "universes" / "enabled.json"
DEFAULT_ENABLED = [uni.INDEX_NIFTY50]


def store_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def list_universe_defs() -> list[dict[str, Any]]:
    """Catalog of known universes (index / theme / operator families)."""
    from atlas.investment.themes import list_themes, theme_universe_id

    defs: list[dict[str, Any]] = []
    for uid in uni.KNOWN_INDICES:
        try:
            rows = uni.membership(uid)
        except KeyError:
            rows = []
        meta = uni.universe_meta(uid)
        defs.append(
            {
                "id": uid,
                "family": meta.get("family") or "index",
                "label": meta.get("label") or uid,
                "count": len(rows),
                "staged": bool(meta.get("staged")),
                "note": meta.get("note") or "",
                "default_enabled": uid == uni.INDEX_NIFTY50,
            }
        )
    for theme in list_themes():
        uid = theme_universe_id(theme["theme_id"])
        defs.append(
            {
                "id": uid,
                "family": "theme",
                "label": f"Theme · {theme.get('label')}",
                "count": int(theme.get("count") or 0),
                "staged": True,
                "note": theme.get("hypothesis") or "",
                "default_enabled": False,
                "theme_id": theme["theme_id"],
            }
        )
    return defs


def load_enabled(data_dir: str | Path | None) -> list[str]:
    if not data_dir:
        return list(DEFAULT_ENABLED)
    path = store_path(data_dir)
    if not path.is_file():
        return list(DEFAULT_ENABLED)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ids = raw.get("enabled") if isinstance(raw, dict) else raw
        if not isinstance(ids, list) or not ids:
            return list(DEFAULT_ENABLED)
        out = [str(x).strip().upper() for x in ids if str(x).strip()]
        return out or list(DEFAULT_ENABLED)
    except Exception:  # noqa: BLE001
        _log.debug("enabled universes read failed", exc_info=True)
        return list(DEFAULT_ENABLED)


def save_enabled(data_dir: str | Path | None, enabled: list[str]) -> dict[str, Any]:
    ids = [str(x).strip().upper() for x in (enabled or []) if str(x).strip()]
    if not ids:
        ids = list(DEFAULT_ENABLED)
    # Always keep at least one resolvable index
    known = {d["id"] for d in list_universe_defs()}
    ids = [i for i in ids if i in known or i in set(uni.KNOWN_INDICES)]
    if not ids:
        ids = list(DEFAULT_ENABLED)
    doc = {"enabled": ids, "version": "iip.1"}
    if data_dir:
        path = store_path(data_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            _log.debug("enabled universes write failed", exc_info=True)
    return doc


def resolve_members(
    *,
    index: str | None = None,
    universes: list[str] | None = None,
    extra_members: list[dict[str, Any]] | None = None,
    data_dir: str | Path | None = None,
    max_members: int | None = None,
) -> dict[str, Any]:
    """Union membership for one index or many universe ids.

    Prefer ``universes`` when provided; else ``index``; else durable enabled set
    (or NIFTY50).
    """
    ids: list[str] = []
    if universes:
        ids = [str(u).strip().upper() for u in universes if str(u).strip()]
    elif index:
        ids = [str(index).strip().upper()]
    elif data_dir:
        ids = load_enabled(data_dir)
    else:
        ids = list(DEFAULT_ENABLED)

    rows: list[dict[str, Any]] = []
    used: list[str] = []
    skipped: list[dict[str, str]] = []
    for uid in ids:
        if uid.startswith("THEME_"):
            from atlas.investment.themes import get_theme

            theme = get_theme(uid)
            if not theme:
                skipped.append({"id": uid, "reason": "unknown_theme"})
                continue
            used.append(uid)
            part = [
                {
                    "symbol": s,
                    "nse_symbol": s.replace(".NS", ""),
                    "name": s,
                    "sector": theme.get("label") or "Theme",
                    "exchange": "NSE",
                    "asset_class": "cash_equity",
                    "theme_id": theme.get("theme_id"),
                }
                for s in (theme.get("symbols") or [])
            ]
            rows = uni.merge_unique(rows, part)
            continue
        try:
            part = uni.membership(uid, extra_members=None)
        except KeyError:
            skipped.append({"id": uid, "reason": "unknown_universe"})
            continue
        used.append(uid)
        rows = uni.merge_unique(rows, part)

    if extra_members:
        rows = uni.membership(
            "CUSTOM" if not rows else used[0] if used else uni.INDEX_NIFTY50,
            extra_members=extra_members,
        ) if not rows else _append_extras(rows, extra_members)

    if max_members is not None and max_members > 0 and len(rows) > max_members:
        rows = rows[: int(max_members)]

    return {
        "universes": used,
        "requested": ids,
        "skipped": skipped,
        "members": rows,
        "count": len(rows),
        "version": "iip.1",
    }


def _append_extras(
    rows: list[dict[str, Any]], extras: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    have = {r.get("symbol") for r in rows}
    out = list(rows)
    for raw in extras:
        if not isinstance(raw, dict):
            continue
        sym = str(raw.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if not sym.endswith(".NS") and "." not in sym:
            sym = f"{sym}.NS"
        if sym in have:
            continue
        out.append(
            {
                "symbol": sym,
                "nse_symbol": str(raw.get("nse_symbol") or sym.replace(".NS", "")),
                "name": str(raw.get("name") or sym),
                "sector": str(raw.get("sector") or ""),
                "exchange": str(raw.get("exchange") or "NSE"),
                "asset_class": str(raw.get("asset_class") or "cash_equity"),
            }
        )
        have.add(sym)
    return out


def universes_view(data_dir: str | Path | None = None) -> dict[str, Any]:
    enabled = load_enabled(data_dir)
    defs = list_universe_defs()
    for d in defs:
        d["enabled"] = d["id"] in enabled
    resolved = resolve_members(universes=enabled, data_dir=data_dir)
    return {
        "universes": defs,
        "enabled": enabled,
        "union_count": resolved["count"],
        "union_universes": resolved["universes"],
        "skipped": resolved["skipped"],
        "caps": {
            "max_active_research_default": 50,
            "max_trade_set_default": 15,
            "max_watchlist_default": 15,
        },
        "version": "iip.1",
        "note": (
            "Enable NEXT50 / Midcap / Smallcap to broaden discovery. "
            "Active research/trade sets stay capped — membership ≠ permission to buy."
        ),
    }
