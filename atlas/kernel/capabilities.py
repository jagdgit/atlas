"""Capability Registry (ADR-0040).

Maps a capability *name* to the provider that offers it. Agents ask the kernel
"do I have X?" instead of importing modules, so plugins/services are truly
optional and swappable (ADR-0041) and an agent can degrade gracefully when a
capability is absent rather than failing at import time.

This complements — it does not replace — the DI container (ADR-0043):

    container      = HOW to build a dependency (by key)
    capabilities   = WHAT is available to agents (by capability name)

Kept intentionally small to honour "the kernel is not a god object".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.exceptions import CapabilityMissingError


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    provider: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, name: str, provider: Any, **metadata: Any) -> None:
        """Advertise ``name`` as provided by ``provider`` (last registration wins)."""
        self._capabilities[name] = Capability(name, provider, dict(metadata))

    def has(self, name: str) -> bool:
        return name in self._capabilities

    def get(self, name: str) -> Any:
        try:
            return self._capabilities[name].provider
        except KeyError:
            raise CapabilityMissingError(
                f"no capability registered named '{name}'", capability=name
            ) from None

    def names(self) -> list[str]:
        return sorted(self._capabilities)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Return capability name -> metadata (for health/introspection)."""
        return {
            name: dict(cap.metadata) for name, cap in sorted(self._capabilities.items())
        }
