"""OI-MKT-COV Phase 1B — durable daily OHLCV store + readiness grades.

Persists bars Atlas actually observed so ranking/learning can reconstruct
what was known on a given day. Missing data stays missing (never invent).

Layout::
    {data}/market/bars/{SYMBOL}.json

Readiness grades (universe aggregate)::
    A ≥99%  B 95–99%  C 80–95%  D <80%
    ``durable_bars_ok`` only when grade ∈ {A,B} and min-history/freshness hold.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "mkt.bars.v1"
_log = logging.getLogger("atlas.investment.bar_store")

# Phase 1B defaults (operator-locked readiness contract)
MIN_HISTORY_BARS = 40
FRESH_DAYS = 5  # calendar days; weekends/holidays tolerant
GRADE_A_PCT = 99.0
GRADE_B_PCT = 95.0
GRADE_C_PCT = 80.0


def bars_root(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / "market" / "bars"


def _canonical_symbol(symbol: str) -> str:
    try:
        from atlas.investment.symbol_aliases import resolve_yahoo_symbol

        return str(
            resolve_yahoo_symbol(symbol).canonical or symbol or ""
        ).strip().upper()
    except Exception:  # noqa: BLE001
        return str(symbol or "").strip().upper()


def _safe_bar_filename(symbol: str) -> str:
    """Filesystem-safe name: ``^NSEI`` → ``_NSEI.json`` (caret not portable)."""
    sym = _canonical_symbol(symbol)
    safe = sym.replace("/", "_").replace("^", "_")
    return f"{safe}.json"


def symbol_path(data_dir: str | Path | None, symbol: str) -> Path | None:
    root = bars_root(data_dir)
    if root is None:
        return None
    sym = _canonical_symbol(symbol)
    if not sym:
        return None
    return root / _safe_bar_filename(sym)


def _candidate_bar_paths(data_dir: str | Path | None, symbol: str) -> list[Path]:
    """Canonical safe path first, then legacy on-disk names (``^NSEI.json``)."""
    root = bars_root(data_dir)
    if root is None:
        return []
    canon = _canonical_symbol(symbol)
    raw = str(symbol or "").strip().upper()
    out: list[Path] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        out.append(root / name)

    if canon:
        _add(_safe_bar_filename(canon))
        # Pre-CAP.1 / observer writes kept the caret in the filename
        if canon.startswith("^"):
            _add(f"{canon}.json")
            _add(f"{canon[1:]}.json")
    if raw and raw != canon:
        _add(_safe_bar_filename(raw))
        _add(f"{raw.replace('/', '_')}.json")
        if raw.startswith("^"):
            _add(f"{raw}.json")
    return out


def load_symbol_doc(data_dir: str | Path | None, symbol: str) -> dict[str, Any] | None:
    for path in _candidate_bar_paths(data_dir, symbol):
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _bar_date_key(bar: dict[str, Any]) -> str | None:
    for key in ("date", "ts", "t", "time", "timestamp"):
        raw = bar.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        # ISO date or datetime
        if "T" in s:
            return s[:10]
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        # epoch seconds / ms
        try:
            n = float(s)
            if n > 1e12:
                n /= 1000.0
            if n > 1e9:
                return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
    return None


def _normalize_bar(bar: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(bar, dict):
        return None
    day = _bar_date_key(bar)
    close = bar.get("close")
    if close is None:
        close = bar.get("c")
    try:
        close_f = float(close) if close is not None else None
    except (TypeError, ValueError):
        close_f = None
    if day is None or close_f is None:
        return None
    out: dict[str, Any] = {"date": day, "close": close_f}
    for src, dst in (
        ("open", "open"),
        ("o", "open"),
        ("high", "high"),
        ("h", "high"),
        ("low", "low"),
        ("l", "low"),
        ("volume", "volume"),
        ("v", "volume"),
    ):
        if dst in out:
            continue
        raw = bar.get(src)
        if raw is None:
            continue
        try:
            out[dst] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def load_bars(
    data_dir: str | Path | None,
    symbol: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    doc = load_symbol_doc(data_dir, symbol)
    if not doc:
        return []
    bars = [b for b in (doc.get("bars") or []) if isinstance(b, dict)]
    bars.sort(key=lambda b: str(b.get("date") or ""))
    if limit is not None and limit > 0:
        bars = bars[-int(limit) :]
    return bars


def merge_bars(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for bar in list(existing or []) + list(incoming or []):
        norm = _normalize_bar(bar) if isinstance(bar, dict) else None
        if not norm:
            continue
        by_day[str(norm["date"])] = norm
    return [by_day[k] for k in sorted(by_day)]


def persist_symbol_bars(
    data_dir: str | Path | None,
    symbol: str,
    bars: list[dict[str, Any]] | None,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    """Merge incoming bars into durable store. Returns per-symbol readiness."""
    try:
        from atlas.investment.symbol_aliases import resolve_yahoo_symbol

        canon = str(resolve_yahoo_symbol(symbol).canonical or symbol).strip().upper()
    except Exception:  # noqa: BLE001
        canon = str(symbol).strip().upper()
    path = symbol_path(data_dir, canon)
    if path is None:
        return {"symbol": symbol, "ok": False, "reason": "no_data_dir"}
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = load_symbol_doc(data_dir, canon) or {}
    prior_bars = prior.get("bars") if isinstance(prior.get("bars"), list) else []
    merged = merge_bars(prior_bars, bars or [])
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "version": VERSION,
        "symbol": canon,
        "provider": str(provider or prior.get("provider") or ""),
        "updated_at": now,
        "bar_count": len(merged),
        "bars": merged,
    }
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return symbol_readiness(doc)


def persist_bars_batch(
    data_dir: str | Path | None,
    bars_by_symbol: dict[str, list[dict[str, Any]]] | None,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    """Persist many symbols; return universe readiness over persisted set."""
    rows: list[dict[str, Any]] = []
    for sym, bars in (bars_by_symbol or {}).items():
        if not sym:
            continue
        try:
            rows.append(
                persist_symbol_bars(
                    data_dir, str(sym), list(bars or []), provider=provider
                )
            )
        except Exception:  # noqa: BLE001
            _log.debug("persist bars failed for %s", sym, exc_info=True)
            rows.append({"symbol": sym, "ok": False, "reason": "persist_error"})
    return readiness_from_rows(rows, membership=list((bars_by_symbol or {}).keys()))


def last_completed_nse_session_date(now: datetime | None = None):
    """Most recent completed NSE cash session date (IST), skipping weekends/holidays."""
    from datetime import date, time as dtime, timedelta
    from zoneinfo import ZoneInfo

    from atlas.trading.holidays import is_holiday

    ref = now or datetime.now(timezone.utc)
    try:
        ist = ref.astimezone(ZoneInfo("Asia/Kolkata"))
    except Exception:  # noqa: BLE001
        ist = ref
    d = ist.date() if hasattr(ist, "date") else date.today()
    # Session treated complete after 15:45 IST
    if ist.weekday() < 5 and not is_holiday("nse_equity", d):
        try:
            t = ist.time()
            if getattr(t, "tzinfo", None) is not None:
                t = t.replace(tzinfo=None)
            if t >= dtime(15, 45):
                return d
        except Exception:  # noqa: BLE001
            if getattr(ist, "hour", 0) >= 16:
                return d
    cur = d - timedelta(days=1)
    for _ in range(21):
        if cur.weekday() < 5 and not is_holiday("nse_equity", cur):
            return cur
        cur -= timedelta(days=1)
    return d


def symbol_readiness(
    doc: dict[str, Any] | None,
    *,
    min_history: int = MIN_HISTORY_BARS,
    fresh_days: int = FRESH_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-symbol readiness card (missing stays missing).

    ``fresh`` = within ``FRESH_DAYS`` calendar days (weekend-tolerant).
    ``session_fresh`` = last bar date equals last completed NSE session (CAP.1).
    Grade ``ok`` still uses calendar ``fresh`` for backward compat; expose both.
    """
    sym = str((doc or {}).get("symbol") or "")
    bars = [
        b
        for b in ((doc or {}).get("bars") or [])
        if isinstance(b, dict) and b.get("close") is not None
    ]
    bars.sort(key=lambda b: str(b.get("date") or ""))
    n = len(bars)
    last = bars[-1] if bars else None
    last_date = str((last or {}).get("date") or "") or None
    last_close = (last or {}).get("close")
    fresh = False
    age_days = None
    session_fresh = False
    last_session = None
    try:
        last_session = last_completed_nse_session_date(now)
        last_session_s = last_session.isoformat()
    except Exception:  # noqa: BLE001
        last_session_s = None
    if last_date:
        try:
            last_dt = datetime.fromisoformat(last_date).replace(tzinfo=timezone.utc)
            ref = now or datetime.now(timezone.utc)
            age_days = (ref.date() - last_dt.date()).days
            fresh = age_days <= int(fresh_days)
            if last_session_s:
                session_fresh = last_date[:10] >= last_session_s
        except ValueError:
            fresh = False
            session_fresh = False
    history_ok = n >= int(min_history)
    priced = last_close is not None
    ok = bool(priced and history_ok and fresh)
    return {
        "version": VERSION,
        "symbol": sym,
        "ok": ok,
        "priced": priced,
        "last_price": last_close,
        "last_date": last_date,
        "bar_count": n,
        "history_ok": history_ok,
        "min_history": int(min_history),
        "fresh": fresh,
        "session_fresh": session_fresh,
        "last_nse_session": last_session_s,
        "age_days": age_days,
        "provider": (doc or {}).get("provider"),
        "updated_at": (doc or {}).get("updated_at"),
    }


def readiness_for_symbols(
    data_dir: str | Path | None,
    symbols: list[str],
    *,
    min_history: int = MIN_HISTORY_BARS,
    fresh_days: int = FRESH_DAYS,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        doc = load_symbol_doc(data_dir, sym)
        if doc is None:
            rows.append(
                {
                    "symbol": sym,
                    "ok": False,
                    "priced": False,
                    "bar_count": 0,
                    "history_ok": False,
                    "fresh": False,
                    "session_fresh": False,
                    "reason": "no_durable_bars",
                }
            )
        else:
            rows.append(
                symbol_readiness(doc, min_history=min_history, fresh_days=fresh_days)
            )
    return readiness_from_rows(rows, membership=symbols)


def _grade(pct: float) -> str:
    if pct >= GRADE_A_PCT:
        return "A"
    if pct >= GRADE_B_PCT:
        return "B"
    if pct >= GRADE_C_PCT:
        return "C"
    return "D"


def readiness_from_rows(
    rows: list[dict[str, Any]],
    *,
    membership: list[str] | None = None,
) -> dict[str, Any]:
    mem = [str(s) for s in (membership or [r.get("symbol") for r in rows]) if s]
    n = max(1, len(mem)) if mem else max(1, len(rows))
    priced = sum(1 for r in rows if r.get("priced"))
    hist = sum(1 for r in rows if r.get("history_ok"))
    fresh = sum(1 for r in rows if r.get("fresh"))
    session_fresh = sum(1 for r in rows if r.get("session_fresh"))
    ok_n = sum(1 for r in rows if r.get("ok"))
    priced_pct = round(100.0 * priced / n, 1)
    hist_pct = round(100.0 * hist / n, 1)
    fresh_pct = round(100.0 * fresh / n, 1)
    session_fresh_pct = round(100.0 * session_fresh / n, 1)
    ok_pct = round(100.0 * ok_n / n, 1)
    # Contract grade uses full readiness (priced + history + fresh)
    grade = _grade(ok_pct)
    durable_ok = grade in {"A", "B"} and priced_pct >= GRADE_B_PCT
    return {
        "version": VERSION,
        "membership": len(mem) if mem else len(rows),
        "symbols_with_bars": priced,
        "priced_pct": priced_pct,
        "history_ok_pct": hist_pct,
        "fresh_pct": fresh_pct,
        "session_fresh_pct": session_fresh_pct,
        "ready_pct": ok_pct,
        "readiness_grade": grade,
        "durable_bars_ok": durable_ok,
        "min_history_bars": MIN_HISTORY_BARS,
        "fresh_days": FRESH_DAYS,
        "honesty": (
            "Durable bars = persisted OHLCV Atlas observed. "
            "RANKING TRUSTWORTHY requires readiness ≥ B (priced+history+fresh). "
            "session_fresh_pct = last bar on last NSE session (CAP.1; separate from "
            f"FRESH_DAYS={FRESH_DAYS}). Live Yahoo alone is not sufficient."
        ),
    }
