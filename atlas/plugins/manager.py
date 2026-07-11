"""Plugin manager: config-driven loading + lifecycle (ADR-0049).

Plugins are loaded from an explicit list of dotted module paths
(``config.plugins.enabled``) — fail-closed: only listed modules load, nothing is
auto-discovered from disk. Each plugin module exposes a factory::

    def build(config) -> Plugin

The manager imports each module, builds the plugin, and (during bootstrap) calls
``plugin.register(kernel)`` so it can advertise capabilities (ADR-0040) and tools
(ADR-0050). The manager is itself a kernel Service that owns plugin lifecycle, so
one ``plugins`` entry appears in ``system.health`` and start/stop fan out to all
loaded plugins.

A single misbehaving plugin never brings down the kernel: load/register/lifecycle
errors are captured per-plugin and surfaced via health instead of raising.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from atlas.exceptions import PluginLoadError
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application
    from atlas.plugins.base import Plugin


class PluginManager:
    name = "plugins"

    def __init__(
        self,
        plugins: "list[Plugin] | None" = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._plugins: list[Plugin] = list(plugins or [])
        self._errors: dict[str, str] = {}
        self._logger = logger or logging.getLogger("atlas.plugins")

    # --- loading --------------------------------------------------------
    def load(self, config: "AtlasConfig") -> "list[Plugin]":
        """Import + build every enabled plugin module. Bad plugins are skipped
        (recorded in ``errors``) so the kernel still boots."""
        for path in config.plugins.enabled:
            try:
                self._plugins.append(self._build_one(path, config))
                self._logger.info("loaded plugin module %s", path)
            except Exception as exc:  # noqa: BLE001 - one bad plugin must not stop boot
                self._errors[path] = str(exc)
                self._logger.exception("failed to load plugin %s", path)
        return self._plugins

    @staticmethod
    def _build_one(module_path: str, config: "AtlasConfig") -> "Plugin":
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001
            raise PluginLoadError(
                f"cannot import plugin module '{module_path}': {exc}",
                module=module_path,
            ) from exc
        builder = getattr(module, "build", None)
        if not callable(builder):
            raise PluginLoadError(
                f"plugin module '{module_path}' has no build(config) factory",
                module=module_path,
            )
        plugin = builder(config)
        return plugin

    def register_all(self, kernel: "Application") -> None:
        """Let each loaded plugin self-register capabilities + tools."""
        for plugin in list(self._plugins):
            try:
                plugin.register(kernel)
            except Exception as exc:  # noqa: BLE001
                self._errors[plugin.name] = f"register: {exc}"
                self._logger.exception("plugin %s failed to register", plugin.name)

    # --- introspection --------------------------------------------------
    @property
    def plugins(self) -> "list[Plugin]":
        return list(self._plugins)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    def names(self) -> list[str]:
        return [p.name for p in self._plugins]

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": p.name, "version": getattr(p, "version", "?")} for p in self._plugins]

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        for plugin in self._plugins:
            try:
                plugin.start()
            except Exception as exc:  # noqa: BLE001
                self._errors[plugin.name] = f"start: {exc}"
                self._logger.exception("plugin %s failed to start", plugin.name)

    def stop(self) -> None:
        for plugin in reversed(self._plugins):
            try:
                plugin.stop()
            except Exception:  # noqa: BLE001 - stop must never raise
                self._logger.exception("plugin %s failed to stop", plugin.name)

    def health_check(self) -> HealthStatus:
        loaded = self.names()
        detail = f"{len(loaded)} plugin(s): {', '.join(loaded) or 'none'}"
        if self._errors:
            detail += f"; {len(self._errors)} error(s)"
        return HealthStatus(
            healthy=not self._errors,
            detail=detail,
            data={"loaded": loaded, "errors": self._errors},
        )
