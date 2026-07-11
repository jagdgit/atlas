"""Dependency injection container.

Holds shared dependencies (config, db manager, event dispatcher, ...) and
resolves them by key. Supports pre-built instances and lazy singleton factories.
This is how services/plugins obtain what they need without constructing
infrastructure themselves.
"""

from __future__ import annotations

from typing import Any, Callable


class ServiceContainer:
    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._singleton: dict[str, bool] = {}

    def register_instance(self, key: str, instance: Any) -> None:
        self._instances[key] = instance

    def register_factory(
        self, key: str, factory: Callable[[], Any], *, singleton: bool = True
    ) -> None:
        self._factories[key] = factory
        self._singleton[key] = singleton

    def has(self, key: str) -> bool:
        return key in self._instances or key in self._factories

    def resolve(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            value = self._factories[key]()
            if self._singleton.get(key, True):
                self._instances[key] = value
            return value
        raise KeyError(f"nothing registered for key: {key}")

    def keys(self) -> list[str]:
        return sorted(set(self._instances) | set(self._factories))
