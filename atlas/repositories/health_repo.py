"""Repository for ``system.health`` (health check history).

Converted to the typed-model boundary (ADR-0036): reads return ``HealthRecord``
models rather than raw dict rows.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from atlas.models import HealthRecord
from atlas.repositories.base import BaseRepository


class HealthRepository(BaseRepository):
    def record(
        self,
        service: str,
        healthy: bool,
        detail: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO system.health (service, status, details)
            VALUES (%s, %s, %s)
            """,
            (
                service,
                "healthy" if healthy else "unhealthy",
                Jsonb({"detail": detail, **(data or {})}),
            ),
        )

    def latest(self, service: str) -> HealthRecord | None:
        row = self.fetch_one(
            """
            SELECT * FROM system.health
            WHERE service = %s
            ORDER BY checked_at DESC
            LIMIT 1
            """,
            (service,),
        )
        return HealthRecord.from_row(row) if row else None

    def recent(self, limit: int = 50) -> list[HealthRecord]:
        rows = self.fetch_all(
            "SELECT * FROM system.health ORDER BY checked_at DESC LIMIT %s",
            (limit,),
        )
        return HealthRecord.from_rows(rows)
