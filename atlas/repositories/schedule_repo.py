"""Repository for ``scheduler.schedules`` (Phase A · §A.3).

The only SQL layer for durable recurrence (ADR-0027); returns typed models (ADR-0036). The
recurrence *logic* (the tick that enqueues due schedules) lives in ``ScheduleService``; this
layer persists rows and does the atomic **claim-and-advance** of due schedules.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.schedule import Schedule
from atlas.repositories.base import BaseRepository

_COLS = (
    "id, task_type, payload, interval_seconds, next_run_at, last_run_at, "
    "enabled, mission_id, worker_id, created_at, updated_at"
)


class ScheduleRepository(BaseRepository):
    def create(
        self,
        *,
        task_type: str,
        interval_seconds: int,
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        enabled: bool = True,
        first_run_delay: float = 0.0,
    ) -> Schedule:
        row = self.fetch_one(
            f"""
            INSERT INTO scheduler.schedules (
                task_type, payload, interval_seconds, next_run_at, enabled,
                mission_id, worker_id
            ) VALUES (%s, %s, %s, now() + make_interval(secs => %s), %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                task_type,
                Jsonb(payload or {}),
                interval_seconds,
                first_run_delay,
                enabled,
                mission_id,
                worker_id,
            ),
        )
        return Schedule.from_row(row)

    def get(self, schedule_id: UUID | str) -> Schedule | None:
        row = self.fetch_one(
            f"SELECT {_COLS} FROM scheduler.schedules WHERE id = %s",
            (str(schedule_id),),
        )
        return Schedule.from_row(row) if row else None

    def list(
        self,
        *,
        enabled: bool | None = None,
        mission_id: str | None = None,
        limit: int = 200,
    ) -> list[Schedule]:
        clauses: list[str] = []
        params: list[Any] = []
        if enabled is not None:
            clauses.append("enabled = %s")
            params.append(enabled)
        if mission_id is not None:
            clauses.append("mission_id = %s")
            params.append(mission_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.fetch_all(
            f"""
            SELECT {_COLS} FROM scheduler.schedules
            {where}
            ORDER BY next_run_at ASC
            LIMIT %s
            """,
            tuple(params),
        )
        return Schedule.from_rows(rows)

    def claim_due(self, *, limit: int = 100) -> list[Schedule]:
        """Atomically claim due enabled schedules and advance their ``next_run_at``.

        ``FOR UPDATE SKIP LOCKED`` makes this safe under multiple scheduler workers. Advancing
        to ``now() + interval`` (not ``next_run_at + interval``) means a schedule that fell
        behind during downtime fires **once** on resume, then continues on cadence — no
        catch-up storm. Returns the claimed rows (task_type/payload are unchanged by the
        UPDATE, so the caller enqueues against the correct values).
        """
        rows = self.fetch_all(
            f"""
            UPDATE scheduler.schedules AS s
            SET last_run_at = now(),
                next_run_at = now() + make_interval(secs => s.interval_seconds),
                updated_at = now()
            WHERE s.id IN (
                SELECT id FROM scheduler.schedules
                WHERE enabled AND next_run_at <= now()
                ORDER BY next_run_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING {', '.join('s.' + c for c in _COLS.split(', '))}
            """,
            (limit,),
        )
        return Schedule.from_rows(rows)

    def set_enabled(self, schedule_id: UUID | str, enabled: bool) -> bool:
        return (
            self.execute(
                """
                UPDATE scheduler.schedules
                SET enabled = %s, updated_at = now()
                WHERE id = %s
                """,
                (enabled, str(schedule_id)),
            )
            > 0
        )

    def set_interval(self, schedule_id: UUID | str, interval_seconds: int) -> bool:
        return (
            self.execute(
                """
                UPDATE scheduler.schedules
                SET interval_seconds = %s, updated_at = now()
                WHERE id = %s
                """,
                (interval_seconds, str(schedule_id)),
            )
            > 0
        )

    def disable_for_mission(self, mission_id: UUID | str) -> int:
        """Disable every schedule owned by a mission (used on mission archive)."""
        return self.execute(
            """
            UPDATE scheduler.schedules
            SET enabled = false, updated_at = now()
            WHERE mission_id = %s AND enabled
            """,
            (str(mission_id),),
        )

    def count_enabled(self) -> int:
        return self.fetch_val(
            "SELECT count(*) FROM scheduler.schedules WHERE enabled"
        )

    def delete(self, schedule_id: UUID | str) -> bool:
        return (
            self.execute(
                "DELETE FROM scheduler.schedules WHERE id = %s", (str(schedule_id),)
            )
            > 0
        )
