"""Service protocol and health status.

A service is a capability with a lifecycle. The kernel starts/stops services and
polls their health; it never needs to know what a service does internally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, detail: str = "ok", **data: Any) -> "HealthStatus":
        return cls(healthy=True, detail=detail, data=data)

    @classmethod
    def fail(cls, detail: str, **data: Any) -> "HealthStatus":
        return cls(healthy=False, detail=detail, data=data)


@runtime_checkable
class Service(Protocol):
    name: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health_check(self) -> HealthStatus: ...
