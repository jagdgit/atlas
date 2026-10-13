"""Durable daily OHLCV health — continuous, timestamped, validated, replayable.

P2 first slice: inventory + fail-closed validation of on-disk ``market/bars``.
Does not fetch Yahoo. Does not invent prices. Ranking stays provisional when
``replayable`` is false for the evaluated universe.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "market.bars.health.v1"
STORE_REL = Path("market") / "bars_health"
_log = logging.getLogger("atlas.investment.market_bars_health")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bar_path(data_dir: str | Path, symbol: str) -> Path | None:
    root = Path(data_dir) / "market" / "bars"
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    try:
        from atlas.investment.bar_store import symbol_path

        # The writer's own name (NIFTY → _NSEI.json); a bare index name never
        # matched it, so every NIFTY/BANKNIFTY episode read as unreplayable.
        canonical = symbol_path(data_dir, sym)
        if canonical is not None and canonical.is_file():
            return canonical
    except Exception:  # noqa: BLE001
        pass
    candidates = []
    if sym.endswith(".NS") or sym.endswith(".BO"):
        candidates.append(root / f"{sym}.json")
    else:
        candidates.append(root / f"{sym}.NS.json")
        candidates.append(root / f"{sym}.json")
        candidates.append(root / f"{sym}.BO.json")
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0] if candidates else None


def _parse_day(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def validate_daily_bars_file(path: Path) -> dict[str, Any]:
    """Fail-closed schema + continuity check for one durable daily bar file."""
    out: dict[str, Any] = {
        "version": VERSION,
        "path": str(path),
        "exists": path.is_file(),
        "ok": False,
        "replayable": False,
        "n_bars": 0,
        "first": None,
        "last": None,
        "null_ohlc": 0,
        "non_monotonic": 0,
        "gaps_gt_5d": 0,
        "gap_examples": [],
        "issues": [],
    }
    if not path.is_file():
        out["issues"].append("file_missing")
        return out
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out["issues"].append(f"read_error:{type(exc).__name__}")
        return out
    bars = doc.get("bars") if isinstance(doc, dict) else None
    if not isinstance(bars, list) or not bars:
        out["issues"].append("no_bars")
        return out
    dates: list[date] = []
    null_ohlc = 0
    for b in bars:
        if not isinstance(b, dict):
            out["issues"].append("non_object_bar")
            continue
        d = _parse_day(b.get("date") or b.get("t") or b.get("timestamp"))
        if d is None:
            out["issues"].append("bad_timestamp")
            continue
        dates.append(d)
        for k in ("open", "high", "low", "close"):
            if b.get(k) is None:
                null_ohlc += 1
                break
    dates_sorted = sorted(dates)
    non_mono = 0
    if dates != dates_sorted and dates != list(reversed(dates_sorted)):
        # Allow reverse chronological files; flag true disorder.
        if dates != sorted(dates, reverse=True):
            non_mono = 1
            out["issues"].append("non_monotonic_timestamps")
    gaps = 0
    examples: list[dict[str, Any]] = []
    for a, b in zip(dates_sorted, dates_sorted[1:]):
        delta = (b - a).days
        if delta > 5:
            gaps += 1
            if len(examples) < 8:
                examples.append({"from": a.isoformat(), "to": b.isoformat(), "days": delta})
    out.update(
        {
            "n_bars": len(bars),
            "first": dates_sorted[0].isoformat() if dates_sorted else None,
            "last": dates_sorted[-1].isoformat() if dates_sorted else None,
            "null_ohlc": null_ohlc,
            "non_monotonic": non_mono,
            "gaps_gt_5d": gaps,
            "gap_examples": examples,
        }
    )
    if null_ohlc:
        out["issues"].append("null_ohlc")
    if gaps:
        out["issues"].append("calendar_gaps_gt_5d")
    out["ok"] = not out["issues"]
    # Replayable = present, timed, no nulls, no disorder (gaps for holidays OK if ≤5d)
    out["replayable"] = (
        out["exists"]
        and out["n_bars"] > 0
        and null_ohlc == 0
        and non_mono == 0
        and "bad_timestamp" not in out["issues"]
        and "no_bars" not in out["issues"]
    )
    return out


def assess_symbols(
    data_dir: str | Path | None,
    symbols: Iterable[str],
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"version": VERSION, "ok": False, "reason": "no_data_dir", "symbols": []}
    rows: list[dict[str, Any]] = []
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym:
            continue
        path = bar_path(data_dir, sym)
        row = validate_daily_bars_file(path) if path else {
            "symbol": sym,
            "exists": False,
            "ok": False,
            "replayable": False,
            "issues": ["file_missing"],
        }
        row["symbol"] = sym
        if path is not None:
            row["path"] = str(path)
        rows.append(row)
    n = len(rows)
    n_ok = sum(1 for r in rows if r.get("ok"))
    n_rep = sum(1 for r in rows if r.get("replayable"))
    return {
        "version": VERSION,
        "kind": "MARKET_BARS_HEALTH",
        "as_of_ist": as_of_ist,
        "built_at": _now(),
        "n_symbols": n,
        "n_ok": n_ok,
        "n_replayable": n_rep,
        "all_replayable": bool(n) and n_rep == n,
        "ranking_honest": (
            "historical_evaluation_ready"
            if n and n_rep == n
            else "provisional_ranking — durable OHLCV incomplete or invalid for universe"
        ),
        "symbols": rows,
        "honesty": (
            "Daily bars only. Intraday not assessed here. No live Yahoo fetch. "
            "Holiday gaps ≤5d allowed; larger gaps fail ok but may still be replayable."
        ),
    }


def persist_health(data_dir: str | Path | None, doc: dict[str, Any]) -> dict[str, Any]:
    if not data_dir or not isinstance(doc, dict):
        return {"ok": False, "reason": "missing_args"}
    day = str(doc.get("as_of_ist") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    root = Path(data_dir) / STORE_REL
    path = root / f"{day}.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        (root / "_latest.json").write_text(
            json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
        )
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("bars health persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def assess_and_persist(
    data_dir: str | Path | None,
    symbols: Iterable[str],
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    doc = assess_symbols(data_dir, symbols, as_of_ist=as_of_ist)
    doc["persist"] = persist_health(data_dir, doc)
    return doc
