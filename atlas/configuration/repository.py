"""Repository for ``config.mission_configs`` (Phase A · §A.2).

The only SQL layer for mission configuration (ADR-0027); returns typed models (ADR-0036).
Versions are **append-only**: there is no UPDATE of a stored document — ``create_version``
always inserts the next version. The active-version pointer lives on ``mission.missions``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.config import MissionConfig
from atlas.repositories.base import BaseRepository

_CFG_COLS = (
    "id, mission_id, version, schema_type, schema_version, document, "
    "change_note, created_at"
)


class ConfigRepository(BaseRepository):
    def next_version(self, mission_id: UUID | str) -> int:
        current = self.fetch_val(
            "SELECT max(version) FROM config.mission_configs WHERE mission_id = %s",
            (str(mission_id),),
        )
        return int(current) + 1 if current is not None else 1

    def create_version(
        self,
        *,
        mission_id: UUID | str,
        version: int,
        schema_type: str,
        schema_version: int,
        document: dict[str, Any],
        change_note: str = "",
    ) -> MissionConfig:
        row = self.fetch_one(
            f"""
            INSERT INTO config.mission_configs (
                mission_id, version, schema_type, schema_version, document, change_note
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {_CFG_COLS}
            """,
            (
                str(mission_id),
                version,
                schema_type,
                schema_version,
                Jsonb(document),
                change_note,
            ),
        )
        return MissionConfig.from_row(row)

    def get_by_id(self, config_id: UUID | str) -> MissionConfig | None:
        row = self.fetch_one(
            f"SELECT {_CFG_COLS} FROM config.mission_configs WHERE id = %s",
            (str(config_id),),
        )
        return MissionConfig.from_row(row) if row else None

    def get_version(
        self, mission_id: UUID | str, version: int
    ) -> MissionConfig | None:
        row = self.fetch_one(
            f"""
            SELECT {_CFG_COLS} FROM config.mission_configs
            WHERE mission_id = %s AND version = %s
            """,
            (str(mission_id), version),
        )
        return MissionConfig.from_row(row) if row else None

    def get_active(self, mission_id: UUID | str) -> MissionConfig | None:
        """The version ``mission.missions.active_config_id`` currently points at."""
        row = self.fetch_one(
            f"""
            SELECT {', '.join('c.' + c for c in _CFG_COLS.split(', '))}
            FROM config.mission_configs c
            JOIN mission.missions m ON m.active_config_id = c.id
            WHERE m.id = %s
            """,
            (str(mission_id),),
        )
        return MissionConfig.from_row(row) if row else None

    def list_versions(self, mission_id: UUID | str) -> list[MissionConfig]:
        rows = self.fetch_all(
            f"""
            SELECT {_CFG_COLS} FROM config.mission_configs
            WHERE mission_id = %s
            ORDER BY version DESC
            """,
            (str(mission_id),),
        )
        return MissionConfig.from_rows(rows)
