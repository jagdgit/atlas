"""OI-CF0 / CF.1 — Counterfactual Learning (decision vs alternatives).

After material buys, schedule +30d (required) panels:
  actual · cash (0) · index (^NSEI) · top-ranked alternative (excluding self).

Deterministic return math only — missing prices → verdict unknown.
Never invents returns.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.counterfactual_learning")
VERSION = "cf1.counterfactual.v1"
STORE_REL = Path("investment") / "counterfactuals"
_IST = ZoneInfo("Asia/Kolkata")

# Locked: +30 required; +7/+90 optional (A12)
HORIZON_DAYS: tuple[int, ...] = (30,)
OPTIONAL_HORIZONS: tuple[int, ...] = (7, 90)
MATCHED_BAND_PCT = 0.5  # |excess| ≤ 0.5pp → matched

PriceFn = Callable[[str, str], float | None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_^." else "_" for c in (s or ""))


def ist_today(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def _by_id_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    d = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pct_return(px0: float | None, px1: float | None) -> float | None:
    if px0 is None or px1 is None:
        return None
    try:
        a = float(px0)
        b = float(px1)
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round(100.0 * (b - a) / a, 4)


def close_on_bars(bars: list[dict[str, Any]] | None, ist_day: str) -> float | None:
    """Closest available close on or before ist_day (never invent)."""
    day = str(ist_day)[:10]
    best: tuple[str, float] | None = None
    for b in bars or []:
        if not isinstance(b, dict) or b.get("close") is None:
            continue
        d = str(b.get("date") or b.get("t") or "")[:10]
        if not d or d > day:
            continue
        try:
            px = float(b["close"])
        except (TypeError, ValueError):
            continue
        if best is None or d >= best[0]:
            best = (d, px)
    return best[1] if best else None


def default_price_fn(data_dir: str | Path | None) -> PriceFn | None:
    if not data_dir:
        return None

    def _fn(symbol: str, ist_day: str) -> float | None:
        try:
            from atlas.investment.bar_store import load_bars
            from atlas.investment.symbol_aliases import resolve_yahoo_symbol

            canon = resolve_yahoo_symbol(symbol).canonical or symbol
            bars = load_bars(data_dir, canon) or load_bars(data_dir, symbol)
            return close_on_bars(bars, ist_day)
        except Exception:  # noqa: BLE001
            return None

    return _fn


def pick_top_alternative(
    symbol: str,
    *,
    program_id: str = "market_intelligence",
    ranked: list[dict[str, Any]] | None = None,
    max_n: int = 30,
) -> dict[str, Any] | None:
    """Rank#1 available that day excluding self (A13)."""
    rows = list(ranked or [])
    if not rows:
        try:
            from atlas.investment import watchlists as wl

            rows = list(wl.ranked_rows(program_id, max_n=max_n) or [])
        except Exception:  # noqa: BLE001
            rows = []
    self_u = str(symbol or "").strip().upper()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        alt = str(r.get("symbol") or "").strip()
        if not alt:
            continue
        if alt.upper() == self_u:
            continue
        return {
            "symbol": alt,
            "rank": r.get("rank") if r.get("rank") is not None else i + 1,
            "name": r.get("name"),
            "sector": r.get("sector"),
        }
    return None


def _schedule_horizons(
    entry_ist: str, *, include_optional: bool = False
) -> list[dict[str, Any]]:
    base = date.fromisoformat(str(entry_ist)[:10])
    days = list(HORIZON_DAYS)
    if include_optional:
        days = sorted(set(days) | set(OPTIONAL_HORIZONS))
    rows: list[dict[str, Any]] = []
    for d in days:
        rows.append(
            {
                "horizon_d": int(d),
                "due_ist": (base + timedelta(days=int(d))).isoformat(),
                "status": "pending",
                "completed_at": None,
                "actual_return": None,
                "cash_return": 0.0,
                "index_return": None,
                "alt_return": None,
                "excess_vs_cash": None,
                "excess_vs_index": None,
                "excess_vs_alt": None,
                "verdict": None,
                "note": None,
            }
        )
    return rows


def schedule_cf(
    data_dir: str | Path | None,
    *,
    decision_id: str | None,
    symbol: str,
    action: str = "buy",
    entry_price: float | None = None,
    entry_ist: str | None = None,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    program_id: str = "market_intelligence",
    index_symbol: str | None = None,
    alt: dict[str, Any] | None = None,
    ranked: list[dict[str, Any]] | None = None,
    include_optional_horizons: bool = False,
) -> dict[str, Any] | None:
    """Schedule counterfactual panels for a material buy (durable)."""
    if not data_dir:
        return None
    act = str(action or "").lower()
    if act not in {"buy", "sell"}:
        return None
    # CF.1 primary path = buys (decision to own vs alternatives)
    if act != "buy":
        return None
    sym = str(symbol or "").strip()
    if not sym:
        return None
    try:
        px = float(entry_price) if entry_price is not None else None
    except (TypeError, ValueError):
        px = None
    if px is None or px <= 0:
        return None

    lab = laboratory_id or portfolio_key or "india_equity_learner"
    day = entry_ist or ist_today()
    from atlas.investment.symbol_aliases import resolve_yahoo_symbol

    idx = index_symbol or resolve_yahoo_symbol("NIFTY").yahoo
    alt_row = alt if isinstance(alt, dict) else pick_top_alternative(
        sym, program_id=program_id, ranked=ranked
    )

    cf_id = str(uuid4())
    row: dict[str, Any] = {
        "cf_id": cf_id,
        "version": VERSION,
        "created_at": _now(),
        "decision_id": decision_id,
        "action": act,
        "symbol": sym,
        "laboratory_id": lab,
        "portfolio_key": portfolio_key or lab,
        "entry_ist": day,
        "entry_price": px,
        "index_symbol": idx,
        "alt_symbol": (alt_row or {}).get("symbol"),
        "alt_rank": (alt_row or {}).get("rank"),
        "horizons": _schedule_horizons(day, include_optional=include_optional_horizons),
        "status": "open",
    }
    path = _by_id_dir(data_dir, lab) / f"{cf_id}.json"
    try:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("CF schedule write failed", exc_info=True)
        return None
    row["path"] = str(path)
    return row


def list_cfs(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = _by_id_dir(data_dir, laboratory_id)
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        if len(rows) >= limit:
            break
    return rows


def _verdict(
    actual: float | None, alt: float | None, index: float | None
) -> str:
    """Prefer comparison vs top alternative; fall back to index; else cash."""
    if actual is None:
        return "unknown"
    if alt is not None:
        excess = actual - alt
        if abs(excess) <= MATCHED_BAND_PCT:
            return "matched"
        return "beat" if excess > 0 else "lost"
    if index is not None:
        excess = actual - index
        if abs(excess) <= MATCHED_BAND_PCT:
            return "matched"
        return "beat" if excess > 0 else "lost"
    # vs cash only
    if abs(actual) <= MATCHED_BAND_PCT:
        return "matched"
    return "beat" if actual > 0 else "lost"


def evaluate_due_cfs(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    price_fn: PriceFn | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Drain due CF horizons. Never invents prices."""
    as_of = as_of_ist or ist_today()
    pfn = price_fn or default_price_fn(data_dir)
    completed = 0
    missing = 0
    scanned = 0
    updated: list[dict[str, Any]] = []
    for row in list_cfs(data_dir, laboratory_id=laboratory_id, limit=200):
        if scanned >= limit and completed == 0:
            # still scan a bit for dues
            pass
        changed = False
        sym = str(row.get("symbol") or "")
        idx = str(row.get("index_symbol") or "^NSEI")
        alt = str(row.get("alt_symbol") or "") or None
        entry_day = str(row.get("entry_ist") or "")[:10]
        entry_px = row.get("entry_price")
        horizons = list(row.get("horizons") or [])
        for h in horizons:
            if not isinstance(h, dict) or h.get("status") != "pending":
                continue
            due = str(h.get("due_ist") or "")[:10]
            if not due or due > as_of:
                continue
            scanned += 1
            if pfn is None:
                h["status"] = "missing_prices"
                h["note"] = "no price_fn"
                h["verdict"] = "unknown"
                missing += 1
                changed = True
                continue
            px1 = pfn(sym, due)
            # Prefer entry_price freeze; else bar on entry day
            try:
                px0 = float(entry_px) if entry_px is not None else pfn(sym, entry_day)
            except (TypeError, ValueError):
                px0 = pfn(sym, entry_day)
            actual = _pct_return(px0, px1)
            idx0 = pfn(idx, entry_day)
            idx1 = pfn(idx, due)
            index_ret = _pct_return(idx0, idx1)
            alt_ret = None
            if alt:
                alt_ret = _pct_return(pfn(alt, entry_day), pfn(alt, due))
            if actual is None or (index_ret is None and alt_ret is None and px1 is None):
                h["status"] = "missing_prices"
                h["note"] = "missing bar closes"
                h["verdict"] = "unknown"
                missing += 1
                changed = True
                continue
            h["actual_return"] = actual
            h["cash_return"] = 0.0
            h["index_return"] = index_ret
            h["alt_return"] = alt_ret
            h["excess_vs_cash"] = (
                round(actual - 0.0, 4) if actual is not None else None
            )
            h["excess_vs_index"] = (
                round(actual - index_ret, 4)
                if actual is not None and index_ret is not None
                else None
            )
            h["excess_vs_alt"] = (
                round(actual - alt_ret, 4)
                if actual is not None and alt_ret is not None
                else None
            )
            h["verdict"] = _verdict(actual, alt_ret, index_ret)
            h["status"] = "done"
            h["completed_at"] = _now()
            completed += 1
            changed = True
        if changed:
            row["horizons"] = horizons
            # Close CF when all horizons terminal
            pending = [
                h
                for h in horizons
                if isinstance(h, dict) and h.get("status") == "pending"
            ]
            if not pending:
                row["status"] = "closed"
            path = _by_id_dir(data_dir, laboratory_id) / f"{row.get('cf_id')}.json"
            try:
                path.write_text(
                    json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            except Exception:  # noqa: BLE001
                _log.debug("CF evaluate write failed", exc_info=True)
            updated.append(row)
        if completed >= limit:
            break
    return {
        "version": VERSION,
        "as_of_ist": as_of,
        "completed": completed,
        "missing_prices": missing,
        "updated": len(updated),
        "rows": updated[:10],
    }


def format_counterfactual_section(
    rows: list[dict[str, Any]] | None,
    *,
    limit: int = 8,
) -> list[str]:
    """Evening: beat / matched / lost vs alternative (or index)."""
    lines = ["", "--- Counterfactuals (CF.1) ---"]
    done: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for h in row.get("horizons") or []:
            if isinstance(h, dict) and h.get("status") == "done":
                done.append((row, h))
    if not done:
        lines.append(
            "No completed counterfactual horizons yet "
            "(+30d after material buys; missing prices stay unknown)."
        )
        return lines
    for row, h in done[:limit]:
        sym = row.get("symbol")
        alt = row.get("alt_symbol") or "—"
        verdict = h.get("verdict") or "unknown"
        actual = h.get("actual_return")
        alt_r = h.get("alt_return")
        idx_r = h.get("index_return")
        hz = h.get("horizon_d")
        lines.append(
            f"{sym} +{hz}d: {verdict} vs alt={alt} "
            f"(actual={actual}% · alt={alt_r}% · index={idx_r}% · cash=0%)"
        )
    return lines


def format_counterfactual_evening_lines(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 8,
) -> list[str]:
    rows = list_cfs(data_dir, laboratory_id=laboratory_id, limit=80)
    return format_counterfactual_section(rows, limit=limit)
