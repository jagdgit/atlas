"""Plugin/capability errors (load, capability missing)."""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class PluginError(AtlasError):
    """Any failure loading or running a plugin."""


class PluginLoadError(PluginError):
    """A plugin could not be discovered, imported, or registered."""


class CapabilityMissingError(PluginError):
    """A requested capability is not registered/available."""


class ToolError(PluginError):
    """A tool failed to register or execute."""


class ToolNotFoundError(ToolError):
    """A requested tool is not registered."""
