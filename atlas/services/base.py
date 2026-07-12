"""Service protocol and health status.

A service is a capability with a lifecycle. The kernel starts/stops services and
polls their health; it never needs to know what a service does internally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Health severities (S22). `degraded` is the middle tier: the service is *up* and
# `healthy` stays True (it should not fail the system), but it is running below full
# capability (e.g. an optional model isn't pulled, a browser engine isn't installed).
SEVERITY_OK = "ok"
SEVERITY_DEGRADED = "degraded"
SEVERITY_FAILED = "failed"


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    # Explicit tier; when unset it is derived from `healthy` (ok/failed) so every
    # existing call site keeps working without change (back-compat).
    severity: str | None = None

    @property
    def level(self) -> str:
        """The severity tier, derived from ``healthy`` when not set explicitly."""
        if self.severity is not None:
            return self.severity
        return SEVERITY_OK if self.healthy else SEVERITY_FAILED

    @property
    def degraded(self) -> bool:
        return self.level == SEVERITY_DEGRADED

    @classmethod
    def ok(cls, detail: str = "ok", **data: Any) -> "HealthStatus":
        return cls(healthy=True, detail=detail, data=data, severity=SEVERITY_OK)

    @classmethod
    def degraded_status(cls, detail: str, **data: Any) -> "HealthStatus":
        """Up but below full capability: ``healthy`` stays True, tier = degraded."""
        return cls(healthy=True, detail=detail, data=data, severity=SEVERITY_DEGRADED)

    @classmethod
    def fail(cls, detail: str, **data: Any) -> "HealthStatus":
        return cls(healthy=False, detail=detail, data=data, severity=SEVERITY_FAILED)


@runtime_checkable
class Service(Protocol):
    name: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health_check(self) -> HealthStatus: ...
