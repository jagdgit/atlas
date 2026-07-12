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
from typing import Any, TYPE_CHECKING

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
    ) -> None:
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
                task = self._repo.claim_next(worker_id)
            except Exception:  # noqa: BLE001 - transient DB error, back off and retry
                self._logger.exception("claim failed; backing off")
                self._stop.wait(self._poll_interval)
                continue

            if task is None:
                self._stop.wait(self._poll_interval)
                continue

            self._run_task(task, worker_id)

    def _run_task(self, task: dict[str, Any], worker_id: str) -> None:
        task_id = task["id"]
        task_type = task["task_type"]
        handler = self._handlers.get(task_type)
        run = self._repo.start_run(task_id, worker_id)

        if handler is None:
            msg = f"no handler registered for task_type '{task_type}'"
            self._repo.finish_run(run["id"], "failed", error=msg)
            self._repo.mark_failed_permanent(task_id, msg)
            self._emit("TaskFailed", task, error=msg)
            self._logger.error("%s (task %s)", msg, task_id)
            return

        try:
            with timer("scheduler.task", task_type=task_type):
                result = handler(task["payload"])
            self._repo.finish_run(run["id"], "completed", result=result)
            self._repo.mark_completed(task_id)
            get_metrics().incr("scheduler.task.completed", task_type=task_type)
            self._emit("TaskCompleted", task)
        except Exception as exc:  # noqa: BLE001 - handler errors drive retry logic
            error = f"{type(exc).__name__}: {exc}"
            self._repo.finish_run(run["id"], "failed", error=error)
            get_metrics().incr("scheduler.task.failed", task_type=task_type)
            self._handle_failure(task, error)

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

    def _emit(self, event_type: str, task: dict[str, Any], **extra: Any) -> None:
        if self._events is None:
            return
        payload = {
            "task_id": str(task["id"]),
            "task_type": task["task_type"],
            **extra,
        }
        self._events.emit(event_type, payload, source=self.name)
