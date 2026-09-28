"""LOOP0 L5 — durable 5-minute bars for the equity intraday lab.

Never mix into daily ``market/bars``. Yahoo 1m is a later OI (OI-FEED-1M).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "loop0.l5.bars_intraday.v1"
INTERVAL = "5m"
RANGE = "1d"
MAX_SYMBOLS = 3
CACHE_TTL_S = 60.0
VALUATION_BASIS = "yahoo 5m session bars"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.intraday_bars")


def is_intraday_lab(cfg: dict[str, Any] | None, portfolio_key: str | None = None) -> bool:
    cfg = cfg or {}
    pk = str(portfolio_key or cfg.get("portfolio_key") or "").strip().lower()
    horizon = ""
    person = cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}
    horizon = str(person.get("time_horizon") or cfg.get("time_horizon") or "").strip().lower()
    return "intraday" in pk or horizon == "intraday"


def ist_session_date(now: datetime | None = None) -> str:
    clock = now or datetime.now(_IST)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc).astimezone(_IST)
    else:
        clock = clock.astimezone(_IST)
    return clock.strftime("%Y-%m-%d")


def _canonical_symbol(symbol: str) -> str:
    try:
        from atlas.investment.symbol_aliases import resolve_yahoo_symbol

        return str(resolve_yahoo_symbol(symbol).canonical or symbol or "").strip().upper()
    except Exception:  # noqa: BLE001
        return str(symbol or "").strip().upper()


def _safe_symbol_dir(symbol: str) -> str:
    return _canonical_symbol(symbol).replace("/", "_").replace("^", "_")


def day_path(
    data_dir: str | Path | None, symbol: str, *, ist_date: str | None = None
) -> Path | None:
    if not data_dir:
        return None
    sym = _safe_symbol_dir(symbol)
    if not sym:
        return None
    day = ist_date or ist_session_date()
    return Path(data_dir) / "market" / "bars_intraday" / sym / f"{day}.json"


def _bar_ist_date(bar: dict[str, Any] | None) -> str | None:
    """IST calendar date of a 5m bar, or None when the timestamp is not a real clock."""
    if not isinstance(bar, dict):
        return None
    raw = bar.get("date")
    if raw is not None:
        s = str(raw).strip()
        if "T" in s:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_IST)
                return dt.astimezone(_IST).strftime("%Y-%m-%d")
            except ValueError:
                if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                    return s[:10]
        elif len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
    t = bar.get("t")
    if t is None:
        return None
    try:
        n = float(t)
    except (TypeError, ValueError):
        s = str(t).strip()
        if "T" in s or (len(s) >= 10 and s[4] == "-" and s[7] == "-"):
            return _bar_ist_date({"date": s})
        return None
    if n > 1e12:
        n /= 1000.0
    if n < 1e9:
        return None  # synthetic L5 test keys, not unix epoch
    dt = datetime.fromtimestamp(n, tz=timezone.utc).astimezone(_IST)
    return dt.strftime("%Y-%m-%d")


def _bar_key(bar: dict[str, Any]) -> str:
    if bar.get("t") is not None:
        return str(bar["t"])
    return str(bar.get("date") or "")


def _normalize(bar: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bar, dict) or bar.get("close") is None:
        return None
    try:
        close = float(bar["close"])
    except (TypeError, ValueError):
        return None
    key = _bar_key(bar)
    if not key:
        return None
    out = {
        "t": bar.get("t", key),
        "open": float(bar["open"]) if bar.get("open") is not None else close,
        "high": float(bar["high"]) if bar.get("high") is not None else close,
        "low": float(bar["low"]) if bar.get("low") is not None else close,
        "close": close,
        "volume": float(bar["volume"]) if bar.get("volume") is not None else 0.0,
    }
    if bar.get("date"):
        out["date"] = bar.get("date")
    return out


def merge_intraday_bars(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_t: dict[str, dict[str, Any]] = {}
    for bar in list(existing or []) + list(incoming or []):
        norm = _normalize(bar) if isinstance(bar, dict) else None
        if not norm:
            continue
        by_t[_bar_key(norm)] = norm

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        k, _ = item
        try:
            return (0, f"{int(float(k)):020d}")
        except (TypeError, ValueError):
            return (1, k)

    return [by_t[k] for k, _ in sorted(by_t.items(), key=_sort_key)]


def load_day_bars(
    data_dir: str | Path | None,
    symbol: str,
    *,
    ist_date: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = day_path(data_dir, symbol, ist_date=ist_date)
    if path is None or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _log.debug("intraday bars read failed: %s", path, exc_info=True)
        return []
    bars = raw.get("bars") if isinstance(raw, dict) else None
    if not isinstance(bars, list):
        return []
    out = [b for b in bars if isinstance(b, dict)]
    if limit is not None and int(limit) > 0:
        out = out[-int(limit) :]
    return out


def persist_day_bars(
    data_dir: str | Path | None,
    symbol: str,
    bars: list[dict[str, Any]] | None,
    *,
    ist_date: str | None = None,
    provider: str = "yahoo",
    interval: str = INTERVAL,
) -> dict[str, Any]:
    path = day_path(data_dir, symbol, ist_date=ist_date)
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = load_day_bars(data_dir, symbol, ist_date=ist_date)
    merged = merge_intraday_bars(prior, bars or [])
    doc = {
        "version": VERSION,
        "symbol": _canonical_symbol(symbol),
        "ist_date": ist_date or ist_session_date(),
        "interval": interval,
        "provider": provider,
        "last_write_provider": provider,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "bar_count": len(merged),
        "bars": merged,
    }
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    _touch_session_index(
        data_dir,
        symbol,
        doc["ist_date"],
        bar_count=len(merged),
        provider=provider,
        interval=interval,
    )
    return {"ok": True, "path": str(path), "bar_count": len(merged), "ist_date": doc["ist_date"]}


def persist_session_tape(
    data_dir: str | Path | None,
    symbol: str,
    bars: list[dict[str, Any]] | None,
    *,
    provider: str = "zerodha",
    interval: str = INTERVAL,
) -> dict[str, Any]:
    """Split 5m bars onto IST session files so yesterday remains reloadable."""
    if not data_dir:
        return {"ok": False, "reason": "no_data_dir", "days": []}
    fallback = ist_session_date()
    groups: dict[str, list[dict[str, Any]]] = {}
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        day = _bar_ist_date(bar) or fallback
        groups.setdefault(day, []).append(bar)
    if not groups:
        return {"ok": False, "reason": "no_bars", "days": []}
    written: list[dict[str, Any]] = []
    total = 0
    for day in sorted(groups):
        row = persist_day_bars(
            data_dir,
            symbol,
            groups[day],
            ist_date=day,
            provider=provider,
            interval=interval,
        )
        written.append(row)
        total += int(row.get("bar_count") or 0)
    return {
        "ok": any(r.get("ok") for r in written),
        "days": [r.get("ist_date") for r in written if r.get("ok")],
        "bar_count": total,
        "writes": written,
        "symbol": _canonical_symbol(symbol),
    }


def _index_path(data_dir: str | Path | None, ist_date: str) -> Path | None:
    if not data_dir or not ist_date:
        return None
    return Path(data_dir) / "market" / "bars_intraday" / "_index" / f"{ist_date}.json"


def _touch_session_index(
    data_dir: str | Path | None,
    symbol: str,
    ist_date: str,
    *,
    bar_count: int,
    provider: str,
    interval: str,
) -> None:
    path = _index_path(data_dir, ist_date)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc: dict[str, Any] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    doc = raw
            except (OSError, json.JSONDecodeError):
                doc = {}
        symbols = doc.get("symbols") if isinstance(doc.get("symbols"), dict) else {}
        canon = _canonical_symbol(symbol)
        rel = day_path(data_dir, symbol, ist_date=ist_date)
        symbols[canon] = {
            "bar_count": int(bar_count),
            "provider": provider,
            "interval": interval,
            "path": str(rel) if rel else None,
        }
        out = {
            "version": VERSION,
            "kind": "intraday_tape_index",
            "ist_date": ist_date,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "symbols": symbols,
        }
        path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("intraday tape index write failed", exc_info=True)


def load_session_index(
    data_dir: str | Path | None, ist_date: str
) -> dict[str, Any] | None:
    path = _index_path(data_dir, ist_date)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def previous_session_ist_date(now: datetime | None = None) -> str:
    from atlas.investment.bar_store import last_completed_nse_session_date

    d = last_completed_nse_session_date(now)
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def load_previous_session_bars(
    data_dir: str | Path | None,
    symbol: str,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return load_day_bars(
        data_dir,
        symbol,
        ist_date=previous_session_ist_date(now),
        limit=limit,
    )


def list_tape_days(data_dir: str | Path | None, symbol: str) -> list[str]:
    path = day_path(data_dir, symbol, ist_date="1970-01-01")
    if path is None:
        return []
    parent = path.parent
    if not parent.is_dir():
        return []
    days = [p.stem for p in parent.glob("*.json") if p.is_file()]
    return sorted(days)


def _key_tuple(k: str) -> tuple[int, str]:
    try:
        return (0, f"{int(float(k)):020d}")
    except (TypeError, ValueError):
        return (1, k)


def _bars_through(
    bars: list[dict[str, Any]], through_t: Any
) -> list[dict[str, Any]]:
    tk = _key_tuple(str(through_t))
    return [b for b in bars if _key_tuple(_bar_key(b)) <= tk]


def tape_ref_for_decision(
    data_dir: str | Path | None,
    symbol: str,
    *,
    bars: list[dict[str, Any]] | None = None,
    cursor: int | None = None,
    provider: str | None = None,
    interval: str = INTERVAL,
) -> dict[str, Any]:
    """Pointer a packet can use tomorrow to reload the 5m window it decided on."""
    rows = [b for b in (bars or []) if isinstance(b, dict)]
    bar: dict[str, Any] | None = None
    if rows and cursor is not None:
        try:
            i = int(cursor)
            if 0 <= i < len(rows):
                bar = rows[i]
        except (TypeError, ValueError):
            bar = None
    if bar is None and rows:
        bar = rows[-1]
    day = _bar_ist_date(bar) if bar else None
    day = day or ist_session_date()
    t = None
    if bar is not None:
        t = bar.get("t") if bar.get("t") is not None else bar.get("date")
    path = day_path(data_dir, symbol, ist_date=day)
    return {
        "kind": "intraday_tape",
        "version": VERSION,
        "symbol": _canonical_symbol(symbol),
        "ist_date": day,
        "interval": interval,
        "provider": provider,
        "bar_t": str(t) if t is not None else None,
        "cursor": int(cursor) if cursor is not None else None,
        "bar_count": len(rows),
        "path": str(path) if path else None,
    }


def reconstruct_from_ref(
    data_dir: str | Path | None, ref: dict[str, Any] | None
) -> dict[str, Any]:
    """Reload the 5m window a decision saw. Missing tape stays missing."""
    if not isinstance(ref, dict) or not ref.get("symbol") or not ref.get("ist_date"):
        return {"ok": False, "reason": "no_ref", "bars": []}
    symbol = str(ref.get("symbol") or "")
    ist_date = str(ref.get("ist_date") or "")
    bars = load_day_bars(data_dir, symbol, ist_date=ist_date)
    if not bars:
        return {
            "ok": False,
            "reason": "tape_missing",
            "symbol": symbol,
            "ist_date": ist_date,
            "bars": [],
        }
    through = ref.get("bar_t")
    if through is not None:
        bars = _bars_through(bars, through)
    elif ref.get("cursor") is not None:
        try:
            bars = bars[: int(ref["cursor"]) + 1]
        except (TypeError, ValueError):
            pass
    last = bars[-1] if bars else None
    close = None
    if isinstance(last, dict) and last.get("close") is not None:
        try:
            close = float(last["close"])
        except (TypeError, ValueError):
            close = None
    return {
        "ok": True,
        "symbol": symbol,
        "ist_date": ist_date,
        "bars": bars,
        "bar_count": len(bars),
        "last_close": close,
        "bar_t": last.get("t") if isinstance(last, dict) else None,
        "path": ref.get("path"),
        "provider": ref.get("provider"),
    }


def clamp_intraday_universe(
    instruments: list[dict[str, Any]] | None,
    *,
    open_symbols: set[str] | None = None,
    max_n: int = MAX_SYMBOLS,
) -> list[dict[str, Any]]:
    """Open book first, then remaining ranked names, hard cap ``max_n`` (Yahoo budget)."""
    rows = [i for i in (instruments or []) if isinstance(i, dict) and i.get("symbol")]
    cap = max(1, int(max_n))
    if len(rows) <= cap:
        return rows
    open_u = {str(s).strip().upper() for s in (open_symbols or set()) if s}
    head = [
        i
        for i in rows
        if str(i.get("symbol") or "").strip().upper() in open_u
    ]
    tail = [
        i
        for i in rows
        if str(i.get("symbol") or "").strip().upper() not in open_u
    ]
    return (head + tail)[:cap]
