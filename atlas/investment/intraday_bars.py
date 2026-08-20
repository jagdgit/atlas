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
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "bar_count": len(merged),
        "bars": merged,
    }
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "bar_count": len(merged)}


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
