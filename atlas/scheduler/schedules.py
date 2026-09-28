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
        interval_seconds: int = 60,
        *,
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        enabled: bool = True,
        first_run_delay: float = 0.0,
        kind: str = "interval",
        cron_expr: str | None = None,
    ) -> Schedule:
        schedule = self._repo.create(
            task_type=task_type,
            interval_seconds=interval_seconds,
            payload=payload,
            mission_id=mission_id,
            worker_id=worker_id,
            enabled=enabled,
            first_run_delay=first_run_delay,
            kind=kind,
            cron_expr=cron_expr,
        )
        if schedule.kind == "cron":
            self._logger.info(
                "registered schedule %s (%s cron %s)",
                schedule.id, task_type, schedule.cron_expr,
            )
        else:
            self._logger.info(
                "registered schedule %s (%s every %ds)",
                schedule.id, task_type, interval_seconds,
            )
        return schedule

    def register_cron_schedule(
        self,
        task_type: str,
        cron_expr: str,
        *,
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        enabled: bool = True,
        first_run_delay: float = 0.0,
    ) -> Schedule:
        """Register a 5-field crontab schedule (OI-A1)."""
        return self.register_schedule(
            task_type,
            interval_seconds=60,
            payload=payload,
            mission_id=mission_id,
            worker_id=worker_id,
            enabled=enabled,
            first_run_delay=first_run_delay,
            kind="cron",
            cron_expr=cron_expr,
        )

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

    def bump_next_run(
        self,
        schedule_id: UUID | str,
        *,
        delay_seconds: float = 120.0,
    ) -> bool:
        """Pull a schedule forward so host/budget deferrals do not waste a full interval.

        Host Respect: never drop program work — retry soon instead of waiting the
        full day after a single admitted-but-deferred tick fire.
        """
        from datetime import datetime, timedelta, timezone

        delay = max(15.0, float(delay_seconds or 120.0))
        nxt = datetime.now(timezone.utc) + timedelta(seconds=delay)
        if hasattr(self._repo, "set_next_run_at"):
            return bool(self._repo.set_next_run_at(schedule_id, nxt, only_if_later=True))
        return False

    def set_cron(self, schedule_id: UUID | str, cron_expr: str) -> bool:
        if hasattr(self._repo, "set_cron"):
            return self._repo.set_cron(schedule_id, cron_expr)
        return False

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
        """Chain exactly one future ``schedule_tick`` (OI-SCHED-CHURN0).

        Always-insert re-enqueue multiplied under concurrent workers: each due tick
        spawned another, backlog grew, and TaskCompleted flooded the journal.
        Prefer an atomic insert-if-no-pending; fall back to a queued-only count for
        hermetic fakes that lack the repo helper.
        """
        try:
            create_if = getattr(self._tasks, "create_if_no_pending", None)
            if callable(create_if):
                try:
                    create_if(
                        TICK_TASK_TYPE,
                        {},
                        max_retries=5,
                        delay_seconds=self._tick_interval,
                    )
                    return
                except Exception:  # noqa: BLE001 - singleton helper must not kill recurrence
                    self._logger.exception(
                        "create_if_no_pending failed; falling back to queued count"
                    )
            queued = getattr(self._tasks, "count_queued_of_type", None)
            if callable(queued):
                if int(queued(TICK_TASK_TYPE) or 0) > 0:
                    return
            elif self._tasks.count_pending_of_type(TICK_TASK_TYPE) > 0:
                # Fake repos often only track pending; still avoid stacking.
                return
            self._tasks.create(
                TICK_TASK_TYPE, {}, max_retries=5, delay_seconds=self._tick_interval
            )
        except Exception:  # noqa: BLE001 - a re-seed on next boot recovers the chain
            self._logger.exception("failed to re-enqueue schedule_tick")

    def ensure_running(self) -> None:
        """Seed the recurring tick if none is in flight (idempotent across reboots)."""
        try:
            collapse = getattr(self._tasks, "collapse_pending_of_type", None)
            if callable(collapse):
                cancelled = int(collapse(TICK_TASK_TYPE, keep=1) or 0)
                if cancelled:
                    self._logger.warning(
                        "collapsed %d excess pending %s task(s)",
                        cancelled,
                        TICK_TASK_TYPE,
                    )
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
