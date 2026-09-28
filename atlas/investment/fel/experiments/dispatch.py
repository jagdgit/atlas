"""Dispatch one queued FEL item through existing runners. No duplicated science."""

from __future__ import annotations

import logging
from typing import Any, Callable

from atlas.investment.fel.experiments.store import load_experiment
from atlas.investment.fel.queue import claim_next, ensure_queue_dir, mark

_log = logging.getLogger("atlas.investment.fel.dispatch")

Handler = Callable[[dict[str, Any], str], dict[str, Any]]


def _summary(doc: dict[str, Any] | None) -> dict[str, Any]:
    d = doc if isinstance(doc, dict) else {}
    return {
        "experiment_id": d.get("experiment_id"),
        "result": d.get("result"),
        "reason": d.get("reason"),
        "promotion": d.get("promotion"),
        "hypothesis_id": d.get("hypothesis_id")
        or (d.get("hypothesis") or {}).get("hypothesis_id"),
        "belief_status": (d.get("belief") or {}).get("status"),
        "skipped": bool(d.get("queue_skipped")),
    }


def handle_e001(item: dict[str, Any], data_dir: str) -> dict[str, Any]:
    from atlas.investment.fel.experiments.e001_vol_accel import E001_ID, run_e001

    eid = str(item.get("experiment_id") or E001_ID)
    lab = item.get("laboratory_id")
    if item.get("skip_if_complete", True):
        existing = load_experiment(data_dir, eid, laboratory_id=lab)
        if existing and existing.get("result"):
            return {**existing, "queue_skipped": True}
    params = dict(item.get("params") or {})
    allowed = {
        k: params[k]
        for k in ("laboratory_id", "symbol_limit", "min_train_months", "costs")
        if k in params
    }
    allowed.setdefault("laboratory_id", lab)
    return run_e001(data_dir, **allowed)


def handle_e002(item: dict[str, Any], data_dir: str) -> dict[str, Any]:
    from atlas.investment.fel.experiments.e002_vol_accel_high_mom import E002_ID, run_e002

    eid = str(item.get("experiment_id") or E002_ID)
    lab = item.get("laboratory_id")
    if item.get("skip_if_complete", True):
        existing = load_experiment(data_dir, eid, laboratory_id=lab)
        if existing and existing.get("result"):
            return {**existing, "queue_skipped": True}
    params = dict(item.get("params") or {})
    allowed = {
        k: params[k]
        for k in ("laboratory_id", "symbol_limit", "min_train_months", "costs")
        if k in params
    }
    allowed.setdefault("laboratory_id", lab)
    return run_e002(data_dir, **allowed)


def handle_paper_round_trip(item: dict[str, Any], data_dir: str) -> dict[str, Any]:
    from atlas.investment.fel.experiments.paper_round_trip import (
        experiment_id_for,
        run_paper_round_trip,
    )

    lab = item.get("laboratory_id")
    eid = str(item.get("experiment_id") or experiment_id_for(str(lab or "")))
    if item.get("skip_if_complete", True):
        existing = load_experiment(data_dir, eid, laboratory_id=lab)
        if existing and existing.get("result"):
            return {**existing, "queue_skipped": True}
    return run_paper_round_trip(data_dir, laboratory_id=lab)


DEFAULT_HANDLERS: dict[str, Handler] = {
    "e001": handle_e001,
    "e002": handle_e002,
    "paper_round_trip": handle_paper_round_trip,
}


def item_is_cheap_skip(item: dict[str, Any] | None, data_dir: str | None) -> bool:
    """True when the next item will not hit Yahoo / rebuild a bar PIT."""
    if not item or not data_dir:
        return False
    if str(item.get("kind") or "") == "paper_round_trip":
        return True
    if not item.get("skip_if_complete", True):
        return False
    eid = str(item.get("experiment_id") or "")
    if not eid:
        return False
    existing = load_experiment(data_dir, eid, laboratory_id=item.get("laboratory_id"))
    return bool(existing and existing.get("result"))


def process_one(
    data_dir: str | None,
    *,
    handlers: dict[str, Handler] | None = None,
) -> dict[str, Any]:
    """Claim at most one item and run it. Safe to call from a BATCH tick."""
    if not data_dir:
        return {"idle": True, "reason": "no_data_dir"}
    try:
        ensure_queue_dir(data_dir)
    except OSError as exc:
        return {"idle": True, "reason": f"queue_unwritable:{exc}"}
    item = claim_next(data_dir)
    if item is None:
        return {"idle": True, "reason": "empty_queue"}
    qid = str(item.get("queue_id"))
    kind = str(item.get("kind") or "")
    table = dict(DEFAULT_HANDLERS)
    if handlers:
        table.update(handlers)
    fn = table.get(kind)
    if fn is None:
        mark(data_dir, qid, "BLOCKED", error=f"unknown_kind:{kind}")
        return {"idle": False, "status": "BLOCKED", "queue_id": qid, "reason": f"unknown_kind:{kind}"}
    try:
        doc = fn(item, data_dir)
        summary = _summary(doc if isinstance(doc, dict) else {})
        result = str(summary.get("result") or "")
        if result == "blocked_unavailable":
            mark(data_dir, qid, "BLOCKED", error="blocked_unavailable", result_summary=summary)
            return {"idle": False, "status": "BLOCKED", "queue_id": qid, "summary": summary}
        mark(data_dir, qid, "COMPLETED", result_summary=summary)
        return {
            "idle": False,
            "status": "COMPLETED",
            "queue_id": qid,
            "summary": summary,
        }
    except Exception as exc:  # noqa: BLE001 - queue must record failure, not crash the worker
        _log.exception("fel experiment %s failed", item.get("experiment_id"))
        mark(data_dir, qid, "FAILED", error=f"{type(exc).__name__}: {exc}")
        return {
            "idle": False,
            "status": "FAILED",
            "queue_id": qid,
            "error": f"{type(exc).__name__}: {exc}",
        }
