"""Health monitor service.

Periodically checks every registered service and records the result to
``system.health``. Emits a ``ServiceUnhealthy`` event when a check fails, so the
rest of the system can react (alerting, recovery) without polling.

Runs a daemon thread; an initial check runs synchronously at start so there is
always a baseline recorded.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.kernel.registry import ServiceRegistry
    from atlas.repositories.health_repo import HealthRepository


class HealthMonitor:
    name = "health_monitor"

    def __init__(
        self,
        registry: "ServiceRegistry",
        health_repo: "HealthRepository",
        events: "EventDispatcher | None" = None,
        interval: int = 30,
        logger: logging.Logger | None = None,
    ) -> None:
        self._registry = registry
        self._repo = health_repo
        self._events = events
        self._interval = interval
        self._logger = logger or logging.getLogger("atlas.health")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self.check_all()  # baseline
        self._thread = threading.Thread(
            target=self._loop, name="atlas-health", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def health_check(self) -> HealthStatus:
        alive = self._thread is not None and self._thread.is_alive()
        return (
            HealthStatus.ok("monitor running")
            if alive
            else HealthStatus.ok("monitor idle")
        )

    def check_all(self) -> dict[str, HealthStatus]:
        results: dict[str, HealthStatus] = {}
        for service in self._registry.all():
            if service.name == self.name:
                continue
            status = service.health_check()
            results[service.name] = status
            try:
                self._repo.record(
                    service.name, status.healthy, status.detail, status.data
                )
            except Exception:  # noqa: BLE001 - recording must never crash the monitor
                self._logger.exception("failed to record health for %s", service.name)
            if not status.healthy and self._events is not None:
                self._events.emit(
                    "ServiceUnhealthy",
                    {"service": service.name, "detail": status.detail},
                    source=self.name,
                )
        return results

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.check_all()
