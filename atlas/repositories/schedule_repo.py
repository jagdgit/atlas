"""Repository for ``scheduler.schedules`` (Phase A · §A.3 / OI-A1).

The only SQL layer for durable recurrence (ADR-0027); returns typed models (ADR-0036). The
recurrence *logic* (the tick that enqueues due schedules) lives in ``ScheduleService``; this
layer persists rows and does the atomic **claim-and-advance** of due schedules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from atlas.models.schedule import KIND_CRON, KIND_INTERVAL, Schedule
from atlas.repositories.base import BaseRepository
from atlas.scheduler.cron import next_run_after, validate_cron

_COLS = (
    "id, task_type, payload, interval_seconds, next_run_at, last_run_at, "
    "enabled, mission_id, worker_id, kind, cron_expr, created_at, updated_at"
)


class ScheduleRepository(BaseRepository):
    def create(
        self,
        *,
        task_type: str,
        interval_seconds: int = 60,
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        enabled: bool = True,
        first_run_delay: float = 0.0,
        kind: str = KIND_INTERVAL,
        cron_expr: str | None = None,
    ) -> Schedule:
        kind = (kind or KIND_INTERVAL).strip().lower()
        cron: str | None = None
        if kind == KIND_CRON:
            cron = validate_cron(str(cron_expr or ""))
            # Sentinel — unused for advance; CHECK still requires >= 1.
            interval_seconds = max(1, int(interval_seconds or 60))
            after = datetime.now(timezone.utc) + timedelta(seconds=float(first_run_delay or 0))
            # First fire: next cron slot at/after ``after`` (strictly after after-1s).
            next_at = next_run_after(cron, after=after - timedelta(seconds=1))
        elif kind == KIND_INTERVAL:
            if cron_expr:
                raise ValueError("cron_expr is only valid for kind='cron'")
            interval_seconds = max(1, int(interval_seconds))
            next_at = None  # SQL: now() + first_run_delay
        else:
            raise ValueError(f"unknown schedule kind: {kind!r}")

        if next_at is not None:
            row = self.fetch_one(
                f"""
                INSERT INTO scheduler.schedules (
                    task_type, payload, interval_seconds, next_run_at, enabled,
                    mission_id, worker_id, kind, cron_expr
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_COLS}
                """,
                (
                    task_type,
                    Jsonb(payload or {}),
                    interval_seconds,
                    next_at,
                    enabled,
                    mission_id,
                    worker_id,
                    kind,
                    cron,
                ),
            )
        else:
            row = self.fetch_one(
                f"""
                INSERT INTO scheduler.schedules (
                    task_type, payload, interval_seconds, next_run_at, enabled,
                    mission_id, worker_id, kind, cron_expr
                ) VALUES (%s, %s, %s, now() + make_interval(secs => %s), %s, %s, %s, %s, %s)
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
                    kind,
                    None,
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

        Interval rows advance to ``now() + interval_seconds`` (no catch-up storm).
        Cron rows advance to the next crontab fire after now (OI-A1).
        ``FOR UPDATE SKIP LOCKED`` keeps this safe under multiple scheduler workers.
        """
        out: list[Schedule] = []
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT {_COLS} FROM scheduler.schedules
                    WHERE enabled AND next_run_at <= now()
                    ORDER BY next_run_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall() or []
                now = datetime.now(timezone.utc)
                for row in rows:
                    kind = str(row.get("kind") or KIND_INTERVAL)
                    if kind == KIND_CRON and row.get("cron_expr"):
                        nxt = next_run_after(str(row["cron_expr"]), after=now)
                    else:
                        nxt = now + timedelta(seconds=int(row["interval_seconds"]))
                    cur.execute(
                        f"""
                        UPDATE scheduler.schedules
                        SET last_run_at = now(),
                            next_run_at = %s,
                            updated_at = now()
                        WHERE id = %s
                        RETURNING {_COLS}
                        """,
                        (nxt, row["id"]),
                    )
                    updated = cur.fetchone()
                    if updated:
                        out.append(Schedule.from_row(updated))
        return out

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
                SET interval_seconds = %s, kind = 'interval', cron_expr = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (interval_seconds, str(schedule_id)),
            )
            > 0
        )

    def set_next_run_at(
        self,
        schedule_id: UUID | str,
        next_run_at: datetime,
        *,
        only_if_later: bool = True,
    ) -> bool:
        """Move ``next_run_at`` (operator catch-up / deferral retry).

        When ``only_if_later`` is true (default), never push the run further into the
        future — only pull a distant schedule forward so deferred work is not lost.
        """
        nxt = next_run_at
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if only_if_later:
            return (
                self.execute(
                    """
                    UPDATE scheduler.schedules
                    SET next_run_at = %s, updated_at = now()
                    WHERE id = %s AND next_run_at > %s
                    """,
                    (nxt, str(schedule_id), nxt),
                )
                > 0
            )
        return (
            self.execute(
                """
                UPDATE scheduler.schedules
                SET next_run_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (nxt, str(schedule_id)),
            )
            > 0
        )

    def set_cron(self, schedule_id: UUID | str, cron_expr: str) -> bool:
        expr = validate_cron(cron_expr)
        nxt = next_run_after(expr)
        return (
            self.execute(
                """
                UPDATE scheduler.schedules
                SET kind = 'cron', cron_expr = %s, next_run_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (expr, nxt, str(schedule_id)),
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
