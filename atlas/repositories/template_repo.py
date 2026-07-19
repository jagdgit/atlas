"""Repository for ``mission.templates`` (Phase A · §A.5).

The only SQL layer for mission templates (ADR-0027); returns typed models (ADR-0036).
Built-ins are upserted by name on boot (``upsert_by_name``); the app is the source of truth.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.template import MissionTemplate
from atlas.repositories.base import BaseRepository

_COLS = (
    "id, name, template_version, description, worker_specs, config_schema_type, "
    "config_schema_version, default_config, knowledge_domains, success_criteria, "
    "created_at, updated_at"
)


class TemplateRepository(BaseRepository):
    def upsert_by_name(
        self,
        *,
        name: str,
        template_version: int,
        config_schema_type: str,
        config_schema_version: int = 1,
        description: str = "",
        worker_specs: list[dict[str, Any]] | None = None,
        default_config: dict[str, Any] | None = None,
        knowledge_domains: list[str] | None = None,
        success_criteria: dict[str, Any] | None = None,
    ) -> MissionTemplate:
        row = self.fetch_one(
            f"""
            INSERT INTO mission.templates (
                name, template_version, description, worker_specs, config_schema_type,
                config_schema_version, default_config, knowledge_domains, success_criteria
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                template_version = EXCLUDED.template_version,
                description = EXCLUDED.description,
                worker_specs = EXCLUDED.worker_specs,
                config_schema_type = EXCLUDED.config_schema_type,
                config_schema_version = EXCLUDED.config_schema_version,
                default_config = EXCLUDED.default_config,
                knowledge_domains = EXCLUDED.knowledge_domains,
                success_criteria = EXCLUDED.success_criteria,
                updated_at = now()
            RETURNING {_COLS}
            """,
            (
                name,
                template_version,
                description,
                Jsonb(worker_specs or []),
                config_schema_type,
                config_schema_version,
                Jsonb(default_config or {}),
                list(knowledge_domains or []),
                Jsonb(success_criteria or {}),
            ),
        )
        return MissionTemplate.from_row(row)

    def get_by_name(self, name: str) -> MissionTemplate | None:
        row = self.fetch_one(
            f"SELECT {_COLS} FROM mission.templates WHERE name = %s", (name,)
        )
        return MissionTemplate.from_row(row) if row else None

    def get(self, template_id: UUID | str) -> MissionTemplate | None:
        row = self.fetch_one(
            f"SELECT {_COLS} FROM mission.templates WHERE id = %s", (str(template_id),)
        )
        return MissionTemplate.from_row(row) if row else None

    def list(self) -> list[MissionTemplate]:
        rows = self.fetch_all(
            f"SELECT {_COLS} FROM mission.templates ORDER BY name ASC"
        )
        return MissionTemplate.from_rows(rows)
