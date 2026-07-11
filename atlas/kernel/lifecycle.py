"""Lifecycle management: ordered start/stop of registered services.

Services start in registration order and stop in reverse order (like a stack),
so dependencies come up before dependents and go down after them.
"""

from __future__ import annotations

import logging

from atlas.kernel.registry import ServiceRegistry


class LifecycleManager:
    def __init__(
        self, registry: ServiceRegistry, logger: logging.Logger | None = None
    ) -> None:
        self._registry = registry
        self._logger = logger or logging.getLogger("atlas.kernel")
        self._started: list[str] = []

    def start_all(self) -> None:
        for service in self._registry.all():
            self._logger.info("starting service: %s", service.name)
            service.start()
            self._started.append(service.name)

    def stop_all(self) -> None:
        for name in reversed(self._started):
            service = self._registry.get(name)
            self._logger.info("stopping service: %s", service.name)
            try:
                service.stop()
            except Exception:  # noqa: BLE001 - continue shutting down others
                self._logger.exception("error stopping service: %s", service.name)
        self._started.clear()
