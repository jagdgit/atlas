"""OI-STAB0 P0.1 — Market data choke (design + thin scaffold).

Nothing else should call Yahoo chart/quote APIs directly once callers migrate.
Today this wraps bar_store + rate gate + optional audit log. Full consolidation
of all Yahoo call sites continues across STAB0 Day 1–2.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

VERSION = "stab0.market_data.v1"
_log = logging.getLogger("atlas.investment.market_data")

_DEFAULT_MARK_TTL_S = 300.0  # 5 minutes


class MarketDataService:
    """Single façade for marks / bars. Yahoo only through this service."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        mark_ttl_s: float = _DEFAULT_MARK_TTL_S,
        audit: bool = True,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._mark_ttl_s = float(mark_ttl_s)
        self._audit = bool(audit)
        self._lock = threading.Lock()
        self._mark_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._audit_path: Path | None = None
        if self._data_dir:
            d = self._data_dir / "investment"
            d.mkdir(parents=True, exist_ok=True)
            self._audit_path = d / "yahoo_request_audit.jsonl"

    @property
    def VERSION(self) -> str:  # noqa: N802
        return VERSION

    def _audit_write(self, row: dict[str, Any]) -> None:
        if not self._audit or not self._audit_path:
            return
        try:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                **row,
            }
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, default=str) + "\n")
        except Exception:  # noqa: BLE001
            _log.debug("yahoo audit write failed", exc_info=True)

    def get_cached_mark(self, symbol: str) -> dict[str, Any] | None:
        key = (symbol or "").strip().upper()
        if not key:
            return None
        with self._lock:
            hit = self._mark_cache.get(key)
            if not hit:
                return None
            exp, doc = hit
            if time.time() > exp:
                self._mark_cache.pop(key, None)
                return None
            return dict(doc)

    def put_cached_mark(self, symbol: str, doc: dict[str, Any]) -> None:
        key = (symbol or "").strip().upper()
        if not key or not isinstance(doc, dict):
            return
        with self._lock:
            self._mark_cache[key] = (time.time() + self._mark_ttl_s, dict(doc))

    def load_local_bars(
        self, symbol: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Read durable bar_store only (no network)."""
        if not self._data_dir:
            return []
        try:
            from atlas.investment.bar_store import load_bars

            bars = load_bars(self._data_dir, symbol) or []
            if isinstance(bars, list):
                return bars[-max(1, int(limit)) :]
        except Exception:  # noqa: BLE001
            _log.debug("bar_store load failed for %s", symbol, exc_info=True)
        return []

    def mark_for_symbol(
        self,
        symbol: str,
        *,
        worker: str = "market_data",
        allow_network: bool = False,
        fetch_fn: Callable[[str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return best mark: cache → local bars tip → optional network fetch_fn.

        ``fetch_fn`` must already respect YahooRateGate. Prefer allow_network=False
        during RTH until callers are fully migrated.
        """
        sym = (symbol or "").strip().upper()
        cached = self.get_cached_mark(sym)
        if cached:
            self._audit_write(
                {
                    "worker": worker,
                    "symbol": sym,
                    "url_class": "cache",
                    "status": 200,
                    "cache_hit": True,
                }
            )
            return {"ok": True, "source": "cache", "symbol": sym, "mark": cached}

        bars = self.load_local_bars(sym, limit=3)
        if bars:
            tip = bars[-1] if isinstance(bars[-1], dict) else {}
            mark = {
                "last": tip.get("close") or tip.get("c") or tip.get("last"),
                "as_of": tip.get("date") or tip.get("ts"),
                "source": "bar_store",
            }
            if mark.get("last") is not None:
                self.put_cached_mark(sym, mark)
                self._audit_write(
                    {
                        "worker": worker,
                        "symbol": sym,
                        "url_class": "bar_store",
                        "status": 200,
                        "cache_hit": False,
                    }
                )
                return {"ok": True, "source": "bar_store", "symbol": sym, "mark": mark}

        if allow_network and fetch_fn is not None:
            try:
                remote = fetch_fn(sym) or {}
                self._audit_write(
                    {
                        "worker": worker,
                        "symbol": sym,
                        "url_class": "yahoo_via_fetch_fn",
                        "status": int(remote.get("status") or 200),
                        "cache_hit": False,
                    }
                )
                if remote.get("last") is not None or remote.get("close") is not None:
                    mark = {
                        "last": remote.get("last", remote.get("close")),
                        "as_of": remote.get("as_of"),
                        "source": "yahoo",
                    }
                    self.put_cached_mark(sym, mark)
                    return {
                        "ok": True,
                        "source": "yahoo",
                        "symbol": sym,
                        "mark": mark,
                    }
            except Exception as exc:  # noqa: BLE001
                self._audit_write(
                    {
                        "worker": worker,
                        "symbol": sym,
                        "url_class": "yahoo_via_fetch_fn",
                        "status": 0,
                        "cache_hit": False,
                        "error": type(exc).__name__,
                    }
                )
                return {
                    "ok": False,
                    "source": "yahoo",
                    "symbol": sym,
                    "error": type(exc).__name__,
                }

        self._audit_write(
            {
                "worker": worker,
                "symbol": sym,
                "url_class": "miss",
                "status": 404,
                "cache_hit": False,
            }
        )
        return {"ok": False, "source": "none", "symbol": sym, "error": "no_mark"}

    def note_bars(
        self,
        symbol: str,
        *,
        source: str,
        bars: list[Any] | None,
        worker: str = "market_reader",
    ) -> None:
        """Cache tip mark + audit when MarketReader resolves bars (no network)."""
        sym = (symbol or "").strip().upper()
        if not sym:
            return
        tip: dict[str, Any] = {}
        if bars:
            last = bars[-1]
            if isinstance(last, dict):
                tip = last
            elif hasattr(last, "close"):
                tip = {
                    "close": getattr(last, "close", None),
                    "date": getattr(last, "date", None) or getattr(last, "t", None),
                }
        last_px = tip.get("close") or tip.get("c") or tip.get("last")
        if last_px is not None:
            try:
                self.put_cached_mark(
                    sym,
                    {
                        "last": float(last_px),
                        "as_of": tip.get("date") or tip.get("t") or tip.get("as_of"),
                        "source": source,
                    },
                )
            except (TypeError, ValueError):
                pass
        self._audit_write(
            {
                "worker": worker,
                "symbol": sym,
                "url_class": source,
                "status": 200 if last_px is not None else 204,
                "cache_hit": source.startswith("durable") or source == "cache",
                "bar_count": len(bars) if bars else 0,
            }
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._mark_cache)
        soak = self.yahoo_soak_today()
        return {
            "version": VERSION,
            "mark_ttl_s": self._mark_ttl_s,
            "cached_marks": n,
            "audit_path": str(self._audit_path) if self._audit_path else None,
            "data_dir": str(self._data_dir) if self._data_dir else None,
            "yahoo_soak": soak,
        }

    def yahoo_soak_today(self, *, day_ist: str | None = None) -> dict[str, Any]:
        """OI-STAB0 Day 3 — count audit rows for today's IST Yahoo soak."""
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        day = day_ist or datetime.now(ist).date().isoformat()
        out: dict[str, Any] = {
            "day_ist": day,
            "rows": 0,
            "network_ish": 0,
            "status_429": 0,
            "durable_hits": 0,
            "cache_hits": 0,
            "by_url_class": {},
        }
        if not self._audit_path or not self._audit_path.is_file():
            return out
        by: dict[str, int] = {}
        try:
            with self._audit_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = str(row.get("ts") or "")
                    # UTC ts → IST day
                    day_ok = False
                    if ts.startswith(day):
                        day_ok = True
                    else:
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if dt.astimezone(ist).date().isoformat() == day:
                                day_ok = True
                        except Exception:  # noqa: BLE001
                            day_ok = False
                    if not day_ok:
                        continue
                    out["rows"] = int(out["rows"]) + 1
                    cls = str(row.get("url_class") or "unknown")
                    by[cls] = by.get(cls, 0) + 1
                    st = int(row.get("status") or 0)
                    if st == 429:
                        out["status_429"] = int(out["status_429"]) + 1
                    if cls in {"yahoo_network", "yahoo_via_fetch_fn"} or "yahoo" in cls:
                        out["network_ish"] = int(out["network_ish"]) + 1
                    if cls.startswith("durable"):
                        out["durable_hits"] = int(out["durable_hits"]) + 1
                    if row.get("cache_hit") or cls == "cache":
                        out["cache_hits"] = int(out["cache_hits"]) + 1
        except Exception:  # noqa: BLE001
            _log.debug("yahoo soak read failed", exc_info=True)
        out["by_url_class"] = by
        return out


_mds: MarketDataService | None = None
_mds_lock = threading.Lock()


def get_market_data_service(
    data_dir: str | Path | None = None,
) -> MarketDataService:
    global _mds
    with _mds_lock:
        if _mds is None:
            if data_dir is None:
                try:
                    from atlas.config import get_config

                    data_dir = get_config().paths.data
                except Exception:  # noqa: BLE001
                    data_dir = None
            _mds = MarketDataService(data_dir=data_dir)
        return _mds
