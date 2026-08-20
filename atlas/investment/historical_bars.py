"""OI-HIST-BARS / J1 — historical daily OHLCV bootstrap into durable bar_store.

Yahoo **history job** (multi-year range) is separate from live/session chart ticks.
Respects the shared Yahoo rate gate; never invents bars.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

VERSION = "jdg.hist_bars.v1"
STORE_REL = Path("investment") / "historical_bars"
_log = logging.getLogger("atlas.investment.historical_bars")

# Bootstrap priority: indices first, then open books / watchlist (caller supplies list)
DEFAULT_RANGE = "10y"
DEFAULT_INTERVAL = "1d"


def progress_path(data_dir: str | Path) -> Path:
    d = Path(data_dir) / STORE_REL
    d.mkdir(parents=True, exist_ok=True)
    return d / "bootstrap_progress.json"


def load_progress(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {"version": VERSION, "done": {}, "failed": {}}
    path = progress_path(data_dir)
    if not path.is_file():
        return {"version": VERSION, "done": {}, "failed": {}, "updated_at": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"version": VERSION, "done": {}, "failed": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": VERSION, "done": {}, "failed": {}}


def save_progress(data_dir: str | Path | None, doc: dict[str, Any]) -> None:
    if not data_dir:
        return
    path = progress_path(data_dir)
    doc = dict(doc)
    doc["version"] = VERSION
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def needs_bootstrap(
    data_dir: str | Path | None,
    symbol: str,
    *,
    min_bars: int = 400,
) -> bool:
    """True when durable history is thin (< ~2y trading days)."""
    try:
        from atlas.investment.bar_store import load_symbol_doc

        doc = load_symbol_doc(data_dir, symbol)
        if not doc:
            return True
        n = int(doc.get("bar_count") or len(doc.get("bars") or []) or 0)
        return n < int(min_bars)
    except Exception:  # noqa: BLE001
        return True


def needs_tip_refresh(
    data_dir: str | Path | None,
    symbol: str,
) -> bool:
    """True when history is dense but last bar is older than last NSE session."""
    try:
        from atlas.investment.bar_store import load_symbol_doc, symbol_readiness

        doc = load_symbol_doc(data_dir, symbol)
        if not doc:
            return False
        ready = symbol_readiness(doc)
        return bool(ready.get("priced")) and not bool(ready.get("session_fresh"))
    except Exception:  # noqa: BLE001
        return False


def bootstrap_symbol(
    data_dir: str | Path | None,
    symbol: str,
    *,
    fetch_bars: Callable[..., list],
    range_: str = DEFAULT_RANGE,
    interval: str = DEFAULT_INTERVAL,
    persist: bool = True,
) -> dict[str, Any]:
    """Fetch long history for one symbol and merge into durable store."""
    from atlas.investment.bar_store import persist_symbol_bars
    from atlas.investment.symbol_aliases import resolve_yahoo_symbol

    resolved = resolve_yahoo_symbol(symbol)
    canon = resolved.canonical or symbol
    out: dict[str, Any] = {
        "symbol": symbol,
        "canonical": canon,
        "yahoo": resolved.yahoo,
        "status": "unknown",
        "bars": 0,
    }
    try:
        raw = fetch_bars(
            symbol,
            limit=0,
            range=range_,
            interval=interval,
        )
    except Exception as exc:  # noqa: BLE001
        out["status"] = "gap"
        out["error"] = f"{type(exc).__name__}: {exc}"[:240]
        return out
    bars = []
    for b in raw or []:
        if isinstance(b, dict):
            bars.append(b)
        else:
            # Bar dataclass-like
            bars.append(
                {
                    "date": getattr(b, "t", None) or getattr(b, "date", None),
                    "open": getattr(b, "open", None),
                    "high": getattr(b, "high", None),
                    "low": getattr(b, "low", None),
                    "close": getattr(b, "close", None),
                    "volume": getattr(b, "volume", None),
                }
            )
    if not bars:
        out["status"] = "empty"
        return out
    if persist and data_dir:
        ready = persist_symbol_bars(
            data_dir, canon, bars, provider="yahoo_history"
        )
        out["bars"] = int(ready.get("bar_count") or len(bars))
        out["last_date"] = ready.get("last_date")
        out["status"] = "ok" if ready.get("ok") or out["bars"] > 0 else "thin"
    else:
        out["bars"] = len(bars)
        out["status"] = "ok"
    return out


def bootstrap_batch(
    data_dir: str | Path | None,
    symbols: list[str],
    *,
    fetch_bars: Callable[..., list],
    max_n: int = 8,
    range_: str = DEFAULT_RANGE,
    skip_done: bool = True,
    min_bars: int = 400,
) -> dict[str, Any]:
    """Budgeted batch — call from worker under Host Guard / rate gate."""
    progress = load_progress(data_dir)
    done = dict(progress.get("done") or {})
    failed = dict(progress.get("failed") or {})
    deferred = dict(progress.get("deferred") or {})
    now = time.time()
    # Drop expired soft-defers (rate-gate cooldowns)
    deferred = {
        k: v
        for k, v in deferred.items()
        if isinstance(v, dict) and float(v.get("until") or 0) > now
    }
    results: list[dict[str, Any]] = []
    attempted = 0
    for sym in symbols:
        if attempted >= max_n:
            break
        key = str(sym or "").strip().upper()
        if not key:
            continue
        # Soft defer (cooldown) — skip until retry window
        if skip_done and key in deferred:
            continue
        # Permanent gaps (e.g. Yahoo 404) — do not burn the batch budget re-probing.
        if skip_done and (key in failed or key in {str(k).upper() for k in failed}):
            continue
        thin = needs_bootstrap(data_dir, key, min_bars=min_bars)
        stale_tip = (not thin) and needs_tip_refresh(data_dir, key)
        if skip_done and key in done and not thin and not stale_tip:
            continue
        if not thin and not stale_tip:
            done[key] = {"status": "already_dense", "at": time.time()}
            continue
        attempted += 1
        row = bootstrap_symbol(
            data_dir,
            key,
            fetch_bars=fetch_bars,
            range_=range_ if thin else "1mo",
        )
        results.append(row)
        status = str(row.get("status") or "")
        err = str(row.get("error") or "")
        transient = (
            "cooldown" in err.lower()
            or "rate-gate" in err.lower()
            or "rate gate" in err.lower()
            or "rth" in err.lower()
            or "yield yahoo" in err.lower()
            or "live session" in err.lower()
        )
        if status in {"ok", "thin"}:
            done[key] = {
                "status": row.get("status"),
                "bars": row.get("bars"),
                "at": time.time(),
            }
            failed.pop(key, None)
            deferred.pop(key, None)
        elif transient:
            # Soft-defer this symbol and stop the batch — gate blocks everyone.
            deferred[key] = {"until": time.time() + 900.0, "error": err[:240]}
            break
        else:
            failed[key] = {
                "status": row.get("status"),
                "error": row.get("error"),
                "at": time.time(),
            }
        # Soft pace between symbols (gate also spaces charts)
        time.sleep(0.35)
    progress["done"] = done
    progress["failed"] = failed
    progress["deferred"] = deferred
    progress["last_batch"] = {
        "attempted": attempted,
        "results": results,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_progress(data_dir, progress)
    return {
        "version": VERSION,
        "attempted": attempted,
        "ok": sum(1 for r in results if r.get("status") in {"ok", "thin"}),
        "gaps": sum(1 for r in results if r.get("status") not in {"ok", "thin"}),
        "done_n": len(done),
        "failed_n": len(failed),
        "deferred_n": len(deferred),
        "results": results,
    }


def default_priority_symbols(
    data_dir: str | Path | None = None,
    *,
    include_universe: bool = True,
    limit: int = 80,
) -> list[str]:
    """Indices → open-book-ish seeds → watchlist/universe."""
    out: list[str] = [
        "^NSEI",
        "NIFTY",
        "^NSEBANK",
        "BANKNIFTY",
        "^CNXPHARMA",
        "^CNXAUTO",
        "^CNXIT",
        "^CNXMETAL",
        "^CNXFMCG",
        "^CNXENERGY",
    ]
    # Common open books / plan names
    out.extend(
        [
            "CIPLA.NS",
            "EICHERMOT.NS",
            "ETERNAL.NS",
            "TMPV.NS",
            "DEVYANI.NS",
            "MOTHERSON.NS",
            "KEI.NS",
            "IDEA.NS",
            "TCS.NS",
            "INFY.NS",
        ]
    )
    # NIFTY50-ish densify seeds (J1) — do not rely solely on short live watchlist
    out.extend(
        [
            "ADANIENT.NS",
            "ADANIPORTS.NS",
            "APOLLOHOSP.NS",
            "ASIANPAINT.NS",
            "AXISBANK.NS",
            "BAJAJ-AUTO.NS",
            "BAJFINANCE.NS",
            "BAJAJFINSV.NS",
            "BEL.NS",
            "BHARTIARTL.NS",
            "COALINDIA.NS",
            "DRREDDY.NS",
            "HCLTECH.NS",
            "HDFCBANK.NS",
            "HDFCLIFE.NS",
            "HEROMOTOCO.NS",
            "HINDALCO.NS",
            "HINDUNILVR.NS",
            "ICICIBANK.NS",
            "INDUSINDBK.NS",
            "ITC.NS",
            "JSWSTEEL.NS",
            "KOTAKBANK.NS",
            "LT.NS",
            "M&M.NS",
            "MARUTI.NS",
            "NESTLEIND.NS",
            "NTPC.NS",
            "ONGC.NS",
            "POWERGRID.NS",
            "RELIANCE.NS",
            "SBIN.NS",
            "SUNPHARMA.NS",
            "TATAMOTORS.NS",
            "TATASTEEL.NS",
            "TECHM.NS",
            "TITAN.NS",
            "ULTRACEMCO.NS",
            "WIPRO.NS",
        ]
    )
    if include_universe and data_dir:
        try:
            from atlas.investment import watchlists as wl

            snap = wl.latest("market_intelligence")
            rows = []
            if isinstance(snap, dict):
                rows = list(snap.get("symbols") or snap.get("ranked") or [])
            for r in rows:
                if isinstance(r, dict) and r.get("symbol"):
                    out.append(str(r["symbol"]))
                elif isinstance(r, str):
                    out.append(r)
        except Exception:  # noqa: BLE001
            _log.debug("watchlist for hist priority skipped", exc_info=True)
    # Dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        k = str(s).strip().upper()
        if not k or k in seen:
            continue
        seen.add(k)
        uniq.append(k)
        if len(uniq) >= limit:
            break
    return uniq
