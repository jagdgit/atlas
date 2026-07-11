"""Tool Registry (ADR-0050).

A tool is a *named, invokable action* a plugin exposes to agents (e.g.
``web.fetch``, ``fs.read``). Plugins register tools during ``register(kernel)``;
agents (Sprint 8) select from the catalog and invoke by name. This complements
the CapabilityRegistry (ADR-0040):

    capabilities = WHAT subsystems exist   (by capability name, coarse)
    tools        = WHICH actions are callable (by tool name, fine-grained)

Kept deliberately small: a tool is a callable + human/LLM-readable description +
optional parameter hints. No schema engine — Sprint 8 can layer richer typing on
top if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from atlas.exceptions import ToolError, ToolNotFoundError


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    func: Callable[..., Any]
    description: str = ""
    params: dict[str, str] = field(default_factory=dict)  # name -> human hint
    plugin: str | None = None  # owning plugin, for introspection

    def invoke(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        description: str = "",
        params: dict[str, str] | None = None,
        plugin: str | None = None,
    ) -> None:
        """Register a callable tool. Raises if the name is already taken."""
        if name in self._tools:
            raise ToolError(f"tool '{name}' already registered", tool=name)
        self._tools[name] = Tool(
            name=name,
            func=func,
            description=description,
            params=dict(params or {}),
            plugin=plugin,
        )

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(
                f"no tool registered named '{name}'", tool=name
            ) from None

    def invoke(self, name: str, **kwargs: Any) -> Any:
        return self.get(name).invoke(**kwargs)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        """Catalog for API/CLI/agent introspection."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "params": t.params,
                "plugin": t.plugin,
            }
            for t in sorted(self._tools.values(), key=lambda x: x.name)
        ]
