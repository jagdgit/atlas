"""Repository for ``audit.events`` (persistent event log).

The in-process event dispatcher (Sprint 1.5) works without this. This repo
exists so events can optionally be persisted for replay/recovery later, without
moving code around (ADR-0012 / ADR-0025).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

VALID_STATUSES = {"pending", "processed", "failed"}


class EventRepository(BaseRepository):
    def record(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO audit.events (event_type, payload, source)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (event_type, Jsonb(payload or {}), source),
        )

    def get(self, event_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM audit.events WHERE id = %s", (str(event_id),)
        )

    def list_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM audit.events
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )

    def mark(self, event_id: UUID | str, status: str) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return (
            self.execute(
                """
                UPDATE audit.events
                SET status = %s,
                    processed_at = CASE WHEN %s IN ('processed','failed')
                                        THEN now() ELSE processed_at END
                WHERE id = %s
                """,
                (status, status, str(event_id)),
            )
            > 0
        )
