"""Archive ingest — start Owner Knowledge jobs (including parallel missions).

Years of mixed work (USB archives, project dumps) belong on ``owner_knowledge`` missions,
not a single Engineering repo ingest. Each parallel job is its own mission + worker so
progress and checkpoints stay independent.

IR-RO1: Resource Planner issues an ``AdmissionContract`` before create. Large archives
may return ``needs_confirmation`` without instantiating a mission.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.core.resources.admission import (
    STATUS_DEFERRED,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_REJECTED,
    ResourcePlanner,
)
from atlas.missions.programs import program_label

_OWNER_TEMPLATE = "owner_knowledge"
_OWNER_PROGRAM = "personal_intelligence"


class ArchiveIngestService:
    """Operator-facing archive ingest (progress + parallel starts)."""

    name = "archive_ingest"
    VERSION = "archive.3"

    def __init__(
        self,
        *,
        templates: Any | None = None,
        workers: Any | None = None,
        missions: Any | None = None,
        materials: Any | None = None,
        host_guard: Any | None = None,
        resource_planner: ResourcePlanner | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._templates = templates
        self._workers = workers
        self._missions = missions
        self._materials = materials
        self._host_guard = host_guard
        self._planner = resource_planner or ResourcePlanner(host_guard=host_guard)
        self._logger = logger or logging.getLogger("atlas.missions.archive")

    def estimate(
        self,
        path: str,
        *,
        kind: str = "document",
        files_per_tick: int = 40,
    ) -> dict[str, Any]:
        """Dry-run archive cost estimate (no mission created)."""
        raw = (path or "").strip()
        if not raw:
            raise ValueError("path is required")
        resolved = Path(raw).expanduser()
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")
        kind = (kind or "document").strip().lower()
        est = self._planner.estimate_archive(
            resolved, kind=kind, files_per_tick=files_per_tick
        )
        return {
            "ok": True,
            "path": str(resolved.resolve()),
            "kind": kind,
            "estimate": est.as_dict(),
            "version": self.VERSION,
        }

    def start(
        self,
        path: str,
        *,
        kind: str = "document",
        domain: str = "personal",
        parallel: bool = True,
        title: str | None = None,
        note: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        files_per_tick: int = 40,
        process_now: bool = False,
        confirm: bool = False,
        confirmation_token: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Start learning from an archive path.

        ``parallel=True`` (default): new ``owner_knowledge`` mission so it runs beside
        existing archive workers. ``parallel=False``: append root to the shared Personal
        Observer mission (sequential with other roots on that worker).

        Large archives without ``confirm`` / ``confirmation_token`` return
        ``needs_confirmation`` and do **not** create a mission.
        """
        raw = (path or "").strip()
        if not raw:
            raise ValueError("path is required")
        resolved = Path(raw).expanduser()
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")
        kind = (kind or "document").strip().lower()
        if kind not in {"code", "document", "conversation"}:
            raise ValueError("kind must be code|document|conversation")

        root = {
            "path": str(resolved.resolve()),
            "kind": kind,
            "domain": domain or "personal",
        }
        label = Path(root["path"]).name

        if not parallel and self._materials is not None:
            out = self._materials.share(
                root["path"],
                program_id=_OWNER_PROGRAM,
                kind=kind,
                domain=root["domain"],
                process_now=process_now,
            )
            contract = self._planner.admit_realtime(
                program_id=_OWNER_PROGRAM,
                mission_template=_OWNER_TEMPLATE,
                intent="archive_shared_root",
            )
            return {
                "ok": True,
                "mode": "shared_mission",
                "path": root["path"],
                "kind": kind,
                "share": out,
                "admission": contract.as_dict(),
                "note": (
                    "Root added to the shared Personal Observer — same worker walks roots "
                    "in sequence. Use parallel=true for a separate progress bar / job."
                ),
                "version": self.VERSION,
            }

        if self._templates is None:
            raise RuntimeError("templates service not wired")

        contract = self._planner.admit_archive(
            path=root["path"],
            kind=kind,
            files_per_tick=files_per_tick,
            confirm=confirm,
            confirmation_token=confirmation_token,
            force=force,
            program_id=_OWNER_PROGRAM,
            mission_template=_OWNER_TEMPLATE,
        )

        if contract.status == STATUS_REJECTED:
            return {
                "ok": False,
                "mode": "rejected",
                "path": root["path"],
                "kind": kind,
                "admission": contract.as_dict(),
                "note": contract.reason or "rejected by Resource Planner",
                "version": self.VERSION,
            }

        if contract.status == STATUS_NEEDS_CONFIRMATION:
            return {
                "ok": False,
                "mode": "needs_confirmation",
                "path": root["path"],
                "kind": kind,
                "admission": contract.as_dict(),
                "estimate": contract.estimate.as_dict() if contract.estimate else None,
                "confirmation_token": contract.confirmation_token,
                "note": (
                    "Large archive — review the estimate, then resubmit with "
                    "confirm=true (and confirmation_token) to start."
                ),
                "version": self.VERSION,
            }

        queue_for_capacity = contract.status == STATUS_DEFERRED
        queue_reason = contract.reason if queue_for_capacity else ""

        short = uuid4().hex[:8]
        mission_title = title or f"Archive · {label} · {short}"
        cfg = {
            "archive_roots": [root],
            "build_profile": True,
            "embed": False,
            "policy": "project",
            "files_per_tick": max(1, int(files_per_tick or 40)),
            "tick_interval_seconds": 60,
            "archive_mode": "one_shot",
        }
        admission_meta = contract.as_dict()
        result = self._templates.instantiate(
            _OWNER_TEMPLATE,
            title=mission_title,
            objective=(
                note
                or f"Learn owner archive at {root['path']}"
                + (f" ({period_start}→{period_end})" if period_start or period_end else "")
            ),
            config_overrides=cfg,
            labels=[
                program_label(_OWNER_PROGRAM),
                f"role:{_OWNER_TEMPLATE}",
                "archive_ingest",
                f"archive:{label}",
            ],
            metadata={
                "program_id": _OWNER_PROGRAM,
                "template": _OWNER_TEMPLATE,
                "role": "Archive Ingest",
                "archive_path": root["path"],
                "archive_kind": kind,
                "archive_mode": "one_shot",  # finish → stop worker (free archive slot)
                "period_start": period_start,
                "period_end": period_end,
                "owner_note": note,
                "queued_for_capacity": queue_for_capacity,
                "queue_reason": queue_reason or None,
                "admission": admission_meta,
                "queue": {
                    "state": "WAITING_HOST" if queue_for_capacity else "READY",
                    "reason": queue_reason or "admitted",
                    "depends_on": [],
                    "owner": {
                        "program": _OWNER_PROGRAM,
                        "operator": "operator",
                    },
                },
            },
            activate=True,
            autostart=not queue_for_capacity,
            budget={"max_concurrent_tasks": 1, "ram_mb": 512},
        )
        mission = result.get("mission")
        workers = result.get("workers") or []
        mid = str(getattr(mission, "id", None) or (mission or {}).get("id") or "")
        worker_ids = [
            str(getattr(w, "id", None) or (w.get("id") if isinstance(w, dict) else ""))
            for w in workers
        ]
        worker_ids = [w for w in worker_ids if w]

        if queue_for_capacity and self._workers is not None and worker_ids:
            for wid in worker_ids:
                try:
                    self._workers.pause(wid, reason=f"queued: {queue_reason}")
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("archive queue pause failed: %s", exc)
            if self._host_guard is not None:
                try:
                    self._host_guard.mark_queued_start()
                except Exception:  # noqa: BLE001
                    pass

        if (
            not queue_for_capacity
            and self._workers is not None
            and worker_ids
        ):
            try:
                self._workers.enqueue_input(worker_ids[0], {"force": True})
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("archive worker nudge skipped: %s", exc)

        owner_context = None
        if (note or period_start or period_end) and self._materials is not None:
            personal = getattr(self._materials, "_personal", None)
            if personal is not None and hasattr(personal, "note_project_period"):
                try:
                    owner_context = personal.note_project_period(
                        project=label,
                        note=note,
                        period_start=period_start,
                        period_end=period_end,
                        root=root["path"],
                        actor="operator",
                    )
                except Exception as exc:  # noqa: BLE001
                    owner_context = {"error": str(exc)}

        mode = "queued_for_capacity" if queue_for_capacity else "parallel_mission"
        return {
            "ok": True,
            "mode": mode,
            "queued": queue_for_capacity,
            "queue_reason": queue_reason or None,
            "path": root["path"],
            "kind": kind,
            "mission_id": mid,
            "mission_title": mission_title,
            "worker_ids": worker_ids,
            "files_per_tick": cfg["files_per_tick"],
            "owner_context": owner_context,
            "admission": admission_meta,
            "estimate": contract.estimate.as_dict() if contract.estimate else None,
            "note": (
                (
                    "Archive job accepted and queued — it will start automatically "
                    f"when host capacity frees ({queue_reason or 'waiting'})."
                )
                if queue_for_capacity
                else (
                    "Parallel archive job started. Open Archive (or Missions) to watch "
                    "done/total progress; keep external disks mounted until complete."
                )
            ),
            "version": self.VERSION,
        }

    def status(self, *, limit: int = 50) -> dict[str, Any]:
        """List archive / owner_knowledge workers with checkpoint progress."""
        if self._workers is None:
            return {"workers": [], "note": "workers service unavailable", "count": 0}
        try:
            pool = max(int(limit) * 5, 100)
            if hasattr(self._workers, "list_workers_enriched"):
                enriched = self._workers.list_workers_enriched(limit=pool)
            else:
                enriched = [
                    self._workers.enrich_worker(w)
                    for w in self._workers.list_workers()[:pool]
                ]
        except Exception as exc:  # noqa: BLE001
            return {
                "workers": [],
                "count": 0,
                "note": f"failed to list workers: {exc}",
                "version": self.VERSION,
            }
        rows = [
            w
            for w in enriched
            if w.get("type") == _OWNER_TEMPLATE or w.get("is_archive")
        ][: max(1, int(limit))]
        return {
            "workers": rows,
            "count": len(rows),
            "host_guard": (
                self._host_guard.status()
                if self._host_guard is not None and hasattr(self._host_guard, "status")
                else None
            ),
            "note": (
                "Parallel Archive jobs use archive_mode=one_shot: when 1/1 files are done "
                "the worker stops and frees the Host Guard archive slot. "
                "Older jobs may still show running after 100% — use Stop (free slot). "
                "Permanent Personal archive (watch) stays running and only ticks on changes. "
                "Review learning via Personal dashboard, Engineering findings, and mission journal."
            ),
            "version": self.VERSION,
        }
