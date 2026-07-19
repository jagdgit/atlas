"""Schedule service — the durable recurrence driver (Phase A · §A.3, P1/P4).

Promotes ad-hoc `delay_seconds` self-re-enqueue into a first-class, inspectable, pausable
recurrence layer. A single lightweight **`schedule_tick`** task (itself durable) periodically:

    claim due enabled schedules  →  enqueue each schedule's task  →  advance next_run_at
                                 →  re-enqueue the next schedule_tick

Because `next_run_at` and the tick task both live in the DB, recurrence survives `kill -9` +
reboot (the scheduler recovers the interrupted tick; the service re-seeds one on boot if none
is pending). Phase A drives **workers** off this (B3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from atlas.models.schedule import Schedule
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.repositories.schedule_repo import ScheduleRepository
    from atlas.repositories.task_repo import TaskRepository

TICK_TASK_TYPE = "schedule_tick"


class ScheduleService:
    name = "schedules"
    VERSION = "1"

    def __init__(
        self,
        schedule_repo: "ScheduleRepository",
        task_repo: "TaskRepository",
        *,
        tick_interval: float = 5.0,
        mission_repo: Any | None = None,
        events: "EventDispatcher | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = schedule_repo
        self._tasks = task_repo
        self._tick_interval = tick_interval
        # Optional (A.6): resolve a mission's effective priority so its tasks are claimed ahead
        # of lower-priority missions. Loose dependency — no hard import on the Mission Manager.
        self._missions = mission_repo
        self._events = events
        self._logger = logger or logging.getLogger("atlas.scheduler.schedules")

    # --- schedule CRUD --------------------------------------------------

    def register_schedule(
        self,
        task_type: str,
        interval_seconds: int,
        *,
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        enabled: bool = True,
        first_run_delay: float = 0.0,
    ) -> Schedule:
        schedule = self._repo.create(
            task_type=task_type,
            interval_seconds=interval_seconds,
            payload=payload,
            mission_id=mission_id,
            worker_id=worker_id,
            enabled=enabled,
            first_run_delay=first_run_delay,
        )
        self._logger.info(
            "registered schedule %s (%s every %ds)",
            schedule.id, task_type, interval_seconds,
        )
        return schedule

    def get(self, schedule_id: UUID | str) -> Schedule | None:
        return self._repo.get(schedule_id)

    def list_schedules(
        self, *, enabled: bool | None = None, mission_id: str | None = None
    ) -> list[Schedule]:
        return self._repo.list(enabled=enabled, mission_id=mission_id)

    def disable(self, schedule_id: UUID | str) -> bool:
        return self._repo.set_enabled(schedule_id, False)

    def enable(self, schedule_id: UUID | str) -> bool:
        return self._repo.set_enabled(schedule_id, True)

    def set_interval(self, schedule_id: UUID | str, interval_seconds: int) -> bool:
        return self._repo.set_interval(schedule_id, interval_seconds)

    def disable_for_mission(self, mission_id: UUID | str) -> int:
        return self._repo.disable_for_mission(mission_id)

    def delete(self, schedule_id: UUID | str) -> bool:
        return self._repo.delete(schedule_id)

    # --- the tick (registered as the `schedule_tick` handler) -----------

    def tick(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Enqueue due schedules, advance them, then re-enqueue the next tick.

        Per-schedule enqueue failures are isolated (logged, skipped) so one bad schedule can
        never stall the whole recurrence loop; the next tick is **always** re-enqueued.
        """
        fired: list[str] = []
        try:
            due = self._repo.claim_due()
        finally:
            # Chain the next tick even if claiming raised, so recurrence self-heals.
            self._reenqueue_self()
        for schedule in due:
            try:
                self._enqueue_for(schedule)
                fired.append(schedule.id)
            except Exception:  # noqa: BLE001 - isolate one bad schedule from the loop
                self._logger.exception("failed to enqueue schedule %s", schedule.id)
        if fired:
            self._logger.debug("schedule tick fired %d schedule(s)", len(fired))
            self._emit("SchedulesFired", {"count": len(fired), "schedule_ids": fired})
        return {"fired": len(fired), "schedule_ids": fired}

    def _enqueue_for(self, schedule: Schedule) -> None:
        task_payload = {
            **(schedule.payload or {}),
            "schedule_id": schedule.id,
            "mission_id": schedule.mission_id,
            "worker_id": schedule.worker_id,
        }
        self._tasks.create(
            schedule.task_type, task_payload, priority=self._priority_for(schedule)
        )

    def _priority_for(self, schedule: Schedule) -> int:
        """Effective scheduler priority for a schedule's task = its mission's (A.6/A7)."""
        if self._missions is None or not schedule.mission_id:
            return 0
        try:
            mission = self._missions.get(schedule.mission_id)
        except Exception:  # noqa: BLE001 - priority lookup must not break the tick
            return 0
        return mission.effective_priority if mission is not None else 0

    def _reenqueue_self(self) -> None:
        try:
            self._tasks.create(
                TICK_TASK_TYPE, {}, max_retries=5, delay_seconds=self._tick_interval
            )
        except Exception:  # noqa: BLE001 - a re-seed on next boot recovers the chain
            self._logger.exception("failed to re-enqueue schedule_tick")

    def ensure_running(self) -> None:
        """Seed the recurring tick if none is in flight (idempotent across reboots)."""
        try:
            if self._tasks.count_pending_of_type(TICK_TASK_TYPE) == 0:
                self._tasks.create(TICK_TASK_TYPE, {}, max_retries=5, delay_seconds=0.0)
                self._logger.info("seeded schedule_tick loop")
        except Exception:  # noqa: BLE001 - never let scheduling seed fail boot
            self._logger.exception("failed to seed schedule_tick")

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        self.ensure_running()

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            enabled = self._repo.count_enabled()
            pending_tick = self._tasks.count_pending_of_type(TICK_TASK_TYPE)
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            return HealthStatus.fail(f"schedule repo unreachable: {exc}")
        detail = f"{enabled} enabled schedule(s), tick {'live' if pending_tick else 'idle'}"
        data = {"enabled": enabled, "tick_pending": pending_tick}
        if pending_tick == 0:
            return HealthStatus.degraded_status(detail + " (no tick queued)", **data)
        return HealthStatus.ok(detail, **data)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.name)
        except Exception:  # noqa: BLE001 - telemetry must never break the tick
            self._logger.exception("failed to emit %s", event_type)
