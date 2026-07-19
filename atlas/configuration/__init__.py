"""Configuration Manager subsystem (Phase A · PHASE_A_PLAN §A.2, P6).

Per-mission, DB-persisted, **versioned** configuration validated by registered Pydantic
schemas. Editing produces a new immutable version; the active version a worker reads is an
explicit pointer on the mission. Nothing about a mission is hardcoded in a worker (P6).
"""

from __future__ import annotations

from atlas.configuration.repository import ConfigRepository
from atlas.configuration.schemas import (
    ConfigSchemaError,
    SchemaRegistry,
    default_registry,
)
from atlas.configuration.service import ConfigError, ConfigurationService

__all__ = [
    "ConfigurationService",
    "ConfigRepository",
    "SchemaRegistry",
    "ConfigSchemaError",
    "ConfigError",
    "default_registry",
]
