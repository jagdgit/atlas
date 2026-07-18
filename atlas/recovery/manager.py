"""Recovery Manager (Phase 0 · ATLAS_OS_ROADMAP §5.x/§2.8, P1/P4).

The cross-cutting **startup recovery** layer that runs *before Atlas accepts new work*.
Per-subsystem recovery already exists (the scheduler resets interrupted tasks and the
Job Engine re-enqueues unfinished jobs, each in their own ``start()``); this manager adds
what spans subsystems and must happen first:

  * a **durable, re-entrant run record** (``system.recovery_runs``) — a crash *during*
    recovery is marked ``interrupted`` and the next boot re-runs recovery cleanly (R1/Q6);
  * **storage integrity** checks (checksums / missing files) via the Storage Manager;
  * **backup verification** (a recent dump exists and is non-empty);
  * a delegated, idempotent **task recovery** sweep (counts interrupted tasks reset).

Every step is idempotent and isolated, and the whole pass never blocks boot — a recovery
failure is recorded and surfaced (health + events), not fatal. Events (``RecoveryStarted``
/ ``RecoveryCompleted``) flow through the durable bus to the Operations Dashboard.
"""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING, Any, Callable

from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.ops.backup import BackupManager
    from atlas.repositories.recovery_repo import RecoveryRepository
    from atlas.repositories.task_repo import TaskRepository
    from atlas.storage.service import StorageManager


class RecoveryManager:
    name = "recovery"
    VERSION = "1"

    def __init__(
        self,
        repo: "RecoveryRepository",
        *,
        storage: "StorageManager | None" = None,
        backup: "BackupManager | None" = None,
        task_repo: "TaskRepository | None" = None,
        events: "EventDispatcher | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._storage = storage
        self._backup = backup
        self._task_repo = task_repo
        self._events = events
        self._logger = logger or logging.getLogger("atlas.recovery")
        self._last: dict[str, Any] | None = None

    # --- lifecycle (runs first, before scheduler/jobs accept work) -------

    def start(self) -> None:
        try:
            self.run()
        except Exception:  # noqa: BLE001 - recovery must never block boot (P4)
            self._logger.exception("recovery pass failed")

    def stop(self) -> None:
        return None

    # --- recovery pass --------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Execute one idempotent recovery pass; record it durably. Returns the report."""
        interrupted = self._repo.mark_stale_running_interrupted()
        if interrupted:
            self._logger.warning(
                "found %d interrupted recovery run(s) from a previous boot", interrupted
            )
        run = self._repo.begin(socket.gethostname())
        run_id = str(run["id"])
        self._emit("RecoveryStarted", {"run_id": run_id})

        steps = [
            self._step("storage_integrity", self._storage_integrity),
            self._step("backup_verify", self._backup_verify),
            self._step("task_recovery", self._task_recovery),
        ]
        ok = all(s["ok"] for s in steps)
        status = "completed" if ok else "failed"
        self._repo.finish(run_id, status, steps)

        report = {
            "run_id": run_id,
            "status": status,
            "ok": ok,
            "prior_interrupted": interrupted,
            "steps": steps,
        }
        self._last = report
        self._emit("RecoveryCompleted", {"run_id": run_id, "status": status, "ok": ok})
        self._logger.info("recovery %s (%d steps)", status, len(steps))
        return report

    def last_report(self) -> dict[str, Any] | None:
        return self._last

    # --- steps ----------------------------------------------------------

    def _storage_integrity(self) -> dict[str, Any]:
        if self._storage is None:
            return {"ok": True, "detail": "storage not available", "data": {}}
        report = self._storage.integrity_check()
        ok = not report["missing"] and not report["corrupt"]
        detail = (
            f"{report['ok']}/{report['checked']} files verified"
            + (f", {len(report['missing'])} missing" if report["missing"] else "")
            + (f", {len(report['corrupt'])} corrupt" if report["corrupt"] else "")
        )
        return {"ok": ok, "detail": detail, "data": report}

    def _backup_verify(self) -> dict[str, Any]:
        if self._backup is None or not hasattr(self._backup, "list_backups"):
            return {"ok": True, "detail": "backup manager not available", "data": {}}
        dumps = self._backup.list_backups()
        if not dumps:
            return {"ok": True, "detail": "no backups yet", "data": {"count": 0}}
        latest = dumps[0]
        try:
            size = latest.stat().st_size
        except OSError:
            size = 0
        ok = size > 0
        return {
            "ok": ok,
            "detail": f"latest {latest.name} ({size} bytes)"
            + ("" if ok else " — empty/unreadable!"),
            "data": {"count": len(dumps), "latest": latest.name, "size": size},
        }

    def _task_recovery(self) -> dict[str, Any]:
        if self._task_repo is None:
            return {"ok": True, "detail": "task repo not available", "data": {}}
        n = self._task_repo.recover_interrupted()
        return {"ok": True, "detail": f"{n} interrupted task(s) reset", "data": {"reset": n}}

    # --- helpers --------------------------------------------------------

    def _step(self, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            out = fn()
            return {"name": name, **out}
        except Exception as exc:  # noqa: BLE001 - one step failing must not abort the pass
            self._logger.exception("recovery step %s failed", name)
            return {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            try:
                self._events.emit(event_type, payload, source=self.name)
            except Exception:  # noqa: BLE001 - telemetry must not break recovery
                self._logger.exception("failed to emit %s", event_type)

    def health_check(self) -> HealthStatus:
        if self._last is None:
            return HealthStatus.degraded_status("recovery has not run yet")
        if self._last["ok"]:
            return HealthStatus.ok(
                f"last recovery {self._last['status']}", **{"run_id": self._last["run_id"]}
            )
        return HealthStatus.degraded_status(
            "last recovery reported issues",
            steps=[s for s in self._last["steps"] if not s["ok"]],
        )
