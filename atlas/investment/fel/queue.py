"""Tiny persistent FEL experiment queue (C).

Statuses: QUEUED → RUNNING → COMPLETED | FAILED | BLOCKED

One JSON file per item under ``{data}/investment/fel/queue/``. Not Redis.
Not Celery. Single Atlas process claims one item per tick.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.laboratory import DEFAULT_SWING_LAB, normalize_laboratory_id

VERSION = "fel.queue.1"
STORE_REL = Path("investment") / "fel" / "queue"
STATUSES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED")
STALE_RUNNING_SECONDS = 2 * 60 * 60
_log = logging.getLogger("atlas.investment.fel.queue")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def queue_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def ensure_queue_dir(data_dir: str | Path) -> Path:
    """Create the queue directory. Caller must have write access (Atlas service user)."""
    root = queue_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def item_path(data_dir: str | Path, queue_id: str) -> Path:
    return queue_dir(data_dir) / f"{_safe(queue_id)}.json"


def _write(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return row if isinstance(row, dict) else None


def list_items(data_dir: str | Path | None) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = queue_dir(data_dir)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        row = _read(path)
        if row:
            rows.append(row)
    return rows


def get_item(data_dir: str | Path | None, queue_id: str) -> dict[str, Any] | None:
    if not data_dir or not queue_id:
        return None
    return _read(item_path(data_dir, queue_id))


def enqueue(
    data_dir: str | Path | None,
    *,
    kind: str,
    experiment_id: str | None = None,
    laboratory_id: str | None = None,
    params: dict[str, Any] | None = None,
    skip_if_complete: bool = True,
) -> dict[str, Any]:
    """Idempotent: same experiment_id stays QUEUED/RUNNING rather than duplicating."""
    if not data_dir:
        raise ValueError("data_dir required")
    kind_s = str(kind or "").strip()
    if not kind_s:
        raise ValueError("kind required")
    eid = str(experiment_id or f"{kind_s}-{uuid4().hex[:8]}")
    qid = _safe(eid)
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    existing = get_item(data_dir, qid)
    if existing and existing.get("status") in {"QUEUED", "RUNNING"}:
        return existing
    if existing and existing.get("status") == "COMPLETED" and skip_if_complete:
        return existing
    row = {
        "queue_id": qid,
        "experiment_id": eid,
        "kind": kind_s,
        "status": "QUEUED",
        "laboratory_id": lab,
        "params": dict(params or {}),
        "skip_if_complete": bool(skip_if_complete),
        "created_at": _now_iso(),
        "claimed_at": None,
        "finished_at": None,
        "error": None,
        "result_summary": None,
        "version": VERSION,
    }
    _write(item_path(data_dir, qid), row)
    return row


def recover_stale(
    data_dir: str | Path | None,
    *,
    stale_seconds: int = STALE_RUNNING_SECONDS,
) -> int:
    """RUNNING with old claimed_at → QUEUED (kill -9 / bounce)."""
    if not data_dir:
        return 0
    n = 0
    cutoff = _now() - timedelta(seconds=max(30, int(stale_seconds)))
    for row in list_items(data_dir):
        if row.get("status") != "RUNNING":
            continue
        claimed = str(row.get("claimed_at") or "")
        stale = True
        if claimed:
            try:
                ts = datetime.fromisoformat(claimed.replace("Z", "+00:00"))
                stale = ts <= cutoff
            except ValueError:
                stale = True
        if not stale:
            continue
        row["status"] = "QUEUED"
        row["error"] = "recovered_stale_running"
        row["claimed_at"] = None
        _write(item_path(data_dir, row["queue_id"]), row)
        n += 1
        _log.warning("recovered stale RUNNING experiment %s", row.get("experiment_id"))
    return n


def peek_next(data_dir: str | Path | None) -> dict[str, Any] | None:
    """Oldest QUEUED item without claiming. Recovers stale RUNNING first."""
    if not data_dir:
        return None
    recover_stale(data_dir)
    queued = [r for r in list_items(data_dir) if r.get("status") == "QUEUED"]
    queued.sort(key=lambda r: str(r.get("created_at") or ""))
    return queued[0] if queued else None


def claim_next(data_dir: str | Path | None) -> dict[str, Any] | None:
    """Claim the oldest QUEUED item. Single-process Atlas — one writer."""
    row = peek_next(data_dir)
    if row is None or not data_dir:
        return None
    row["status"] = "RUNNING"
    row["claimed_at"] = _now_iso()
    row["error"] = None
    _write(item_path(data_dir, row["queue_id"]), row)
    return row


def mark(
    data_dir: str | Path | None,
    queue_id: str,
    status: str,
    *,
    error: str | None = None,
    result_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if status not in STATUSES:
        raise ValueError(f"invalid status {status}")
    row = get_item(data_dir, queue_id)
    if not row or not data_dir:
        return None
    row["status"] = status
    if status in {"COMPLETED", "FAILED", "BLOCKED"}:
        row["finished_at"] = _now_iso()
    if error is not None:
        row["error"] = error
    if result_summary is not None:
        row["result_summary"] = result_summary
    _write(item_path(data_dir, queue_id), row)
    return row
