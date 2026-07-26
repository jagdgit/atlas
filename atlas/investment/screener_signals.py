"""Screener-class signals (IL.8) — operator snapshots + bars/quality derived scores.

No scrapes. Prefer operator-supplied JSON or ToS-compliant APIs later.
In-process store (same pattern as watchlists) keyed by program_id.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.RLock()
_STORE: dict[str, dict[str, Any]] = {}

DEFAULT_PROGRAM = "market_intelligence"
SOURCE_OPERATOR = "operator_snapshot"
SOURCE_COMPUTED = "computed_bars_quality"
VERSION = "il.8"


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s and not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def publish_snapshot(
    rows: dict[str, dict[str, Any]] | list[dict[str, Any]],
    *,
    program_id: str = DEFAULT_PROGRAM,
    source: str = SOURCE_OPERATOR,
    as_of: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Upsert an operator (or API) screener snapshot for a Program."""
    by_sym: dict[str, dict[str, Any]] = {}
    if isinstance(rows, dict):
        iterable = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in rows.items()]
    else:
        iterable = [r for r in rows if isinstance(r, dict)]
    for raw in iterable:
        sym = _normalize_symbol(str(raw.get("symbol") or ""))
        if not sym:
            continue
        payload = {k: v for k, v in raw.items() if k != "symbol"}
        payload["symbol"] = sym
        payload.setdefault("source", source)
        if as_of:
            payload["as_of"] = as_of
        by_sym[sym] = payload
    snap = {
        "program_id": program_id,
        "source": source,
        "as_of": as_of or time.strftime("%Y-%m-%d", time.gmtime()),
        "note": note or "Hermetic / operator snapshot — not a live scrape",
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
            if _STORE.get("default", {}).get("program_id") == program_id:
                _STORE.pop("default", None)


def compute_from_bars_quality(
    *,
    bars_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    quality_by_symbol: dict[str, dict[str, Any]] | None = None,
    symbols: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Derive screener-class signal rows from bars + quality (no network)."""
    bars_by_symbol = bars_by_symbol or {}
    quality_by_symbol = quality_by_symbol or {}
    syms = list(symbols or [])
    if not syms:
        syms = sorted(set(list(bars_by_symbol) + list(quality_by_symbol)))
    out: dict[str, dict[str, Any]] = {}
    for sym in syms:
        key = _normalize_symbol(sym)
        bars = bars_by_symbol.get(key) or bars_by_symbol.get(sym) or []
        q = quality_by_symbol.get(key) or quality_by_symbol.get(sym) or {}
        signals: dict[str, Any] = {}
        score_parts: list[float] = []

        # Relative volume vs prior window
        vols = []
        for b in bars[-20:]:
            try:
                vols.append(float(b.get("volume") or 0.0))
            except (TypeError, ValueError):
                continue
        if len(vols) >= 5:
            recent = sum(vols[-5:]) / 5.0
            base = sum(vols[:-5]) / max(1, len(vols) - 5)
            if base > 0:
                rel_vol = recent / base
                signals["rel_volume"] = round(rel_vol, 4)
                # 0.5x→0.2, 1x→0.5, 2x→0.9
                score_parts.append(_clamp01(0.2 + (rel_vol - 0.5) * 0.4))

        closes = []
        for b in bars[-21:]:
            try:
                closes.append(float(b["close"]))
            except (TypeError, ValueError, KeyError):
                continue
        if len(closes) >= 6:
            short = (closes[-1] / closes[-6] - 1.0) if closes[-6] else 0.0
            signals["mom_5d"] = round(short, 4)
            score_parts.append(_clamp01(0.5 + short * 2.0))

        if "roe" in q:
            try:
                roe = float(q["roe"])
                signals["roe"] = roe
            except (TypeError, ValueError):
                pass
        if "debt_to_equity" in q or "debt_equity" in q:
            try:
                de = float(q.get("debt_to_equity", q.get("debt_equity")))
                signals["debt_to_equity"] = de
            except (TypeError, ValueError):
                pass

        # Score only from market/tape signals — avoid double-counting IL.5 quality in ranker
        if not score_parts:
            continue
        score = sum(score_parts) / len(score_parts)
        out[key] = {
            "symbol": key,
            "signals": signals,
            "score": round(score, 4),
            "source": SOURCE_COMPUTED,
            "method": "bars_quality",
        }
    return out


def merge_into_quality(
    quality_by_symbol: dict[str, dict[str, Any]] | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    bars_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    use_computed: bool = True,
    config_snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Merge operator snapshot (+ optional computed) into quality map for ranking.

    Returns ``(merged_quality, meta)`` where meta has counts / sources.
    """
    base = { _normalize_symbol(k): dict(v) for k, v in (quality_by_symbol or {}).items()
             if isinstance(v, dict) }
    meta: dict[str, Any] = {
        "operator_count": 0,
        "computed_count": 0,
        "merged_count": 0,
        "sources": [],
        "version": VERSION,
    }

    snap = None
    if isinstance(config_snapshot, dict) and (
        config_snapshot.get("symbols") or config_snapshot.get("rows")
    ):
        # Ephemeral config body
        rows = config_snapshot.get("symbols") or config_snapshot.get("rows")
        snap = publish_snapshot(
            rows if isinstance(rows, (dict, list)) else {},
            program_id=program_id,
            source=str(config_snapshot.get("source") or SOURCE_OPERATOR),
            as_of=config_snapshot.get("as_of"),
            note=str(config_snapshot.get("note") or ""),
        )
    else:
        snap = latest_snapshot(program_id)

    if snap and isinstance(snap.get("symbols"), dict):
        meta["operator_count"] = len(snap["symbols"])
        meta["sources"].append(str(snap.get("source") or SOURCE_OPERATOR))
        for sym, row in snap["symbols"].items():
            if not isinstance(row, dict):
                continue
            key = _normalize_symbol(sym)
            cur = dict(base.get(key) or {})
            # Map screener fields into quality / explicit score
            for fld in ("roe", "debt_to_equity", "debt_equity", "pe", "promoter_holding"):
                if fld in row and row[fld] is not None:
                    cur[fld] = row[fld]
            if row.get("screener_score") is not None:
                cur["screener_score"] = row["screener_score"]
            elif "score" in row and row["score"] is not None:
                cur["screener_score"] = row["score"]
            elif isinstance(row.get("signals"), dict) and "score" in row["signals"]:
                cur["screener_score"] = row["signals"]["score"]
            cur["screener_source"] = row.get("source") or snap.get("source") or SOURCE_OPERATOR
            cur["screener_as_of"] = row.get("as_of") or snap.get("as_of")
            base[key] = cur

    if use_computed:
        computed = compute_from_bars_quality(
            bars_by_symbol=bars_by_symbol,
            quality_by_symbol=base,
        )
        meta["computed_count"] = len(computed)
        if computed:
            meta["sources"].append(SOURCE_COMPUTED)
        for sym, row in computed.items():
            cur = dict(base.get(sym) or {})
            # Only fill screener_score when operator didn't set one
            if "screener_score" not in cur:
                cur["screener_score"] = row.get("score")
                cur["screener_source"] = SOURCE_COMPUTED
            # Attach computed signals for WHY / company facts
            cur["screener_signals"] = row.get("signals") or {}
            base[sym] = cur

    meta["merged_count"] = sum(
        1 for v in base.values() if v.get("screener_score") is not None or v.get("pe") is not None
        or v.get("promoter_holding") is not None or v.get("screener_source")
    )
    return base, meta


def signals_view(program_id: str = DEFAULT_PROGRAM) -> dict[str, Any]:
    """Operator-facing GET payload."""
    snap = latest_snapshot(program_id)
    if not snap:
        return {
            "program_id": program_id,
            "symbols": {},
            "count": 0,
            "note": "No screener snapshot — POST /v1/market/screener-snapshot",
            "version": VERSION,
        }
    return {
        "program_id": snap.get("program_id"),
        "source": snap.get("source"),
        "as_of": snap.get("as_of"),
        "note": snap.get("note"),
        "symbols": snap.get("symbols") or {},
        "count": snap.get("count") or 0,
        "updated_at": snap.get("updated_at"),
        "version": VERSION,
    }


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


def quality_enrichment_fact(row: dict[str, Any]) -> str | None:
    """Honest one-liner for company auto-seed facts."""
    src = row.get("screener_source") or row.get("source")
    if not src:
        return None
    bits = []
    if row.get("pe") is not None:
        bits.append(f"PE≈{row['pe']}")
    if row.get("promoter_holding") is not None:
        try:
            ph = float(row["promoter_holding"])
            bits.append(f"promoter≈{ph * 100:.0f}%" if ph <= 1.5 else f"promoter≈{ph:.0f}%")
        except (TypeError, ValueError):
            pass
    if row.get("screener_score") is not None:
        bits.append(f"screener_score={row['screener_score']}")
    if not bits:
        return f"Screener signal present (source={src}; not a live scrape)."
    return f"Screener fields ({', '.join(bits)}; source={src}; not a live scrape)."
