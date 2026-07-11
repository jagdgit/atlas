"""Configuration errors."""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class ConfigError(AtlasError):
    """Configuration is missing, malformed, or fails validation."""
