"""Cognitive Loop C4 — durable record of admitted and refused hypotheses.

The Agent Kernel reads admitted questions from here; the nightly cognitive pass
writes both outcomes. Refusals are kept with their reason, because "Atlas declined to
test this, and here is why" is a result.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.queue.v1"
STORE_REL = Path("investment") / "cognitive" / "queue"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.queue")

STATUS_ADMITTED = "ADMITTED"
STATUS_REFUSED = "REFUSED"
STATUS_DISPATCHED = "DISPATCHED"
STATUS_DONE = "DONE"


def _path(data_dir: str | Path, laboratory_id: str) -> Path:
    return Path(data_dir) / STORE_REL / f"{laboratory_id}.jsonl"


def record_decision(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    hypothesis_id: str | None,
    decision: dict[str, Any],
    statement: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    row = {
        "version": VERSION,
        "laboratory_id": str(laboratory_id or ""),
        "hypothesis_id": str(hypothesis_id or "") or None,
        "dimension": decision.get("dimension"),
        "status": STATUS_ADMITTED
        if str(decision.get("status") or "") == "ADMITTED"
        else STATUS_REFUSED,
        "reason": decision.get("reason"),
        "detail": decision.get("detail"),
        "experiment_spec": decision.get("experiment_spec"),
        "confounded_with": decision.get("confounded_with"),
        "statement": (statement or "")[:500] or None,
        "falsifier": decision.get("falsifier"),
        "recorded_at": datetime.now(_IST).isoformat(),
    }
    try:
        path = _path(data_dir, str(laboratory_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "row": row}
    except Exception as exc:  # noqa: BLE001
        _log.debug("cognitive queue append failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_queue(
    data_dir: str | Path | None, *, laboratory_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    path = _path(data_dir, str(laboratory_id))
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


def _latest_by_hypothesis(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        if hid:
            latest[hid] = row
    return latest


def next_admitted_hypothesis(
    data_dir: str | Path | None, *, laboratory_id: str
) -> dict[str, Any] | None:
    """Oldest admitted question not yet dispatched. One at a time, by design."""
    rows = load_queue(data_dir, laboratory_id=laboratory_id)
    for row in _latest_by_hypothesis(rows).values():
        if row.get("status") == STATUS_ADMITTED:
            return row
    return None


def mark(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    hypothesis_id: str,
    status: str,
    detail: str | None = None,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """Append a new state for a hypothesis — history is never overwritten."""
    rows = load_queue(data_dir, laboratory_id=laboratory_id)
    prior = _latest_by_hypothesis(rows).get(str(hypothesis_id))
    row = dict(prior or {})
    row.update(
        {
            "version": VERSION,
            "laboratory_id": str(laboratory_id or ""),
            "hypothesis_id": str(hypothesis_id),
            "status": str(status),
            "detail": detail or row.get("detail"),
            "experiment_id": experiment_id or row.get("experiment_id"),
            "recorded_at": datetime.now(_IST).isoformat(),
        }
    )
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    try:
        path = _path(data_dir, str(laboratory_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "row": row}
    except Exception as exc:  # noqa: BLE001
        _log.debug("cognitive queue mark failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}
