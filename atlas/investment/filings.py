"""Company filings depth (IL.5+) — hermetic refs + operator snapshots.

No scrapes. Atlas attaches **filing references** (title/kind/as_of) for India
learner study — not live NSE/BSE pulls and not invented financial line items.
Operators POST ToS-compliant snapshots when they have a real source.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from atlas.investment.universe import INDEX_NIFTY50, membership

_LOCK = threading.RLock()
_STORE: dict[str, dict[str, Any]] = {}

DEFAULT_PROGRAM = "market_intelligence"
SOURCE_HERMETIC = "hermetic_seed"
SOURCE_OPERATOR = "operator_snapshot"
VERSION = "il.5.filings"

# Illustrative Indian fiscal calendar refs (Mar YE). Not live exchange metadata.
_ANNUAL_AS_OF = "2025-03-31"
_Q_AS_OF = "2025-12-31"
_ANNUAL_TITLE = "Annual Report FY25 (hermetic ref)"
_Q_TITLE = "Quarterly results Q3 FY25 (hermetic ref)"


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s and not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def _hermetic_refs(symbol: str, *, name: str = "") -> list[dict[str, Any]]:
    label = (name or symbol).strip() or symbol
    return [
        {
            "title": _ANNUAL_TITLE.replace("(hermetic ref)", f"— {label} (hermetic ref)"),
            "kind": "annual",
            "as_of": _ANNUAL_AS_OF,
            "url": "",
            "source": SOURCE_HERMETIC,
            "period": "FY25",
        },
        {
            "title": _Q_TITLE.replace("(hermetic ref)", f"— {label} (hermetic ref)"),
            "kind": "quarterly",
            "as_of": _Q_AS_OF,
            "url": "",
            "source": SOURCE_HERMETIC,
            "period": "Q3 FY25",
        },
    ]


def hermetic_filings_for(symbol: str, *, name: str | None = None) -> list[dict[str, Any]]:
    """Hermetic filing refs for one symbol (NIFTY50 or any `.NS` study ticker)."""
    sym = _normalize_symbol(symbol)
    if not sym:
        return []
    label = (name or "").strip()
    if not label:
        for row in membership(INDEX_NIFTY50):
            if str(row.get("symbol") or "").upper() == sym:
                label = str(row.get("name") or "")
                break
    return _hermetic_refs(sym, name=label or sym)


def nifty50_filings_seed() -> dict[str, list[dict[str, Any]]]:
    """Full NIFTY50 hermetic filing-ref map."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in membership(INDEX_NIFTY50):
        sym = str(row["symbol"])
        out[sym] = hermetic_filings_for(sym, name=str(row.get("name") or ""))
    return out


def publish_snapshot(
    rows: dict[str, list[dict[str, Any]] | dict[str, Any]] | list[dict[str, Any]],
    *,
    program_id: str = DEFAULT_PROGRAM,
    source: str = SOURCE_OPERATOR,
    as_of: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Upsert operator filing refs. Shape: ``{symbol: [filing, …]}`` or list of
    ``{symbol, filings: [...]}`` / ``{symbol, title, kind, …}``.
    """
    by_sym: dict[str, list[dict[str, Any]]] = {}

    def _ingest_filing(sym: str, raw: dict[str, Any]) -> None:
        title = str(raw.get("title") or raw.get("name") or "").strip()
        if not title:
            return
        row = {
            "title": title,
            "kind": str(raw.get("kind") or "filing").strip(),
            "as_of": str(raw.get("as_of") or raw.get("date") or "").strip(),
            "url": str(raw.get("url") or "").strip(),
            "source": str(raw.get("source") or source).strip(),
            "period": str(raw.get("period") or "").strip(),
        }
        by_sym.setdefault(sym, []).append(row)

    if isinstance(rows, dict):
        for key, val in rows.items():
            sym = _normalize_symbol(str(key))
            if not sym:
                continue
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _ingest_filing(sym, item)
            elif isinstance(val, dict):
                if isinstance(val.get("filings"), list):
                    for item in val["filings"]:
                        if isinstance(item, dict):
                            _ingest_filing(sym, item)
                else:
                    _ingest_filing(sym, val)
    else:
        for raw in rows or []:
            if not isinstance(raw, dict):
                continue
            sym = _normalize_symbol(str(raw.get("symbol") or ""))
            if not sym:
                continue
            if isinstance(raw.get("filings"), list):
                for item in raw["filings"]:
                    if isinstance(item, dict):
                        _ingest_filing(sym, item)
            else:
                _ingest_filing(sym, raw)

    snap = {
        "program_id": program_id,
        "source": source,
        "as_of": as_of or time.strftime("%Y-%m-%d", time.gmtime()),
        "note": note
        or "Operator / hermetic filing refs — not a live NSE/BSE scrape (MI4/MI5)",
        "symbols": by_sym,
        "count": len(by_sym),
        "updated_at": time.time(),
        "version": VERSION,
    }
    with _LOCK:
        _STORE[program_id] = snap
        _STORE["default"] = snap
    return dict(snap)


def latest_snapshot(program_id: str = DEFAULT_PROGRAM) -> dict[str, Any] | None:
    with _LOCK:
        row = _STORE.get(program_id) or _STORE.get("default")
        return dict(row) if row else None


def clear(program_id: str | None = None) -> None:
    with _LOCK:
        if program_id is None:
            _STORE.clear()
        else:
            _STORE.pop(program_id, None)
            if _STORE.get("default") and program_id != "default":
                # keep default unless explicitly cleared
                pass


def filings_for_symbol(
    symbol: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
    name: str | None = None,
    use_hermetic: bool = True,
) -> list[dict[str, Any]]:
    """Merge operator snapshot (wins) over hermetic refs for one symbol."""
    sym = _normalize_symbol(symbol)
    if not sym:
        return []
    op: list[dict[str, Any]] = []
    snap = latest_snapshot(program_id)
    if snap and isinstance(snap.get("symbols"), dict):
        raw = snap["symbols"].get(sym) or []
        if isinstance(raw, list):
            op = [dict(x) for x in raw if isinstance(x, dict)]
    if op:
        return op
    if use_hermetic:
        return hermetic_filings_for(sym, name=name)
    return []


def enrichment_fact(filings: list[dict[str, Any]] | None) -> str | None:
    """Honest one-liner for company facts when filings refs exist."""
    if not filings:
        return None
    top = filings[0]
    kind = str(top.get("kind") or "filing")
    title = str(top.get("title") or "Filing")
    as_of = str(top.get("as_of") or "")
    source = str(top.get("source") or SOURCE_HERMETIC)
    bit = f"Filing ref: {kind} «{title}»"
    if as_of:
        bit += f" as_of {as_of}"
    bit += f" (source={source}; not a live exchange pull)."
    return bit


def filings_view(
    *,
    symbol: str | None = None,
    program_id: str = DEFAULT_PROGRAM,
    use_hermetic: bool = True,
) -> dict[str, Any]:
    if symbol:
        refs = filings_for_symbol(
            symbol, program_id=program_id, use_hermetic=use_hermetic
        )
        return {
            "symbol": _normalize_symbol(symbol),
            "filings": refs,
            "count": len(refs),
            "program_id": program_id,
            "version": VERSION,
            "note": (
                "Hermetic refs are study placeholders; POST operator snapshots "
                "for ToS-compliant real filing metadata."
            ),
        }
    snap = latest_snapshot(program_id)
    hermetic_n = len(nifty50_filings_seed())
    return {
        "program_id": program_id,
        "snapshot": snap,
        "hermetic_nifty50_symbols": hermetic_n,
        "version": VERSION,
        "note": (
            "Atlas attaches hermetic filing refs to M2 auto-seed; "
            "official NSE/BSE clients remain capability_gap until ToS path exists."
        ),
    }


__all__ = [
    "SOURCE_HERMETIC",
    "SOURCE_OPERATOR",
    "VERSION",
    "clear",
    "enrichment_fact",
    "filings_for_symbol",
    "filings_view",
    "hermetic_filings_for",
    "latest_snapshot",
    "nifty50_filings_seed",
    "publish_snapshot",
]
