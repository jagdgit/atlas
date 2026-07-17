"""Repository for ``job.jobs`` / ``job.steps`` (ADR-0027, S12).

The only SQL layer for job state. Returns typed models (ADR-0036). Scheduling
*logic* (the advance loop, blocking, resume) lives in ``JobService``; this layer
persists state transitions atomically.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.job import (
    JOB_TERMINAL,
    STEP_BLOCKED,
    STEP_PENDING,
    STEP_RUNNING,
    STEP_SKIPPED,
    Job,
    JobStep,
)
from atlas.repositories.base import BaseRepository

_JOB_COLS = (
    "id, session_id, objective, status, result, error, metadata, "
    "created_at, updated_at, started_at, completed_at"
)
_STEP_COLS = (
    "id, job_id, ordinal, intent, capability, args, description, depends_on, "
    "status, result, error, blocked_reason, attempts, created_at, updated_at, "
    "started_at, completed_at"
)


class JobRepository(BaseRepository):
    # --- jobs -----------------------------------------------------------
    def create_job(
        self,
        objective: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        row = self.fetch_one(
            f"""
            INSERT INTO job.jobs (objective, session_id, metadata)
            VALUES (%s, %s, %s)
            RETURNING {_JOB_COLS}
            """,
            (objective, session_id, Jsonb(metadata or {})),
        )
        return Job.from_row(row)

    def get_job(self, job_id: UUID | str) -> Job | None:
        row = self.fetch_one(
            f"SELECT {_JOB_COLS} FROM job.jobs WHERE id = %s", (str(job_id),)
        )
        return Job.from_row(row) if row else None

    def list_jobs(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        if status:
            rows = self.fetch_all(
                f"""
                SELECT {_JOB_COLS} FROM job.jobs
                WHERE status = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (status, limit),
            )
        else:
            rows = self.fetch_all(
                f"SELECT {_JOB_COLS} FROM job.jobs ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return Job.from_rows(rows)

    def set_job_status(
        self,
        job_id: UUID | str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        started = status == STEP_RUNNING  # 'running' marks start for jobs too
        completed = status in JOB_TERMINAL
        return (
            self.execute(
                """
                UPDATE job.jobs
                SET status = %s,
                    result = COALESCE(%s, result),
                    error = COALESCE(%s, error),
                    started_at = CASE WHEN %s AND started_at IS NULL
                                      THEN now() ELSE started_at END,
                    completed_at = CASE WHEN %s THEN now() ELSE completed_at END,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    status,
                    Jsonb(result) if result is not None else None,
                    error,
                    started,
                    completed,
                    str(job_id),
                ),
            )
            > 0
        )

    def merge_job_metadata(
        self, job_id: UUID | str, patch: dict[str, Any]
    ) -> bool:
        """Shallow-merge keys into ``job.jobs.metadata`` (3.2e planning phase)."""
        if not patch:
            return False
        return (
            self.execute(
                """
                UPDATE job.jobs
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(patch), str(job_id)),
            )
            > 0
        )

    def count_jobs(self, *, status: str | None = None) -> int:
        if status:
            return (
                self.fetch_val(
                    "SELECT count(*) FROM job.jobs WHERE status = %s", (status,)
                )
                or 0
            )
        return self.fetch_val("SELECT count(*) FROM job.jobs") or 0

    # --- steps ----------------------------------------------------------
    def add_step(
        self,
        job_id: UUID | str,
        ordinal: int,
        intent: str,
        capability: str,
        *,
        args: dict[str, Any] | None = None,
        description: str = "",
        depends_on: int | None = None,
    ) -> JobStep:
        row = self.fetch_one(
            f"""
            INSERT INTO job.steps
                (job_id, ordinal, intent, capability, args, description, depends_on)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {_STEP_COLS}
            """,
            (
                str(job_id),
                ordinal,
                intent,
                capability,
                Jsonb(args or {}),
                description,
                depends_on,
            ),
        )
        return JobStep.from_row(row)

    def list_steps(self, job_id: UUID | str) -> list[JobStep]:
        rows = self.fetch_all(
            f"""
            SELECT {_STEP_COLS} FROM job.steps
            WHERE job_id = %s ORDER BY ordinal ASC
            """,
            (str(job_id),),
        )
        return JobStep.from_rows(rows)

    def set_step_status(
        self,
        step_id: UUID | str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        blocked_reason: str | None = None,
        bump_attempts: bool = False,
    ) -> bool:
        started = status == STEP_RUNNING
        completed = status in {"done", "failed", "skipped"}
        return (
            self.execute(
                """
                UPDATE job.steps
                SET status = %s,
                    result = COALESCE(%s, result),
                    error = %s,
                    blocked_reason = %s,
                    attempts = attempts + CASE WHEN %s THEN 1 ELSE 0 END,
                    started_at = CASE WHEN %s AND started_at IS NULL
                                      THEN now() ELSE started_at END,
                    completed_at = CASE WHEN %s THEN now() ELSE completed_at END,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    status,
                    Jsonb(result) if result is not None else None,
                    error,
                    blocked_reason,
                    bump_attempts,
                    started,
                    completed,
                    str(step_id),
                ),
            )
            > 0
        )

    def reset_blocked_steps(self, job_id: UUID | str) -> int:
        """Reset blocked (and steps skipped by a blocked dependency) to pending.

        Used by resume (R3): the user provided the file/credential or built the
        capability, so the previously-blocked work can run again.
        """
        return self.execute(
            """
            UPDATE job.steps
            SET status = %s, blocked_reason = NULL, error = NULL, updated_at = now()
            WHERE job_id = %s AND status IN (%s, %s)
            """,
            (STEP_PENDING, str(job_id), STEP_BLOCKED, STEP_SKIPPED),
        )

    def recover_interrupted_steps(self) -> int:
        """Reset steps left `running` (crash) back to `pending` (Q10)."""
        return self.execute(
            """
            UPDATE job.steps SET status = %s, updated_at = now()
            WHERE status = %s
            """,
            (STEP_PENDING, STEP_RUNNING),
        )

    def list_unfinished_jobs(self) -> list[Job]:
        """Jobs still queued/running — re-hydrated on startup (Q10)."""
        rows = self.fetch_all(
            f"""
            SELECT {_JOB_COLS} FROM job.jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at ASC
            """
        )
        return Job.from_rows(rows)
