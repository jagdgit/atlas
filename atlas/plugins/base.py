"""Plugin base + protocol (ADR-0041).

Everything external to Atlas (filesystem, browser, github, postgres, email,
shell, weather, scada, calendar) becomes a plugin that **self-registers** with
the kernel and advertises capabilities, so adding an integration in five years
never requires touching the kernel or existing agents.

Only the boundary lands in Sprint 4 — concrete plugins are built in Sprint 7.
A plugin's ``register(kernel)`` is where it calls
``kernel.capabilities.register(name, provider)`` (ADR-0040).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.kernel.application import Application


@runtime_checkable
class Plugin(Protocol):
    name: str
    version: str

    def register(self, kernel: "Application") -> None:
        """Self-register with the kernel (typically register capabilities)."""
        ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def health_check(self) -> HealthStatus: ...


class BasePlugin:
    """Convenience base with no-op lifecycle; override what you need.

    Subclasses set ``name``/``version`` and typically override ``register`` to
    advertise their capabilities to ``kernel.capabilities``.
    """

    name: str = "plugin"
    version: str = "0.0.0"

    def register(self, kernel: "Application") -> None:  # pragma: no cover - override
        return None

    def start(self) -> None:  # pragma: no cover - override
        return None

    def stop(self) -> None:  # pragma: no cover - override
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(f"{self.name} plugin ready")
