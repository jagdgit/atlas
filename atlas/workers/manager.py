"""Worker Manager (Phase A · PHASE_A_PLAN §A.4) — supervises Persistent Workers.

Owns all worker durability so concrete workers stay trivial (see ``base.py``):

    worker_tick  →  skip unless tickable + past backoff
                 →  upgrade to running code version (B8)
                 →  drain operator inputs (Q4)
                 →  load active config version + checkpoint
                 →  worker.do_tick(ctx)  (one bounded unit)
                 →  save checkpoint + reset crash state   (success)
                 →  recovering + exponential backoff, pause on the 5th failure (B4, failure)

Ticks are driven by the schedule table (A.3); the manager never holds a worker in memory. A
tick failure is the *worker's* failure (tracked on the worker row) — it never propagates out of
the handler, so the scheduler keeps the recurrence alive and recovering ticks self-skip until
their ``next_retry_at``. Every notable action is journaled on the owning mission (P9).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from atlas.exceptions.base import AtlasError
from atlas.models.worker import (
    CRASH_PAUSE_AFTER,
    HEALTH_BLOCKED,
    HEALTH_HEALTHY,
    HEALTH_RECOVERING,
    WORKER_PAUSED,
    WORKER_RECOVERING,
    WORKER_RUNNING,
    WORKER_STATUSES,
    WORKER_STOPPED,
    WORKER_TICKABLE,
    Worker,
    backoff_for,
)
from atlas.services.base import HealthStatus
from atlas.workers.base import PersistentWorker, TickContext

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.recovery.checkpoints import CheckpointStore
    from atlas.repositories.worker_repo import WorkerRepository

_CHECKPOINT_OWNER = "worker"


class WorkerError(AtlasError):
    """A worker operation was invalid (unknown type/worker)."""


class WorkerManager:
    name = "workers"
    VERSION = "1"

    def __init__(
        self,
        worker_repo: "WorkerRepository",
        checkpoint_store: "CheckpointStore",
        *,
        schedule_service: Any | None = None,
        config_repo: Any | None = None,
        mission_repo: Any | None = None,
        events: "EventDispatcher | None" = None,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = worker_repo
        self._checkpoints = checkpoint_store
        self._schedules = schedule_service
        self._config_repo = config_repo
        self._missions = mission_repo
        self._events = events
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.workers")
        self._types: dict[str, PersistentWorker] = {}
        # Per-mission concurrency gate for the Phase-A budget (B1: max_concurrent_tasks only).
        # In-memory admission control (single-process Phase A); tracked as debt for multi-process.
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, int] = {}

    # --- worker-type registry -------------------------------------------

    def register_worker_type(self, worker: PersistentWorker) -> None:
        self._types[worker.type] = worker

    def known_types(self) -> list[str]:
        return sorted(self._types)

    # --- lifecycle management -------------------------------------------

    def create_worker(
        self,
        mission_id: str,
        worker_type: str,
        *,
        interval_seconds: int = 60,
        metadata: dict[str, Any] | None = None,
        autostart: bool = True,
    ) -> Worker:
        impl = self._require_type(worker_type)
        config_version = self._active_config_version(mission_id)
        worker = self._repo.create(
            mission_id=mission_id,
            type=worker_type,
            worker_version=impl.VERSION,
            config_version=config_version,
            metadata=metadata,
        )
        if autostart and self._schedules is not None:
            schedule = self._schedules.register_schedule(
                "worker_tick",
                interval_seconds,
                payload={"worker_id": worker.id},
                mission_id=mission_id,
                worker_id=worker.id,
                first_run_delay=0.0,
            )
            self._repo.set_schedule(worker.id, schedule.id)
            worker = self._repo.get(worker.id) or worker
        self._journal(
            mission_id,
            "worker_created",
            f"{worker_type} worker created",
            {"worker_id": worker.id, "type": worker_type, "worker_version": impl.VERSION},
        )
        self._emit("WorkerCreated", worker)
        self._logger.info("created %s worker %s (mission %s)", worker_type, worker.id, mission_id)
        return worker

    def pause(self, worker_id: UUID | str, reason: str = "") -> Worker:
        worker = self._require(worker_id)
        self._repo.set_status(worker.id, WORKER_PAUSED)
        self._toggle_schedule(worker, enabled=False)
        self._journal(worker.mission_id, "worker_paused", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerPaused", updated, reason=reason)
        return updated

    def resume(self, worker_id: UUID | str, reason: str = "") -> Worker:
        worker = self._require(worker_id)
        # Fresh start: clear crash backoff so it ticks on the next schedule fire.
        self._repo.record_success(worker.id)
        self._repo.set_status(worker.id, WORKER_RUNNING, health=HEALTH_HEALTHY)
        self._toggle_schedule(worker, enabled=True)
        self._journal(worker.mission_id, "worker_resumed", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerResumed", updated, reason=reason)
        return updated

    def stop_worker(self, worker_id: UUID | str, reason: str = "") -> Worker:
        """Operator stop of a worker (distinct from the service-lifecycle ``stop``)."""
        worker = self._require(worker_id)
        self._repo.set_status(worker.id, WORKER_STOPPED)
        self._toggle_schedule(worker, enabled=False)
        self._journal(worker.mission_id, "worker_stopped", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerStopped", updated, reason=reason)
        return updated

    def enqueue_input(self, worker_id: UUID | str, payload: dict[str, Any]) -> None:
        """Queue a live operator input the worker drains at the top of its next tick (Q4)."""
        worker = self._require(worker_id)
        self._repo.enqueue_input(worker.id, payload)
        self._emit("WorkerInputQueued", worker)

    # --- reads ----------------------------------------------------------

    def get_worker(self, worker_id: UUID | str) -> Worker | None:
        return self._repo.get(worker_id)

    def list_workers(
        self, *, mission_id: str | None = None, status: str | None = None
    ) -> list[Worker]:
        return self._repo.list(mission_id=mission_id, status=status)

    # --- the tick (registered as the `worker_tick` handler) -------------

    def worker_tick(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        worker_id = (payload or {}).get("worker_id")
        if not worker_id:
            return {"skipped": "no worker_id"}
        worker = self._repo.get(worker_id)
        if worker is None:
            return {"skipped": "unknown worker"}
        if worker.status not in WORKER_TICKABLE:
            return {"skipped": worker.status}
        if self._in_backoff(worker):
            return {"skipped": "backoff", "worker_id": worker.id}

        impl = self._types.get(worker.type)
        if impl is None:
            # No running code for this type — block it rather than crash-loop.
            self._repo.set_status(worker.id, WORKER_PAUSED, health=HEALTH_BLOCKED)
            self._journal(
                worker.mission_id, "worker_blocked",
                f"no registered code for type {worker.type!r}", {"worker_id": worker.id},
            )
            return {"skipped": "unknown type", "worker_id": worker.id}

        # Budget admission (B1/A.6): skip this tick if the mission is at its concurrent cap.
        cap = self._mission_cap(worker.mission_id)
        if not self._acquire(worker.mission_id, cap):
            self._emit("WorkerThrottled", worker, cap=cap)
            return {"skipped": "budget", "worker_id": worker.id}
        try:
            worker = self._maybe_upgrade(worker, impl)
            inputs = [i.payload for i in self._repo.drain_inputs(worker.id)]
            config, config_version = self._load_config(worker)
            state = self._checkpoints.load(_CHECKPOINT_OWNER, worker.id) or {}
            ctx = TickContext(
                worker_id=worker.id,
                mission_id=worker.mission_id,
                config=config,
                config_version=config_version,
                state=state,
                inputs=inputs,
            )
            try:
                result = impl.do_tick(ctx)
            except Exception as exc:  # noqa: BLE001 - a worker failure is data, not a crash
                return self._on_failure(worker, exc)
            return self._on_success(worker, impl, result, config_version)
        finally:
            self._release(worker.mission_id, cap)

    # --- tick outcome handling ------------------------------------------

    def _on_success(self, worker, impl, result, config_version) -> dict[str, Any]:
        self._checkpoints.save(_CHECKPOINT_OWNER, worker.id, result.state)
        self._repo.record_success(worker.id, config_version=config_version)
        if getattr(impl, "journal_ticks", False) and result.note:
            self._journal(worker.mission_id, "worker_tick", result.note, {"worker_id": worker.id})
        self._emit("WorkerTick", worker, note=result.note)
        if result.done:
            self._repo.set_status(worker.id, WORKER_STOPPED)
            self._toggle_schedule(worker, enabled=False)
            self._journal(
                worker.mission_id, "worker_done", result.note or "worker reported done",
                {"worker_id": worker.id},
            )
            self._emit("WorkerDone", worker, note=result.note)
        return {"worker_id": worker.id, "ticked": True, "done": result.done}

    def _on_failure(self, worker, exc: Exception) -> dict[str, Any]:
        error = f"{type(exc).__name__}: {exc}"
        new_count = worker.restart_count + 1
        if new_count >= CRASH_PAUSE_AFTER:
            # Crash loop: stop retrying (B4) — operator must resume.
            self._repo.record_failure(
                worker.id, status=WORKER_PAUSED, health=HEALTH_BLOCKED, backoff_seconds=None
            )
            self._toggle_schedule(worker, enabled=False)
            self._journal(
                worker.mission_id, "worker_paused",
                f"crash loop after {new_count} failures: {error}",
                {"worker_id": worker.id, "restart_count": new_count, "error": error},
            )
            self._emit("WorkerPaused", worker, error=error, restart_count=new_count)
            self._logger.error("worker %s paused after %d failures: %s", worker.id, new_count, error)
        else:
            delay = backoff_for(new_count)
            self._repo.record_failure(
                worker.id, status=WORKER_RECOVERING, health=HEALTH_RECOVERING,
                backoff_seconds=delay,
            )
            self._journal(
                worker.mission_id, "worker_recovering",
                f"tick failed (retry {new_count} in {delay:.0f}s): {error}",
                {"worker_id": worker.id, "restart_count": new_count, "backoff": delay, "error": error},
            )
            self._emit("WorkerFailed", worker, error=error, retry=new_count, backoff=delay)
            self._logger.warning(
                "worker %s tick failed (%s); retry %d in %.0fs", worker.id, error, new_count, delay
            )
        return {"worker_id": worker.id, "failed": True, "error": error, "restart_count": new_count}

    # --- helpers --------------------------------------------------------

    def _maybe_upgrade(self, worker: Worker, impl: PersistentWorker) -> Worker:
        if impl.VERSION != worker.worker_version:
            self._repo.set_version(worker.id, impl.VERSION)
            self._journal(
                worker.mission_id, "worker_upgraded",
                f"worker upgraded v{worker.worker_version}→v{impl.VERSION}",
                {"worker_id": worker.id, "from": worker.worker_version, "to": impl.VERSION},
            )
            self._emit("WorkerUpgraded", worker, to_version=impl.VERSION)
            return self._repo.get(worker.id) or worker
        return worker

    def _load_config(self, worker: Worker) -> tuple[dict[str, Any], int | None]:
        if self._config_repo is None:
            return {}, worker.config_version
        active = self._config_repo.get_active(worker.mission_id)
        if active is None:
            return {}, None
        if active.version != worker.config_version:
            self._journal(
                worker.mission_id, "config_picked_up",
                f"worker picked up config v{active.version}",
                {"worker_id": worker.id, "config_version": active.version},
            )
        return dict(active.document), active.version

    def _mission_cap(self, mission_id: str) -> int | None:
        """The mission's ``max_concurrent_tasks`` budget (B1), or ``None`` = unlimited."""
        if self._missions is None:
            return None
        try:
            mission = self._missions.get(mission_id)
        except Exception:  # noqa: BLE001 - budget lookup must not break a tick
            return None
        return mission.max_concurrent_tasks if mission is not None else None

    def _acquire(self, mission_id: str, cap: int | None) -> bool:
        if not cap or cap <= 0:
            return True
        with self._inflight_lock:
            current = self._inflight.get(mission_id, 0)
            if current >= cap:
                return False
            self._inflight[mission_id] = current + 1
            return True

    def _release(self, mission_id: str, cap: int | None) -> None:
        if not cap or cap <= 0:
            return
        with self._inflight_lock:
            current = self._inflight.get(mission_id, 0)
            if current <= 1:
                self._inflight.pop(mission_id, None)
            else:
                self._inflight[mission_id] = current - 1

    def _in_backoff(self, worker: Worker) -> bool:
        if worker.status != WORKER_RECOVERING or worker.next_retry_at is None:
            return False
        return self._now() < worker.next_retry_at

    def _toggle_schedule(self, worker: Worker, *, enabled: bool) -> None:
        if self._schedules is None or not worker.schedule_id:
            return
        try:
            if enabled:
                self._schedules.enable(worker.schedule_id)
            else:
                self._schedules.disable(worker.schedule_id)
        except Exception:  # noqa: BLE001 - schedule toggle must not fail a lifecycle op
            self._logger.exception("failed to toggle schedule for worker %s", worker.id)

    def _active_config_version(self, mission_id: str) -> int | None:
        if self._config_repo is None:
            return None
        active = self._config_repo.get_active(mission_id)
        return active.version if active else None

    def _now(self) -> datetime:
        if self._clock is not None:
            try:
                return self._clock.now()
            except Exception:  # noqa: BLE001 - fall back to wall clock
                pass
        return datetime.now(timezone.utc)

    def _require(self, worker_id: UUID | str) -> Worker:
        worker = self._repo.get(worker_id)
        if worker is None:
            raise WorkerError("worker not found", worker_id=str(worker_id))
        return worker

    def _require_type(self, worker_type: str) -> PersistentWorker:
        impl = self._types.get(worker_type)
        if impl is None:
            raise WorkerError(
                f"unknown worker type: {worker_type!r}", known=self.known_types()
            )
        return impl

    def _journal(
        self, mission_id: str, action: str, reason: str, refs: dict[str, Any] | None = None
    ) -> None:
        if self._missions is None:
            return
        try:
            self._missions.add_journal(mission_id, action, reason, refs or {})
        except Exception:  # noqa: BLE001 - journaling must not break a tick
            self._logger.exception("failed to journal %s for mission %s", action, mission_id)

    def _emit(self, event_type: str, worker: Worker, **extra: Any) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(
                event_type,
                {
                    "worker_id": worker.id,
                    "mission_id": worker.mission_id,
                    "type": worker.type,
                    **extra,
                },
                source=self.name,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            counts = self._repo.count_by_status()
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            return HealthStatus.fail(f"worker repo unreachable: {exc}")
        running = counts.get(WORKER_RUNNING, 0) + counts.get(WORKER_RECOVERING, 0)
        detail = f"{running} active worker(s); {len(self._types)} type(s) registered"
        data = {"counts": counts, "types": self.known_types()}
        if counts.get("failed"):
            return HealthStatus.degraded_status(detail + f", {counts['failed']} failed", **data)
        return HealthStatus.ok(detail, **data)
