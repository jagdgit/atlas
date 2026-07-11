"""The Atlas application object — the running microkernel.

Holds the wired-together kernel primitives (config, logger, events, registry,
container, lifecycle) and exposes the small set of Kernel APIs that services,
plugins, and agents use. It deliberately knows nothing about documents,
embeddings, browsers, etc.
"""

from __future__ import annotations

import logging
import signal
import threading

from atlas.config import AtlasConfig
from atlas.events.dispatcher import EventDispatcher
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.lifecycle import LifecycleManager
from atlas.kernel.registry import ServiceRegistry
from atlas.kernel.service_container import ServiceContainer
from atlas.kernel.tools import ToolRegistry
from atlas.services.base import HealthStatus, Service


class Application:
    def __init__(
        self,
        *,
        config: AtlasConfig,
        logger: logging.Logger,
        events: EventDispatcher,
        registry: ServiceRegistry,
        container: ServiceContainer,
        lifecycle: LifecycleManager,
        capabilities: CapabilityRegistry | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.events = events
        self.registry = registry
        self.container = container
        self.lifecycle = lifecycle
        self.capabilities = capabilities or CapabilityRegistry()
        self.tools = tools or ToolRegistry()
        self._stop_event = threading.Event()

    # --- Kernel APIs -----------------------------------------------------
    def service(self, name: str) -> Service:
        return self.registry.get(name)

    def resolve(self, key: str):
        return self.container.resolve(key)

    def capability(self, name: str):
        """Return the provider for a capability (ADR-0040)."""
        return self.capabilities.get(name)

    def invoke_tool(self, name: str, **kwargs):
        """Invoke a registered tool by name (ADR-0050)."""
        return self.tools.invoke(name, **kwargs)

    # --- Lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.logger.info(
            "Atlas %s starting...", self.config.system.version
        )
        self.lifecycle.start_all()
        self.events.emit("KernelStarted", source="kernel")
        self.logger.info("Atlas is ready.")

    def stop(self) -> None:
        self.events.emit("KernelStopping", source="kernel")
        self.lifecycle.stop_all()
        self.logger.info("Atlas stopped.")

    def health(self) -> dict[str, HealthStatus]:
        return {svc.name: svc.health_check() for svc in self.registry.all()}

    def healthy(self) -> bool:
        return all(status.healthy for status in self.health().values())

    # --- Blocking run ----------------------------------------------------
    def run_forever(self) -> None:
        """Start, install signal handlers, and block until SIGINT/SIGTERM."""
        self.start()
        self._install_signal_handlers()
        try:
            self._stop_event.wait()
        finally:
            self.stop()

    def request_shutdown(self) -> None:
        self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            self.logger.info("received signal %s, shutting down", signum)
            self.request_shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except ValueError:
                # Not in the main thread; skip signal installation.
                pass
