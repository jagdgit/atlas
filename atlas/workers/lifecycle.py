"""Bounded worker lifecycle actions for ops recovery (weekend P4).

Only ``resume_paused_paper_lab`` is allowed. It may resume a paper_trading
worker that was paused by the Phase-5 accidental dedupe (``phase5:STALE``).
It must never pause, stop, create workers, or change trading gates.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

_log = logging.getLogger("atlas.workers.lifecycle")

ACTION_RESUME_PAUSED_PAPER_LAB = "resume_paused_paper_lab"
PHASE5_STALE_MARKER = "phase5:STALE"
ALLOWED_PAPER_LABS = frozenset(
    {
        "india_fno_learner",
        "equity_intraday_learner",
        "india_equity_learner",
    }
)


def _portfolio_key_of(worker: Any, mission: dict[str, Any] | None = None) -> str:
    meta = getattr(worker, "metadata", None)
    if not isinstance(meta, dict):
        meta = worker.get("metadata") if isinstance(worker, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    for key in ("portfolio_key", "laboratory_id"):
        if meta.get(key):
            return str(meta[key]).strip()
    if isinstance(mission, dict):
        mmeta = mission.get("metadata") if isinstance(mission.get("metadata"), dict) else {}
        cfg = mission.get("config") if isinstance(mission.get("config"), dict) else {}
        doc = cfg.get("document") if isinstance(cfg.get("document"), dict) else cfg
        for src in (mmeta, doc, mission):
            if isinstance(src, dict):
                for key in ("portfolio_key", "laboratory_id"):
                    if src.get(key):
                        return str(src[key]).strip()
    return ""


def _worker_field(worker: Any, name: str) -> Any:
    if worker is None:
        return None
    if isinstance(worker, dict):
        return worker.get(name)
    return getattr(worker, name, None)


def pause_reason_is_phase5_stale(reason: str | None) -> bool:
    text = str(reason or "")
    return PHASE5_STALE_MARKER in text


def find_pause_reason(
    *,
    worker: Any = None,
    journal_rows: list[dict[str, Any]] | None = None,
) -> str:
    meta = _worker_field(worker, "metadata")
    if isinstance(meta, dict):
        for key in ("pause_reason", "last_pause_reason", "phase5_reason"):
            if meta.get(key):
                return str(meta[key])
    for row in journal_rows or []:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or row.get("kind") or row.get("event") or "")
        if action in {"worker_paused", "WorkerPaused"}:
            return str(row.get("reason") or row.get("message") or "")
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        if detail.get("reason") and "pause" in action.lower():
            return str(detail.get("reason"))
    return ""


def resume_paused_paper_lab(
    *,
    workers: Any,
    laboratory_id: str,
    journal_rows: list[dict[str, Any]] | None = None,
    mission_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    reason: str = "ops:resume_phase5_stale_paper_lab",
) -> dict[str, Any]:
    """Resume one paused paper lab worker if the pause was Phase-5 STALE.

    ``workers`` must expose ``list_workers`` / ``get_worker`` / ``resume`` like
    :class:`atlas.workers.manager.WorkerManager`.
    """
    lab = str(laboratory_id or "").strip()
    if lab not in ALLOWED_PAPER_LABS:
        return {
            "ok": False,
            "error": "laboratory_not_allowed",
            "laboratory_id": lab,
        }
    listed: list[Any] = []
    try:
        listed = list(workers.list_workers(status="paused", limit=200) or [])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"list_failed:{type(exc).__name__}:{exc}"}

    matches: list[Any] = []
    for w in listed:
        wtype = str(_worker_field(w, "type") or "")
        if wtype != "paper_trading":
            continue
        status = str(_worker_field(w, "status") or "")
        if status != "paused":
            continue
        mission = None
        mid = _worker_field(w, "mission_id")
        if mission_lookup and mid is not None:
            try:
                mission = mission_lookup(str(mid))
            except Exception:  # noqa: BLE001
                mission = None
        pk = _portfolio_key_of(w, mission)
        if pk == lab:
            matches.append((w, pk, mission))

    if not matches:
        return {
            "ok": False,
            "error": "no_paused_paper_worker",
            "laboratory_id": lab,
        }
    if len(matches) > 1:
        return {
            "ok": False,
            "error": "ambiguous_paused_workers",
            "laboratory_id": lab,
            "n": len(matches),
        }

    worker, pk, mission = matches[0]
    pause_reason = find_pause_reason(worker=worker, journal_rows=journal_rows)
    if not pause_reason_is_phase5_stale(pause_reason):
        # Allow explicit operator/ops binder that already verified Phase-5.
        meta = _worker_field(worker, "metadata")
        forced = isinstance(meta, dict) and meta.get("phase5_stale") is True
        if not forced:
            return {
                "ok": False,
                "error": "pause_reason_not_phase5_stale",
                "pause_reason": pause_reason or None,
                "laboratory_id": lab,
                "worker_id": str(_worker_field(worker, "id")),
            }

    wid = _worker_field(worker, "id")
    try:
        updated = workers.resume(wid, reason=reason)
    except Exception as exc:  # noqa: BLE001
        _log.warning("resume_paused_paper_lab failed: %s", exc, exc_info=True)
        return {
            "ok": False,
            "error": f"resume_failed:{type(exc).__name__}:{exc}",
            "worker_id": str(wid),
            "laboratory_id": lab,
        }

    status = str(_worker_field(updated, "status") or "")
    return {
        "ok": status == "running",
        "action": ACTION_RESUME_PAUSED_PAPER_LAB,
        "worker_id": str(_worker_field(updated, "id") or wid),
        "status": status,
        "schedule_id": str(_worker_field(updated, "schedule_id") or ""),
        "laboratory_id": lab,
        "portfolio_key": pk,
        "pause_reason": pause_reason,
        "phase5_stale": True,
        "mutates_strategy": False,
        "live_orders": False,
    }


def resume_fno_paper_if_phase5_stale(
    *,
    workers: Any,
    journal_rows: list[dict[str, Any]] | None = None,
    mission_lookup: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Ops-health binder: only the F&O paper lab."""
    return resume_paused_paper_lab(
        workers=workers,
        laboratory_id="india_fno_learner",
        journal_rows=journal_rows,
        mission_lookup=mission_lookup,
        reason="ops_health:resume_phase5_stale_fno_paper",
    )
