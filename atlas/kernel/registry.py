"""Service registry: holds live services by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.services.base import Service


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, Service] = {}
        self._order: list[str] = []

    def register(self, service: Service) -> None:
        if service.name in self._services:
            raise ValueError(f"service already registered: {service.name}")
        self._services[service.name] = service
        self._order.append(service.name)

    def get(self, name: str) -> Service:
        try:
            return self._services[name]
        except KeyError:
            raise KeyError(f"service not registered: {name}") from None

    def has(self, name: str) -> bool:
        return name in self._services

    def names(self) -> list[str]:
        return list(self._order)

    def all(self) -> list[Service]:
        return [self._services[name] for name in self._order]
