"""Scheduler service: durable task execution with crash recovery.

Resilience (the power/internet-outage requirement):
    - On start, tasks left in claimed/running (interrupted by a crash) are reset
      to pending and picked up again.
    - Failures retry with exponential backoff up to ``max_retries``; each attempt
      is recorded in ``scheduler.task_runs``.
    - Workers claim tasks atomically (FOR UPDATE SKIP LOCKED), so running multiple
      workers — or even multiple processes later — is safe.

The scheduler is a Service (kernel-managed lifecycle). Handlers are registered
via a HandlerRegistry so new task types plug in without touching the scheduler.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TYPE_CHECKING

from atlas.scheduler.handlers import HandlerRegistry, TaskHandler
from atlas.services.base import HealthStatus
from atlas.telemetry import get_metrics, timer

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.repositories.task_repo import TaskRepository


class SchedulerService:
    name = "scheduler"

    def __init__(
        self,
        task_repo: "TaskRepository",
        handlers: HandlerRegistry | None = None,
        events: "EventDispatcher | None" = None,
        *,
        workers: int = 2,
        poll_interval: float = 1.0,
        backoff_base: float = 2.0,
        drain_timeout: float = 30.0,
        logger: logging.Logger | None = None,
        failure_data_dir: str | None = None,
        unknown_handler_delay: float = 5.0,
        idle_callback: "Callable[[], None] | None" = None,
        idle_heal_after: float = 120.0,
        mutate_queue: bool = True,
    ) -> None:
        # F2: the recurring clock cannot heal itself through a schedule — if
        # `schedule_tick` dies, nothing becomes due again, including any task that
        # would have repaired it. The worker loop always runs, so a sustained-idle
        # callback is the one place recovery can live without a circular dependency.
        self._idle_callback = idle_callback
        self._idle_heal_after = float(idle_heal_after)
        # F1: CLI/ephemeral boots must not recover/claim against the live task queue.
        self._mutate_queue = bool(mutate_queue)
        self._idle_since: float | None = None
        self._last_heal: float = 0.0
        self._idle_lock = threading.Lock()
        self._failure_data_dir = failure_data_dir
        # Small delay when releasing a task this process cannot handle, so it is not
        # re-claimed in a tight loop by the same handler-less process.
        self._unknown_handler_delay = float(unknown_handler_delay)
        self._repo = task_repo
        self._handlers = handlers or HandlerRegistry()
        self._events = events
        self._workers = workers
        self._poll_interval = poll_interval
        self._backoff_base = backoff_base
        self._drain_timeout = drain_timeout
        self._logger = logger or logging.getLogger("atlas.scheduler")
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- public API -----------------------------------------------------
    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers.register(task_type, handler)

    def set_idle_callback(self, callback: "Callable[[], None] | None") -> None:
        """Wire the recurring-clock re-seed (F2); set after ScheduleService exists."""
        self._idle_callback = callback

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
        max_retries: int = 3,
        delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        return self._repo.create(
            task_type,
            payload,
            priority=priority,
            max_retries=max_retries,
            delay_seconds=delay_seconds,
        )

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        if not self._mutate_queue:
            self._logger.info("scheduler start skipped (ephemeral — no claim/recover)")
            return
        try:
            from atlas.ops.service_locks import get_service_lock_manager

            mgr = get_service_lock_manager()
            if mgr is not None:
                lock = mgr.acquire("atlas.svc.scheduler")
                if lock.passive:
                    self._logger.error(
                        "scheduler staying passive — service lock not held"
                    )
                    return
        except Exception:  # noqa: BLE001
            self._logger.exception("scheduler service lock acquire failed")
        self._stop.clear()
        recovered = self._repo.recover_interrupted()
        if recovered:
            self._logger.info("recovered %d interrupted task(s)", recovered)
            if self._events is not None:
                self._events.emit(
                    "TasksRecovered", {"count": recovered}, source=self.name
                )
        for i in range(self._workers):
            thread = threading.Thread(
                target=self._worker_loop,
                args=(f"worker-{i}",),
                name=f"atlas-scheduler-{i}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Graceful drain (S22): stop claiming new tasks immediately, then give the
        in-flight task on each worker up to ``drain_timeout`` (total budget) to
        finish before abandoning it. A worker only claims new work when ``_stop`` is
        clear, so setting it here guarantees no new task starts during the drain.
        """
        self._stop.set()
        deadline = time.monotonic() + self._drain_timeout
        for thread in self._threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
        abandoned = [t for t in self._threads if t.is_alive()]
        if abandoned:
            # In-flight tasks stay `running` in the DB and are recovered on next boot.
            self._logger.warning(
                "drain timeout (%.0fs): %d task(s) still running, abandoning "
                "(will recover on restart)",
                self._drain_timeout, len(abandoned),
            )
        self._threads.clear()

    def health_check(self) -> HealthStatus:
        alive = sum(1 for t in self._threads if t.is_alive())
        detail = f"{alive}/{self._workers} workers alive"
        data = {"workers": alive, "configured": self._workers}
        if alive == self._workers:
            return HealthStatus.ok(detail, **data)
        if alive > 0:
            # Some workers died but the pool still drains tasks — degraded, not down.
            return HealthStatus.degraded_status(detail, **data)
        return HealthStatus.fail(detail, **data)

    # --- internals ------------------------------------------------------
    def _worker_loop(self, worker_id: str) -> None:
        while not self._stop.is_set():
            try:
                from atlas.ops.service_locks import require_service

                if not require_service("atlas.svc.scheduler"):
                    self._stop.wait(self._poll_interval)
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                task = self._repo.claim_next(worker_id)
            except Exception:  # noqa: BLE001 - transient DB error, back off and retry
                self._logger.exception("claim failed; backing off")
                self._stop.wait(self._poll_interval)
                continue

            if task is None:
                self._maybe_heal_idle()
                self._stop.wait(self._poll_interval)
                continue

            self._mark_busy()
            self._run_task(task, worker_id)

    def _run_task(self, task: dict[str, Any], worker_id: str) -> None:
        task_id = task["id"]
        task_type = task["task_type"]
        handler = self._handlers.get(task_type)
        run = self._repo.start_run(task_id, worker_id)

        if handler is None:
            self._handle_unknown_handler(task, task_id, task_type, run)
            return

        try:
            with timer("scheduler.task", task_type=task_type):
                result = handler(task["payload"])
            self._repo.finish_run(run["id"], "completed", result=result)
            self._repo.mark_completed(task_id)
            get_metrics().incr("scheduler.task.completed", task_type=task_type)
            self._emit(
                "TaskCompleted",
                task,
                result=result if isinstance(result, dict) else None,
            )
        except Exception as exc:  # noqa: BLE001 - handler errors drive retry logic
            error = f"{type(exc).__name__}: {exc}"
            self._repo.finish_run(run["id"], "failed", error=error)
            get_metrics().incr("scheduler.task.failed", task_type=task_type)
            self._handle_failure(task, error)

    def _mark_busy(self) -> None:
        with self._idle_lock:
            self._idle_since = None

    def _maybe_heal_idle(self) -> None:
        """Nothing claimable for a sustained window — ask the owner to re-seed (F2).

        A healthy Atlas is never idle for minutes: `host_guard_tick` alone is due every
        60s. Sustained emptiness means the recurring clock has stopped, which is exactly
        the 2026-10-06 outage (all 107 schedules frozen, service reporting healthy).
        """
        if self._idle_callback is None or self._idle_heal_after <= 0:
            return
        now = time.monotonic()
        with self._idle_lock:
            if self._idle_since is None:
                self._idle_since = now
                return
            if now - self._idle_since < self._idle_heal_after:
                return
            # Don't re-heal more often than the idle window itself.
            if now - self._last_heal < self._idle_heal_after:
                return
            self._last_heal = now
            idle_for = now - self._idle_since
            self._idle_since = now
        self._logger.warning(
            "scheduler idle for %.0fs with nothing claimable — re-seeding the recurring "
            "clock (a frozen schedule_tick cannot repair itself)",
            idle_for,
        )
        try:
            self._idle_callback()
            get_metrics().incr("scheduler.idle_heal")
        except Exception:  # noqa: BLE001 - healing must never kill the worker loop
            self._logger.exception("idle heal callback failed")

    def _handle_unknown_handler(
        self,
        task: dict[str, Any],
        task_id: Any,
        task_type: str,
        run: dict[str, Any],
    ) -> None:
        """An unknown handler is *this process's* limitation, not the task's fault.

        Previously the task was marked permanently failed. That turned a harmless
        condition into an outage: on 2026-10-06 a process without the full handler set
        consumed ``schedule_tick``, the only task that advances ``next_run_at``, and all
        107 enabled schedules froze for 45 minutes while the service still reported
        healthy. 164 such failures had accumulated since 2026-07-11, unnoticed.

        So: release the task so the process that owns the handler can run it, do not
        consume a retry, and shout — two processes sharing one queue with different
        handler sets is never a correct configuration.
        """
        msg = f"no handler registered for task_type '{task_type}'"
        self._repo.finish_run(run["id"], "failed", error=msg)
        released = False
        try:
            released = self._repo.release_to_pending(
                task_id, delay_seconds=self._unknown_handler_delay, error=msg
            )
        except Exception:  # noqa: BLE001 - fall through to the old behaviour
            self._logger.debug("release_to_pending failed", exc_info=True)
        if not released:
            self._repo.mark_failed_permanent(task_id, msg)
            self._emit("TaskFailed", task, error=msg)
            self._logger.error("%s (task %s; could not release)", msg, task_id)
            self._record_permanent_failure(task, msg)
            return
        get_metrics().incr("scheduler.task.unknown_handler", task_type=task_type)
        self._logger.error(
            "%s — released back to pending (task %s). This means another process is "
            "claiming tasks from the same queue without the full handler set; "
            "recurring work can stall if it claims schedule_tick.",
            msg,
            task_id,
        )
        self._note_unknown_handler(task_type)

    def _note_unknown_handler(self, task_type: str) -> None:
        """Record the unknown-handler condition so Loop 0 can escalate it (F3)."""
        if not self._failure_data_dir:
            return
        try:
            from atlas.investment.ops_health import record_task_failure

            record_task_failure(
                self._failure_data_dir,
                task_type=f"{task_type}:no_handler",
                task_id="-",
                error="no handler registered — two processes share one task queue",
            )
        except Exception:  # noqa: BLE001 - accounting must never break the scheduler
            self._logger.debug("unknown-handler record skipped", exc_info=True)

    def _handle_failure(self, task: dict[str, Any], error: str) -> None:
        task_id = task["id"]
        retry_count = task["retry_count"]
        max_retries = task["max_retries"]

        if retry_count < max_retries:
            delay = self._backoff_base * (2**retry_count)
            new_count = self._repo.reschedule_for_retry(task_id, delay, error)
            self._logger.warning(
                "task %s failed (%s); retry %d/%d in %.1fs",
                task_id,
                error,
                new_count,
                max_retries,
                delay,
            )
            self._emit("TaskRetry", task, error=error, retry=new_count)
        else:
            self._repo.mark_failed_permanent(task_id, error)
            self._logger.error(
                "task %s failed permanently after %d retries: %s",
                task_id,
                max_retries,
                error,
            )
            self._emit("TaskFailed", task, error=error)
            self._record_permanent_failure(task, error)

    def _record_permanent_failure(self, task: dict[str, Any], error: str) -> None:
        if not self._failure_data_dir:
            return
        try:
            from atlas.investment.ops_health import record_task_failure

            inner = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            task_type = str(task["task_type"])
            if inner.get("worker_id"):
                task_type = f"{task_type}:{inner['worker_id']}"
            record_task_failure(
                self._failure_data_dir,
                task_type=task_type,
                task_id=str(task["id"]),
                error=error,
            )
        except Exception:  # noqa: BLE001 - failure accounting must never break the scheduler
            self._logger.debug("permanent failure record skipped", exc_info=True)

    def _emit(self, event_type: str, task: dict[str, Any], **extra: Any) -> None:
        if self._events is None:
            return
        inner = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        payload: dict[str, Any] = {
            "task_id": str(task["id"]),
            "task_type": task["task_type"],
        }
        for key in ("worker_id", "mission_id", "schedule_id", "job_id"):
            if inner.get(key):
                payload[key] = str(inner[key])
        result = extra.pop("result", None)
        if isinstance(result, dict):
            if result.get("note"):
                payload["summary"] = str(result["note"])[:160]
            elif result.get("skipped"):
                payload["summary"] = f"skipped: {result['skipped']}"
            if result.get("reason") and not payload.get("summary"):
                payload["summary"] = str(result["reason"])[:160]
            if result.get("worker_id") and "worker_id" not in payload:
                payload["worker_id"] = str(result["worker_id"])
        payload.update(extra)
        self._events.emit(event_type, payload, source=self.name)
