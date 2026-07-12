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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.conversation.service import ConversationContext
from atlas.jobs.activity import (
    PHASE_LIFECYCLE,
    PHASE_STEP,
    ActivityRecorder,
)
from atlas.jobs.workspace import JobWorkspace
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
        reports: Any = None,
        events: Any = None,
        learning: Any = None,
        workspace_root: str | Path | None = None,
        step_max_retries: int = 2,
        retry_delay: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._planner = planner
        self._runner = runner
        self._enqueue = enqueue
        self._conversation = conversation
        self._reports = reports
        self._events = events
        self._learning = learning
        # Per-job on-disk workspace root (§5a, C3). When set (``<data>``), each job
        # gets ``<data>/jobs/job_<id>/`` with a manifest, notes, and final report —
        # so work is durable and inspectable ("open the workspace"). Best-effort:
        # workspace I/O never fails a job. Left unset in lightweight tests.
        self._workspace_root = Path(workspace_root) if workspace_root else None
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
        ws = self._workspace(job.id)
        if ws is not None:
            try:
                ws.init_manifest(objective=objective)
                ws.append_note(f"job created ({len(steps)} step(s)): {objective[:120]}")
            except Exception:  # noqa: BLE001 - workspace I/O must never fail a job
                self._logger.debug("job %s workspace init failed", job.id)
        self._recorder(job.id).record(
            PHASE_LIFECYCLE,
            f"Job created — planned {len(steps)} step(s).",
            steps=len(steps),
            objective=objective[:200],
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
            "activity": self._activity_tail(job_id),
        }

    def _activity_tail(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Recent progress events for the live feed (RL/C0). Empty without a workspace."""
        ws = self._workspace(job_id)
        if ws is None:
            return []
        try:
            return ws.read_activity(limit=limit)
        except Exception:  # noqa: BLE001 - feed is best-effort
            return []

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[Job]:
        return self._repo.list_jobs(status=status, limit=limit)

    def list_blocked(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Aggregate blocked steps across jobs — the HITL queue (R3, Q2).

        These are the sub-tasks waiting on the user (a file, a credential, a login,
        or a capability to be enabled). Each never stalled its job — the job ran
        everything else it could — and each is resumable via ``resume_job``.
        """
        out: list[dict[str, Any]] = []
        for job in self._repo.list_jobs(status=JOB_COMPLETED_WITH_BLOCKS, limit=limit):
            for step in self._repo.list_steps(job.id):
                if step.status == STEP_BLOCKED:
                    view = self._blocked_view(step)
                    view["job_id"] = job.id
                    view["objective"] = job.objective
                    out.append(view)
        return out

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
        recorder = self._recorder(job.id)
        recorder.record(
            PHASE_STEP,
            f"Step {step.ordinal + 1}: {step.description or step.intent}",
            ordinal=step.ordinal,
            intent=step.intent,
            capability=step.capability,
            state="running",
        )
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
            recorder.record(
                PHASE_STEP,
                f"Step {step.ordinal + 1} errored: {type(exc).__name__}",
                ordinal=step.ordinal,
                state="error",
            )
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
            recorder.record(
                PHASE_STEP,
                f"Step {step.ordinal + 1} blocked — needs you: "
                f"{outcome.blocked_reason or 'input required'}",
                ordinal=step.ordinal,
                state="blocked",
                needs=outcome.blocked_reason,
            )
            self._notify(
                "job.step_blocked",
                {
                    "job_id": str(job.id),
                    "ordinal": step.ordinal,
                    "capability": step.capability,
                    "needs": outcome.blocked_reason,
                },
            )
            return

        recorder.record(
            PHASE_STEP,
            f"Step {step.ordinal + 1} completed.",
            ordinal=step.ordinal,
            state="done",
            tools=[tc.get("action") or tc.get("intent") for tc in tool_calls],
        )
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
        report = self._build_report(job_id, steps)
        if report is not None:
            result["report"] = report.get("markdown", "")
            result["report_sections"] = report.get("sections", {})
            result["overall_confidence"] = report.get("overall_confidence")
        self._persist_workspace(job_id, status, result)
        self._repo.set_job_status(job_id, status, result=result)
        self._logger.info("job %s finalized: %s", job_id, status)
        self._recorder(job_id).record(
            PHASE_LIFECYCLE,
            f"Job {status.replace('_', ' ')} — {result['progress'].get('done', 0)}"
            f"/{result['progress'].get('total', 0)} step(s) done.",
            status=status,
            progress=result["progress"],
        )
        self._observe_learning(job_id, steps, result)
        self._notify(
            "job.finalized",
            {
                "job_id": str(job_id),
                "status": status,
                "progress": result["progress"],
            },
        )
        return status

    def _observe_learning(
        self, job_id: str, steps: list[JobStep], result: dict[str, Any]
    ) -> None:
        """Propose an Experience from the finished job (S18b, §5d). Governed and
        best-effort: never auto-verifies and never fails the job."""
        if self._learning is None:
            return
        try:
            job = self._repo.get_job(job_id)
            self._learning.observe_job({"job": job, "steps": steps, "result": result})
        except Exception:  # noqa: BLE001 - learning must never break finalization
            self._logger.debug("job %s learning observation failed", job_id)

    def _build_report(self, job_id: str, steps: list[JobStep]) -> dict[str, Any] | None:
        """Attach a scientific-review report (§5a.5) to the finished job (S17)."""
        if self._reports is None:
            return None
        job = self._repo.get_job(job_id)
        objective = job.objective if job else ""
        answer = self._answer(steps)
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in steps:
            for cit in (step.result or {}).get("citations", []) or []:
                did = str(cit.get("document_id") or cit.get("chunk_id") or "")
                if did and did not in seen:
                    seen.add(did)
                    sources.append(
                        {
                            "id": did,
                            "title": (cit.get("snippet") or "")[:80] or did,
                            "evidence_level": 3,
                        }
                    )
        try:
            return self._reports.render(
                objective, claims=[], sources=sources, answer=answer, notes=answer[:600]
            )
        except Exception:  # noqa: BLE001 - a report must never fail the job
            self._logger.exception("job %s report generation failed", job_id)
            return None

    def _workspace(self, job_id: str) -> JobWorkspace | None:
        if self._workspace_root is None:
            return None
        return JobWorkspace.for_job(self._workspace_root, str(job_id))

    def _recorder(self, job_id: str) -> ActivityRecorder:
        """An activity recorder for a job (RL/C0): writes to the workspace feed and
        emits ``job.activity`` on the event bus. Safe even without a workspace."""
        return ActivityRecorder(
            str(job_id),
            workspace=self._workspace(job_id),
            events=self._events,
            logger=self._logger,
        )

    def _persist_workspace(
        self, job_id: str, status: str, result: dict[str, Any]
    ) -> None:
        """Write the final report + result summary into the job workspace (§5a)."""
        ws = self._workspace(job_id)
        if ws is None:
            return
        try:
            if result.get("report"):
                ws.write_text(ws.report_path.name, result["report"])
            ws.write_json(
                "result.json",
                {
                    "status": status,
                    "summary": result.get("summary", ""),
                    "progress": result.get("progress", {}),
                    "overall_confidence": result.get("overall_confidence"),
                },
            )
            ws.append_note(f"finalized: {status}")
            result["workspace"] = str(ws.root)
        except Exception:  # noqa: BLE001 - workspace I/O must never fail a job
            self._logger.debug("job %s workspace persist failed", job_id)

    def _notify(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source="jobs")
        except Exception:  # noqa: BLE001 - notifications are best-effort
            self._logger.debug("notify %s failed", event_type)

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
