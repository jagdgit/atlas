"""Job Engine service — decompose, advance, block, resume, recover (S12).

Design (D1/R1/R3/R4/Q1/Q10):
- **One step per scheduler task.** `create_job` enqueues an ``advance_job`` task;
  the handler runs *one* runnable step, then **re-enqueues itself**. Short tasks let
  many jobs interleave on the worker pool (R1, CPU-parallel) while steps within a job
  stay sequential (Q1). LLM calls still serialise through the single LLM lane (R4).
- **Blocking is non-fatal (R3).** A step that needs the user (missing capability,
  missing file, login) is marked ``blocked``; the loop simply advances past it to the
  next runnable step. Dependents of a blocked step cascade to ``blocked``; dependents
  of a failed step cascade to ``skipped``. The job finishes
  ``completed_with_blocks`` and is **resumable**.
- **Reuse, not reimplementation (D1).** Steps run through ``AssistantService.run_step``
  — the exact dispatch a chat turn uses.
- **Reboot recovery (Q10).** On start, steps left ``running`` reset to ``pending`` and
  unfinished jobs are re-enqueued.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from atlas.conversation.service import ConversationContext
from atlas.models.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_COMPLETED_WITH_BLOCKS,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_TERMINAL,
    STEP_BLOCKED,
    STEP_DONE,
    STEP_FAILED,
    STEP_PENDING,
    STEP_RUNNING,
    STEP_SKIPPED,
    Job,
    JobStep,
)
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.jobs.planner import JobPlanner
    from atlas.repositories.job_repo import JobRepository
    from atlas.services.assistant_service import AssistantService

ADVANCE_TASK = "advance_job"


class JobService:
    name = "jobs"

    def __init__(
        self,
        repo: "JobRepository",
        planner: "JobPlanner",
        runner: "AssistantService",
        *,
        enqueue: Callable[..., Any] | None = None,
        conversation: Any = None,
        step_max_retries: int = 2,
        retry_delay: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._planner = planner
        self._runner = runner
        self._enqueue = enqueue
        self._conversation = conversation
        self._step_max_retries = step_max_retries
        self._retry_delay = retry_delay
        self._logger = logger or logging.getLogger("atlas.jobs")

    # --- public API -----------------------------------------------------
    def create_job(
        self, objective: str, *, session_id: str | None = None
    ) -> dict[str, Any]:
        """Create a job, decompose it into steps, and enqueue it to run."""
        job = self._repo.create_job(objective, session_id=session_id)
        steps = self._planner.decompose(objective)
        for ordinal, step in enumerate(steps):
            self._repo.add_step(
                job.id,
                ordinal,
                step.intent,
                step.capability,
                args=step.args,
                description=step.description,
                depends_on=step.depends_on,
            )
        self._logger.info(
            "created job %s (%d step(s)): %s", job.id, len(steps), objective[:80]
        )
        self._enqueue_advance(job.id)
        return self.job_detail(job.id)

    def job_detail(self, job_id: str) -> dict[str, Any]:
        job = self._repo.get_job(job_id)
        if job is None:
            raise KeyError(f"no job {job_id}")
        steps = self._repo.list_steps(job_id)
        return {
            "job": job,
            "steps": steps,
            "progress": self._progress(steps),
            "blocked": [self._blocked_view(s) for s in steps if s.status == STEP_BLOCKED],
        }

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[Job]:
        return self._repo.list_jobs(status=status, limit=limit)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        """Reset blocked/skipped steps to pending and re-run them (R3)."""
        job = self._repo.get_job(job_id)
        if job is None:
            raise KeyError(f"no job {job_id}")
        reset = self._repo.reset_blocked_steps(job_id)
        self._repo.set_job_status(job_id, JOB_QUEUED)
        self._logger.info("resuming job %s (%d step(s) reset)", job_id, reset)
        self._enqueue_advance(job_id)
        return self.job_detail(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self._repo.get_job(job_id)
        if job is None:
            raise KeyError(f"no job {job_id}")
        if job.status not in JOB_TERMINAL:
            self._repo.set_job_status(job_id, JOB_CANCELLED)
            self._logger.info("cancelled job %s", job_id)
        return self.job_detail(job_id)

    # --- scheduler handler ---------------------------------------------
    def advance_job_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one runnable step of a job, then re-enqueue or finalize.

        Registered as the ``advance_job`` scheduler handler; idempotent and
        crash-safe (re-derives the next step from persisted state each call).
        """
        job_id = payload.get("job_id")
        job = self._repo.get_job(job_id) if job_id else None
        if job is None:
            return {"status": "unknown_job", "job_id": job_id}
        if job.status in JOB_TERMINAL:
            return {"status": job.status, "job_id": job_id}

        if job.status != JOB_RUNNING:
            self._repo.set_job_status(job_id, JOB_RUNNING)

        steps = self._repo.list_steps(job_id)
        step = self._next_runnable(job_id, steps)
        if step is None:
            final = self._finalize(job_id, self._repo.list_steps(job_id))
            return {"status": final, "job_id": job_id}

        self._run_one(job, step)
        # Re-enqueue to process the next step (or finalize on the next pass).
        self._enqueue_advance(job_id)
        return {"status": "advanced", "job_id": job_id, "step": step.ordinal}

    # --- internals ------------------------------------------------------
    def _next_runnable(self, job_id: str, steps: list[JobStep]) -> JobStep | None:
        by_ordinal = {s.ordinal: s for s in steps}
        for step in steps:
            if step.status != STEP_PENDING:
                continue
            if step.depends_on is None:
                self._claim(step)
                return step
            dep = by_ordinal.get(step.depends_on)
            if dep is None or dep.status == STEP_DONE:
                self._claim(step)
                return step
            if dep.status == STEP_BLOCKED:
                self._repo.set_step_status(
                    step.id,
                    STEP_BLOCKED,
                    blocked_reason=f"depends on blocked step {dep.ordinal}",
                )
            elif dep.status in {STEP_FAILED, STEP_SKIPPED}:
                self._repo.set_step_status(
                    step.id,
                    STEP_SKIPPED,
                    error=f"skipped: prerequisite step {dep.ordinal} did not complete",
                )
            # dep still pending/running (shouldn't happen: deps precede) → leave.
        return None

    def _claim(self, step: JobStep) -> None:
        self._repo.set_step_status(step.id, STEP_RUNNING)

    def _run_one(self, job: Job, step: JobStep) -> None:
        context = self._build_context(job)
        tool_calls: list[dict[str, Any]] = []
        try:
            outcome = self._runner.run_step(
                step.intent,
                dict(step.args),
                context=context,
                tool_calls=tool_calls,
                capability=step.capability,
            )
        except Exception as exc:  # noqa: BLE001 - a bad step must not kill the job
            self._on_step_error(step, f"{type(exc).__name__}: {exc}")
            return

        if outcome.blocked:
            self._repo.set_step_status(
                step.id,
                STEP_BLOCKED,
                result={"answer": outcome.answer, "tool_calls": tool_calls},
                blocked_reason=outcome.blocked_reason or "needs the user",
                bump_attempts=True,
            )
            self._logger.info("job %s step %s blocked: %s", job.id, step.ordinal, outcome.blocked_reason)
            return

        self._repo.set_step_status(
            step.id,
            STEP_DONE,
            result={
                "answer": outcome.answer,
                "citations": outcome.citations,
                "run_id": outcome.run_id,
                "tool_calls": tool_calls,
            },
            bump_attempts=True,
        )

    def _on_step_error(self, step: JobStep, error: str) -> None:
        # Simple step-level retry mirroring the scheduler's backoff intent.
        if step.attempts + 1 < self._step_max_retries:
            self._repo.set_step_status(
                step.id, STEP_PENDING, error=error, bump_attempts=True
            )
            self._logger.warning("job step %s errored (%s); will retry", step.id, error)
        else:
            self._repo.set_step_status(
                step.id, STEP_FAILED, error=error, bump_attempts=True
            )
            self._logger.error("job step %s failed permanently: %s", step.id, error)

    def _finalize(self, job_id: str, steps: list[JobStep]) -> str:
        statuses = [s.status for s in steps]
        has_blocked = STEP_BLOCKED in statuses
        has_failed = STEP_FAILED in statuses
        if has_blocked:
            status = JOB_COMPLETED_WITH_BLOCKS
        elif has_failed:
            status = JOB_FAILED
        else:
            status = JOB_COMPLETED
        result = {
            "summary": self._summary(steps),
            "answer": self._answer(steps),
            "progress": self._progress(steps),
        }
        self._repo.set_job_status(job_id, status, result=result)
        self._logger.info("job %s finalized: %s", job_id, status)
        return status

    # --- views / helpers -----------------------------------------------
    @staticmethod
    def _progress(steps: list[JobStep]) -> dict[str, int]:
        counts = {
            "total": len(steps),
            "done": 0,
            "blocked": 0,
            "failed": 0,
            "skipped": 0,
            "pending": 0,
            "running": 0,
        }
        for s in steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        return counts

    @staticmethod
    def _blocked_view(step: JobStep) -> dict[str, Any]:
        return {
            "ordinal": step.ordinal,
            "intent": step.intent,
            "capability": step.capability,
            "needs": step.blocked_reason,
            "description": step.description,
        }

    @staticmethod
    def _summary(steps: list[JobStep]) -> str:
        done = sum(1 for s in steps if s.status == STEP_DONE)
        blocked = [s for s in steps if s.status == STEP_BLOCKED]
        parts = [f"{done}/{len(steps)} step(s) completed"]
        if blocked:
            needs = "; ".join(f"step {s.ordinal}: {s.blocked_reason}" for s in blocked)
            parts.append(f"blocked — needs you: {needs}")
        return ". ".join(parts) + "."

    @staticmethod
    def _answer(steps: list[JobStep]) -> str:
        answers = [
            (s.result or {}).get("answer", "")
            for s in steps
            if s.status == STEP_DONE and (s.result or {}).get("answer")
        ]
        return "\n\n".join(a for a in answers if a)

    def _build_context(self, job: Job) -> ConversationContext:
        if job.session_id and self._conversation is not None:
            try:
                return self._conversation.build_context(job.session_id, job.objective)
            except Exception:  # noqa: BLE001 - context is best-effort
                self._logger.exception("failed to build job context")
        return ConversationContext(session_id=job.session_id or f"job:{job.id}")

    def _enqueue_advance(self, job_id: str) -> None:
        if self._enqueue is None:
            return
        self._enqueue(ADVANCE_TASK, {"job_id": str(job_id)})

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        try:
            recovered = self._repo.recover_interrupted_steps()
            unfinished = self._repo.list_unfinished_jobs()
        except Exception:  # noqa: BLE001 - never block boot on recovery
            self._logger.exception("job recovery failed")
            return
        if recovered:
            self._logger.info("recovered %d interrupted job step(s)", recovered)
        for job in unfinished:
            self._enqueue_advance(job.id)
        if unfinished:
            self._logger.info("re-enqueued %d unfinished job(s)", len(unfinished))

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            total = self._repo.count_jobs()
            running = self._repo.count_jobs(status=JOB_RUNNING)
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"job store unreachable: {exc}")
        return HealthStatus.ok(f"{total} job(s), {running} running", jobs=total, running=running)
