"""Repository for ``scheduler.tasks`` and ``scheduler.task_runs``.

State transitions only — the scheduling *logic* (workers, retries, backoff)
lives in the scheduler service (Sprint 2). This layer just persists state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

VALID_STATUSES = {
    "pending",
    "claimed",
    "running",
    "completed",
    "failed",
    "cancelled",
}


class TaskRepository(BaseRepository):
    def create(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
        max_retries: int = 3,
        delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Create a pending task and return the row.

        ``delay_seconds`` postpones eligibility via ``scheduled_at`` (used for
        periodic tasks that re-enqueue themselves, e.g. the ingestion scan).
        """
        return self.fetch_one(
            """
            INSERT INTO scheduler.tasks
                (task_type, payload, priority, max_retries, scheduled_at)
            VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s))
            RETURNING *
            """,
            (task_type, Jsonb(payload or {}), priority, max_retries, delay_seconds),
        )

    def count_pending_of_type(self, task_type: str) -> int:
        """Count not-yet-finished tasks of a type (pending/claimed/running)."""
        return self.fetch_val(
            """
            SELECT count(*) FROM scheduler.tasks
            WHERE task_type = %s AND status IN ('pending', 'claimed', 'running')
            """,
            (task_type,),
        )

    def get(self, task_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM scheduler.tasks WHERE id = %s", (str(task_id),)
        )

    def list_by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return self.fetch_all(
            """
            SELECT * FROM scheduler.tasks
            WHERE status = %s
            ORDER BY priority DESC, scheduled_at ASC
            LIMIT %s
            """,
            (status, limit),
        )

    def set_status(
        self,
        task_id: UUID | str,
        status: str,
        *,
        error: str | None = None,
    ) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return (
            self.execute(
                """
                UPDATE scheduler.tasks
                SET status = %s,
                    last_error = COALESCE(%s, last_error),
                    claimed_at = CASE WHEN %s = 'claimed' THEN now() ELSE claimed_at END,
                    completed_at = CASE WHEN %s IN ('completed','failed','cancelled')
                                        THEN now() ELSE completed_at END,
                    updated_at = now()
                WHERE id = %s
                """,
                (status, error, status, status, str(task_id)),
            )
            > 0
        )

    def claim_next(self, worker_id: str) -> dict[str, Any] | None:
        """Atomically claim the next runnable pending task.

        Uses FOR UPDATE SKIP LOCKED so multiple workers never grab the same task.
        Only tasks whose scheduled_at has arrived are eligible (supports backoff).
        """
        return self.fetch_one(
            """
            UPDATE scheduler.tasks
            SET status = 'running', claimed_at = now(), updated_at = now()
            WHERE id = (
                SELECT id FROM scheduler.tasks
                WHERE status = 'pending' AND scheduled_at <= now()
                ORDER BY priority DESC, scheduled_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """,
            (),
        )

    def recover_interrupted(self) -> int:
        """Reset tasks left in claimed/running (crash) back to pending.

        Returns the number of tasks recovered.
        """
        return self.execute(
            """
            UPDATE scheduler.tasks
            SET status = 'pending', claimed_at = NULL, updated_at = now()
            WHERE status IN ('claimed', 'running')
            """
        )

    def mark_completed(self, task_id: UUID | str) -> bool:
        return (
            self.execute(
                """
                UPDATE scheduler.tasks
                SET status = 'completed', completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (str(task_id),),
            )
            > 0
        )

    def reschedule_for_retry(
        self, task_id: UUID | str, delay_seconds: float, error: str | None = None
    ) -> int:
        """Increment retry_count and re-queue with a future scheduled_at.

        Returns the new retry_count.
        """
        return self.fetch_val(
            """
            UPDATE scheduler.tasks
            SET status = 'pending',
                retry_count = retry_count + 1,
                scheduled_at = now() + make_interval(secs => %s),
                last_error = %s,
                claimed_at = NULL,
                updated_at = now()
            WHERE id = %s
            RETURNING retry_count
            """,
            (delay_seconds, error, str(task_id)),
        )

    def mark_failed_permanent(
        self, task_id: UUID | str, error: str | None = None
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE scheduler.tasks
                SET status = 'failed', completed_at = now(),
                    last_error = COALESCE(%s, last_error), updated_at = now()
                WHERE id = %s
                """,
                (error, str(task_id)),
            )
            > 0
        )

    # --- task_runs ------------------------------------------------------
    def start_run(self, task_id: UUID | str, worker_id: str) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO scheduler.task_runs (task_id, status, worker_id)
            VALUES (%s, 'running', %s)
            RETURNING *
            """,
            (str(task_id), worker_id),
        )

    def finish_run(
        self,
        run_id: UUID | str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE scheduler.task_runs
                SET status = %s, finished_at = now(), result = %s, error = %s
                WHERE id = %s
                """,
                (
                    status,
                    Jsonb(result) if result is not None else None,
                    error,
                    str(run_id),
                ),
            )
            > 0
        )

    def increment_retry(self, task_id: UUID | str) -> int:
        """Bump retry_count and return the new value."""
        return self.fetch_val(
            """
            UPDATE scheduler.tasks
            SET retry_count = retry_count + 1, updated_at = now()
            WHERE id = %s
            RETURNING retry_count
            """,
            (str(task_id),),
        )

    def delete(self, task_id: UUID | str) -> bool:
        return self.execute(
            "DELETE FROM scheduler.tasks WHERE id = %s", (str(task_id),)
        ) > 0
