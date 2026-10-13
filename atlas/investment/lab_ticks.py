"""Per-lab tick admission ledger: did each paper lab actually get to run in session?

Written by the paper-trading worker (admitted ticks) and the worker manager
(deferred ticks). Read by ops health (stale-lab alert) and the evening digest.
Counters only — never a trading input.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()

VERSION = "ops.lab_ticks.v1"
STORE_REL = Path("investment") / "ops_health" / "lab_ticks"
SESSION = (time(9, 15), time(15, 30))
PAPER_WORKER_TYPE = "paper_trading"


def _now_utc(now: datetime | None) -> datetime:
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(timezone.utc)


def _is_trading_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    try:
        from atlas.trading.holidays import is_holiday

        return not is_holiday("nse_equity", day)
    except Exception:  # noqa: BLE001
        return True


def in_session(now: datetime | None = None) -> bool:
    ist = _now_utc(now).astimezone(_IST)
    return _is_trading_day(ist.date()) and SESSION[0] <= ist.time() < SESSION[1]


def ticks_path(data_dir: str | Path, day: str) -> Path:
    return Path(data_dir) / STORE_REL / f"{day}.json"


def load_day(data_dir: str | Path, day: str) -> dict[str, Any]:
    path = ticks_path(data_dir, day)
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("version", VERSION)
    doc.setdefault("ist_day", day)
    doc.setdefault("labs", {})
    doc.setdefault("deferrals", {})
    return doc


def previous_day_labs(data_dir: str | Path, day: str) -> set[str]:
    root = Path(data_dir) / STORE_REL
    if not root.is_dir():
        return set()
    prior = sorted(p.stem for p in root.glob("*.json") if p.stem < day)
    if not prior:
        return set()
    return set(load_day(data_dir, prior[-1]).get("labs") or {})


def _update(data_dir: str | Path, now: datetime | None, fn) -> None:
    clock = _now_utc(now)
    day = clock.astimezone(_IST).date().isoformat()
    path = ticks_path(data_dir, day)
    with _LOCK:
        doc = load_day(data_dir, day)
        fn(doc, clock.isoformat(), in_session(clock))
        doc["updated_at"] = clock.isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def record_admitted_tick(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Called at the start of every paper-lab tick that passed admission. Never raises."""
    if not data_dir or not laboratory_id:
        return

    def _apply(doc: dict[str, Any], at: str, session: bool) -> None:
        lab = doc["labs"].setdefault(laboratory_id, {"admitted": 0, "in_session": 0, "first_at": at})
        lab["admitted"] = int(lab.get("admitted") or 0) + 1
        lab["last_at"] = at
        if worker_id:
            lab["worker_id"] = str(worker_id)
        if session:
            lab["in_session"] = int(lab.get("in_session") or 0) + 1
            lab["last_in_session_at"] = at
            lab.setdefault("first_in_session_at", at)

    try:
        _update(data_dir, now, _apply)
    except Exception:  # noqa: BLE001
        _log.debug("lab tick record failed", exc_info=True)


def record_deferred_tick(
    data_dir: str | Path | None,
    *,
    worker_id: str,
    cause: str,
    reason: str = "",
    now: datetime | None = None,
) -> None:
    """Called by the worker manager when a paper-lab tick is deferred. Never raises."""
    if not data_dir or not worker_id:
        return

    def _apply(doc: dict[str, Any], at: str, session: bool) -> None:
        row = doc["deferrals"].setdefault(str(worker_id), {"total": 0, "in_session": 0, "by_cause": {}})
        row["total"] = int(row.get("total") or 0) + 1
        if session:
            row["in_session"] = int(row.get("in_session") or 0) + 1
        by = row.setdefault("by_cause", {})
        by[cause] = int(by.get(cause) or 0) + 1
        row["last_cause"] = cause
        row["last_reason"] = str(reason or "")[:200]
        row["last_at"] = at

    try:
        _update(data_dir, now, _apply)
    except Exception:  # noqa: BLE001
        _log.debug("lab deferral record failed", exc_info=True)


def deferrals_for_lab(doc: dict[str, Any], laboratory_id: str) -> dict[str, Any]:
    wid = ((doc.get("labs") or {}).get(laboratory_id) or {}).get("worker_id")
    return dict((doc.get("deferrals") or {}).get(str(wid)) or {}) if wid else {}
