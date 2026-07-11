"""Plugin layer (ADR-0041): external integrations that self-register.

The boundary (``Plugin`` protocol + ``BasePlugin``) landed in Sprint 4; Sprint 7
adds the config-driven ``PluginManager`` and the first concrete plugins
(filesystem, web). Each plugin module exposes ``build(config) -> Plugin``.
"""

from __future__ import annotations

from atlas.plugins.base import BasePlugin, Plugin
from atlas.plugins.manager import PluginManager

__all__ = ["Plugin", "BasePlugin", "PluginManager"]
