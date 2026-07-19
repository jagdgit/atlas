"""Repository for ``worker.workers`` / ``worker.inputs`` (Phase A · §A.4).

The only SQL layer for worker state (ADR-0027); returns typed models (ADR-0036). Supervision
*logic* (crash backoff, upgrade, tick orchestration) lives in ``WorkerManager``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.worker import Worker, WorkerInput
from atlas.repositories.base import BaseRepository

_WORKER_COLS = (
    "id, mission_id, type, worker_version, status, health, schedule_id, "
    "config_version, restart_count, next_retry_at, last_tick_at, metadata, "
    "created_at, updated_at"
)
_INPUT_COLS = "id, worker_id, payload, status, created_at, consumed_at"


class WorkerRepository(BaseRepository):
    # --- workers --------------------------------------------------------
    def create(
        self,
        *,
        mission_id: str,
        type: str,
        worker_version: int,
        schedule_id: str | None = None,
        config_version: int | None = None,
        status: str = "running",
        health: str = "healthy",
        metadata: dict[str, Any] | None = None,
    ) -> Worker:
        row = self.fetch_one(
            f"""
            INSERT INTO worker.workers (
                mission_id, type, worker_version, schedule_id, config_version,
                status, health, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_WORKER_COLS}
            """,
            (
                mission_id,
                type,
                worker_version,
                schedule_id,
                config_version,
                status,
                health,
                Jsonb(metadata or {}),
            ),
        )
        return Worker.from_row(row)

    def get(self, worker_id: UUID | str) -> Worker | None:
        row = self.fetch_one(
            f"SELECT {_WORKER_COLS} FROM worker.workers WHERE id = %s",
            (str(worker_id),),
        )
        return Worker.from_row(row) if row else None

    def list(
        self,
        *,
        mission_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[Worker]:
        clauses: list[str] = []
        params: list[Any] = []
        if mission_id is not None:
            clauses.append("mission_id = %s")
            params.append(mission_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.fetch_all(
            f"""
            SELECT {_WORKER_COLS} FROM worker.workers
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return Worker.from_rows(rows)

    def set_schedule(self, worker_id: UUID | str, schedule_id: str) -> bool:
        return (
            self.execute(
                "UPDATE worker.workers SET schedule_id = %s, updated_at = now() WHERE id = %s",
                (schedule_id, str(worker_id)),
            )
            > 0
        )

    def set_status(
        self,
        worker_id: UUID | str,
        status: str,
        *,
        health: str | None = None,
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE worker.workers
                SET status = %s,
                    health = COALESCE(%s, health),
                    updated_at = now()
                WHERE id = %s
                """,
                (status, health, str(worker_id)),
            )
            > 0
        )

    def record_success(
        self, worker_id: UUID | str, *, config_version: int | None = None
    ) -> bool:
        """Reset crash state after a good tick: restart_count=0, health=healthy, running."""
        return (
            self.execute(
                """
                UPDATE worker.workers
                SET status = 'running',
                    health = 'healthy',
                    restart_count = 0,
                    next_retry_at = NULL,
                    config_version = COALESCE(%s, config_version),
                    last_tick_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (config_version, str(worker_id)),
            )
            > 0
        )

    def record_failure(
        self,
        worker_id: UUID | str,
        *,
        status: str,
        health: str,
        backoff_seconds: float | None,
    ) -> int:
        """Increment restart_count, set status/health, and (if given) set next_retry_at.

        Returns the new restart_count.
        """
        return self.fetch_val(
            """
            UPDATE worker.workers
            SET restart_count = restart_count + 1,
                status = %s,
                health = %s,
                next_retry_at = CASE
                    WHEN %s IS NULL THEN NULL
                    ELSE now() + make_interval(secs => %s)
                END,
                last_tick_at = now(),
                updated_at = now()
            WHERE id = %s
            RETURNING restart_count
            """,
            (status, health, backoff_seconds, backoff_seconds, str(worker_id)),
        )

    def set_version(self, worker_id: UUID | str, worker_version: int) -> bool:
        return (
            self.execute(
                "UPDATE worker.workers SET worker_version = %s, updated_at = now() WHERE id = %s",
                (worker_version, str(worker_id)),
            )
            > 0
        )

    def count_by_status(self) -> dict[str, int]:
        rows = self.fetch_all(
            "SELECT status, count(*) AS n FROM worker.workers GROUP BY status"
        )
        return {r["status"]: int(r["n"]) for r in rows}

    def stop_active_for_mission(self, mission_id: UUID | str) -> int:
        """Stop every running/recovering worker of a mission (used on mission archive)."""
        return self.execute(
            """
            UPDATE worker.workers
            SET status = 'stopped', updated_at = now()
            WHERE mission_id = %s AND status IN ('running', 'recovering')
            """,
            (str(mission_id),),
        )

    def count_active_for_mission(self, mission_id: UUID | str) -> int:
        """Running/recovering workers for a mission (budget admission, A.6/B1)."""
        return self.fetch_val(
            """
            SELECT count(*) FROM worker.workers
            WHERE mission_id = %s AND status IN ('running', 'recovering')
            """,
            (str(mission_id),),
        )

    # --- inputs ---------------------------------------------------------
    def enqueue_input(
        self, worker_id: UUID | str, payload: dict[str, Any]
    ) -> WorkerInput:
        row = self.fetch_one(
            f"""
            INSERT INTO worker.inputs (worker_id, payload)
            VALUES (%s, %s)
            RETURNING {_INPUT_COLS}
            """,
            (str(worker_id), Jsonb(payload or {})),
        )
        return WorkerInput.from_row(row)

    def drain_inputs(self, worker_id: UUID | str) -> list[WorkerInput]:
        """Atomically claim + mark consumed all pending inputs for a worker (oldest first)."""
        rows = self.fetch_all(
            f"""
            UPDATE worker.inputs
            SET status = 'consumed', consumed_at = now()
            WHERE id IN (
                SELECT id FROM worker.inputs
                WHERE worker_id = %s AND status = 'pending'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
            )
            RETURNING {_INPUT_COLS}
            """,
            (str(worker_id),),
        )
        rows.sort(key=lambda r: r["created_at"])
        return WorkerInput.from_rows(rows)

    def count_pending_inputs(self, worker_id: UUID | str) -> int:
        return self.fetch_val(
            "SELECT count(*) FROM worker.inputs WHERE worker_id = %s AND status = 'pending'",
            (str(worker_id),),
        )
