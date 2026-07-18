"""Repository for ``audit.events`` (persistent event log).

The in-process event dispatcher works without this. This repo persists events for
replay/recovery: ``record`` is the original explicit-append path; ``persist`` (Phase 0 ·
ATLAS_OS_ROADMAP §2.5, P1) is the durable-bus path — the dispatcher calls it for every
published event (idempotent on the event UUID) so the stream survives a restart and can
be replayed (e.g. to backfill an SSE client) (ADR-0012 / ADR-0025).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

if TYPE_CHECKING:
    from atlas.events.event import Event

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

    def persist(self, event: "Event") -> None:
        """Append a dispatched event, keyed by its UUID (a replayed id is ignored)."""
        self.execute(
            """
            INSERT INTO audit.events (id, event_type, payload, source, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                str(event.id),
                event.type,
                Jsonb(event.payload or {}),
                event.source,
                event.created_at,
            ),
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

    def recent(
        self, *, limit: int = 100, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Most recent events first (optionally filtered by type) — for the dashboard."""
        if event_type is not None:
            return self.fetch_all(
                """
                SELECT * FROM audit.events
                WHERE event_type = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (event_type, limit),
            )
        return self.fetch_all(
            "SELECT * FROM audit.events ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )

    def since(self, created_at: Any, *, limit: int = 500) -> list[dict[str, Any]]:
        """Events strictly after a timestamp, oldest first — for replay/backfill."""
        return self.fetch_all(
            """
            SELECT * FROM audit.events
            WHERE created_at > %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (created_at, limit),
        )

    def count(self) -> int:
        return int(self.fetch_val("SELECT count(*) FROM audit.events") or 0)

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

    def mark_processed(self, event_id: UUID | str) -> bool:
        """Convenience wrapper used by durable-bus consumers."""
        return self.mark(event_id, "processed")
