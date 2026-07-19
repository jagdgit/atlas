"""Configuration Manager service (Phase A · PHASE_A_PLAN §A.2, P6/B6).

Owns **per-mission, versioned configuration**. Every write validates against a registered
Pydantic schema (invalid → rejected, never stored) and produces a **new immutable version**;
editing never mutates a stored row, so results stay reproducible. ``Mission.active_config_id``
points at the version a worker currently reads; ``set_active`` flips it explicitly.

A Kernel Service (registered lifecycle + capability). It knows nothing about any specific
mission type — those are just registered schemas (P5/P7).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from atlas.configuration.schemas import ConfigSchemaError, SchemaRegistry, default_registry
from atlas.exceptions.base import AtlasError
from atlas.models.config import MissionConfig
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.configuration.repository import ConfigRepository
    from atlas.events.dispatcher import EventDispatcher
    from atlas.missions.repository import MissionRepository


class ConfigError(AtlasError):
    """A configuration operation was invalid (missing mission/config, no prior version)."""


class ConfigurationService:
    name = "configuration"
    VERSION = "1"

    def __init__(
        self,
        repo: "ConfigRepository",
        mission_repo: "MissionRepository",
        *,
        registry: SchemaRegistry | None = None,
        events: "EventDispatcher | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._missions = mission_repo
        self._registry = registry or default_registry()
        self._events = events
        self._logger = logger or logging.getLogger("atlas.configuration")

    @property
    def registry(self) -> SchemaRegistry:
        return self._registry

    # --- writes ---------------------------------------------------------

    def create_config(
        self,
        mission_id: UUID | str,
        schema_type: str,
        document: dict[str, Any],
        *,
        change_note: str = "",
        activate: bool | None = None,
    ) -> MissionConfig:
        """Create version 1+ of a mission's config (validated).

        ``activate`` defaults to auto-activating the **first** config (when the mission has
        none yet), matching template instantiation; pass an explicit bool to override.
        """
        self._require_mission(mission_id)
        normalized, schema_version = self._registry.validate(schema_type, document)
        version = self._repo.next_version(mission_id)
        cfg = self._repo.create_version(
            mission_id=mission_id,
            version=version,
            schema_type=schema_type,
            schema_version=schema_version,
            document=normalized,
            change_note=change_note,
        )
        should_activate = (
            activate
            if activate is not None
            else self._repo.get_active(mission_id) is None
        )
        if should_activate:
            self._set_active_row(mission_id, cfg)
        self._journal(mission_id, "config_created", change_note or f"config v{version}", cfg)
        self._emit("MissionConfigCreated", mission_id, cfg)
        return cfg

    def update_config(
        self,
        mission_id: UUID | str,
        document: dict[str, Any],
        *,
        change_note: str = "",
        activate: bool = False,
    ) -> MissionConfig:
        """Create the next version, reusing the latest version's ``schema_type``.

        Does **not** activate by default (v6 B6: activation is an explicit operator choice);
        pass ``activate=True`` to flip the active pointer at the same time.
        """
        latest = self._latest(mission_id)
        normalized, schema_version = self._registry.validate(latest.schema_type, document)
        version = self._repo.next_version(mission_id)
        cfg = self._repo.create_version(
            mission_id=mission_id,
            version=version,
            schema_type=latest.schema_type,
            schema_version=schema_version,
            document=normalized,
            change_note=change_note,
        )
        if activate:
            self._set_active_row(mission_id, cfg)
        self._journal(mission_id, "config_updated", change_note or f"config v{version}", cfg)
        self._emit("MissionConfigUpdated", mission_id, cfg)
        return cfg

    def set_active(self, mission_id: UUID | str, version: int) -> MissionConfig:
        cfg = self._repo.get_version(mission_id, version)
        if cfg is None:
            raise ConfigError(
                "config version not found", mission_id=str(mission_id), version=version
            )
        self._set_active_row(mission_id, cfg)
        self._journal(mission_id, "config_activated", f"activated v{version}", cfg)
        self._emit("MissionConfigActivated", mission_id, cfg)
        return cfg

    # --- reads ----------------------------------------------------------

    def get_active(self, mission_id: UUID | str) -> MissionConfig | None:
        return self._repo.get_active(mission_id)

    def get_version(self, mission_id: UUID | str, version: int) -> MissionConfig | None:
        return self._repo.get_version(mission_id, version)

    def list_versions(self, mission_id: UUID | str) -> list[MissionConfig]:
        return self._repo.list_versions(mission_id)

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(
            f"{len(self._registry.known())} config schema(s) registered",
            schemas=self._registry.known(),
        )

    # --- helpers --------------------------------------------------------

    def _require_mission(self, mission_id: UUID | str) -> None:
        if self._missions.get(mission_id) is None:
            raise ConfigError("mission not found", mission_id=str(mission_id))

    def _latest(self, mission_id: UUID | str) -> MissionConfig:
        versions = self._repo.list_versions(mission_id)
        if not versions:
            raise ConfigError(
                "no existing config to update; use create_config first",
                mission_id=str(mission_id),
            )
        return versions[0]

    def _set_active_row(self, mission_id: UUID | str, cfg: MissionConfig) -> None:
        self._missions.set_active_config(mission_id, cfg.id)

    def _journal(
        self, mission_id: UUID | str, action: str, reason: str, cfg: MissionConfig
    ) -> None:
        try:
            self._missions.add_journal(
                mission_id,
                action,
                reason,
                {
                    "config_id": cfg.id,
                    "version": cfg.version,
                    "schema_type": cfg.schema_type,
                    "schema_version": cfg.schema_version,
                },
            )
        except Exception:  # noqa: BLE001 - journaling must not break a config write
            self._logger.exception("failed to journal %s for mission %s", action, mission_id)

    def _emit(self, event_type: str, mission_id: UUID | str, cfg: MissionConfig) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(
                event_type,
                {
                    "mission_id": str(mission_id),
                    "config_id": cfg.id,
                    "version": cfg.version,
                    "schema_type": cfg.schema_type,
                },
                source=self.name,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break a config write
            self._logger.exception("failed to emit %s", event_type)
