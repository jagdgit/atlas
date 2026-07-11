"""Atlas microkernel: lifecycle, DI, registry, events wiring.

Small and stable. Knows nothing about documents, embeddings, or browsers.
"""

from __future__ import annotations

from atlas.kernel.application import Application
from atlas.kernel.bootstrap import build_application
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.lifecycle import LifecycleManager
from atlas.kernel.registry import ServiceRegistry
from atlas.kernel.service_container import ServiceContainer
from atlas.kernel.tools import Tool, ToolRegistry

__all__ = [
    "Application",
    "build_application",
    "CapabilityRegistry",
    "LifecycleManager",
    "ServiceRegistry",
    "ServiceContainer",
    "Tool",
    "ToolRegistry",
]
