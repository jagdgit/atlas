"""Job Engine service — decompose, advance, block, resume, recover (S12).

Design (D1/R1/R3/R4/Q1/Q10 + 3.2e):
- **Async planning (3.2e).** ``create_job`` inserts the job, records planning
  activity, and enqueues ``plan_job``. LLM decompose runs in the background with a
  bounded timeout; the HTTP create path never waits on Ollama. Deterministic
  fallback remains on timeout/error (D32.18).
- **One step per scheduler task.** After planning, ``plan_job`` enqueues
  ``advance_job``; the handler runs *one* runnable step, then **re-enqueues itself**.
  Short tasks let many jobs interleave on the worker pool (R1, CPU-parallel) while
  steps within a job stay sequential (Q1). LLM calls still serialise through the
  single LLM lane (R4).
- **Blocking is non-fatal (R3).** A step that needs the user (missing capability,
  missing file, login) is marked ``blocked``; the loop simply advances past it to the
  next runnable step. Dependents of a blocked step cascade to ``blocked``; dependents
  of a failed step cascade to ``skipped``. The job finishes
  ``completed_with_blocks`` and is **resumable**.
- **Reuse, not reimplementation (D1).** Steps run through ``AssistantService.run_step``
  — the exact dispatch a chat turn uses.
- **Reboot recovery (Q10).** On start, steps left ``running`` reset to ``pending``;
  jobs still planning (no steps) re-enqueue ``plan_job``; jobs with steps re-enqueue
  ``advance_job``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.conversation.service import ConversationContext
from atlas.jobs.activity import (
    PHASE_LIFECYCLE,
    PHASE_PLANNING,
    PHASE_STEP,
    ActivityRecorder,
)
from atlas.jobs.workspace import JobWorkspace
from atlas.models.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_COMPLETED_WITH_BLOCKS,
    JOB_FAILED,
    JOB_PHASE_KEY,
    JOB_PLANNING_PHASES,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_TERMINAL,
    PHASE_PLANNING as JOB_PHASE_PLANNING,
    PHASE_PLANNING_QUEUED,
    PHASE_READY,
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
PLAN_TASK = "plan_job"


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
        knowledge: Any = None,
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
        # Stage 3 C6: knowledge sink for domain-tagged promotion of read docs + claims.
        self._knowledge = knowledge
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
        """Create a job and schedule async planning (3.2e).

        Returns immediately after the job row exists and ``plan_job`` is enqueued.
        LLM JobPlanner decompose runs in the background; steps appear when planning
        finishes (or falls back to the deterministic plan).
        """
        job = self._repo.create_job(
            objective,
            session_id=session_id,
            metadata={JOB_PHASE_KEY: PHASE_PLANNING_QUEUED},
        )
        self._logger.info("created job %s (planning queued): %s", job.id, objective[:80])
        ws = self._workspace(job.id)
        if ws is not None:
            try:
                ws.init_manifest(objective=objective)
                ws.append_note(f"job created — planning queued: {objective[:120]}")
            except Exception:  # noqa: BLE001 - workspace I/O must never fail a job
                self._logger.debug("job %s workspace init failed", job.id)
        self._recorder(job.id).record(
            PHASE_LIFECYCLE,
            "Job submitted — planning queued.",
            objective=objective[:200],
            job_phase=PHASE_PLANNING_QUEUED,
        )
        self._recorder(job.id).record(
            PHASE_PLANNING,
            "Waiting for planner capacity.",
            job_phase=PHASE_PLANNING_QUEUED,
        )
        self._enqueue_plan(job.id)
        return self.job_detail(job.id)

    def plan_job_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run JobPlanner decompose, persist steps, then enqueue advance (3.2e)."""
        job_id = payload.get("job_id")
        job = self._repo.get_job(job_id) if job_id else None
        if job is None:
            return {"status": "unknown_job", "job_id": job_id}
        if job.status in JOB_TERMINAL:
            return {"status": job.status, "job_id": job_id}

        existing = self._repo.list_steps(job.id)
        if existing:
            # Already planned (duplicate plan task / recovery race) — just advance.
            self._set_phase(job.id, PHASE_READY)
            self._enqueue_advance(job.id)
            return {
                "status": "already_planned",
                "job_id": job.id,
                "steps": len(existing),
            }

        self._set_phase(job.id, JOB_PHASE_PLANNING)
        self._recorder(job.id).record(
            PHASE_PLANNING,
            "Planner started — decomposing objective.",
            job_phase=JOB_PHASE_PLANNING,
        )

        steps = self._planner.decompose(job.objective)
        source = getattr(self._planner, "last_source", "deterministic")
        fallback = source == "fallback"

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

        if fallback:
            self._recorder(job.id).record(
                PHASE_PLANNING,
                "Planner timed out or failed — using deterministic plan.",
                steps=len(steps),
                fallback=True,
                source=source,
            )
        else:
            self._recorder(job.id).record(
                PHASE_PLANNING,
                f"Plan ready — {len(steps)} step(s).",
                steps=len(steps),
                fallback=False,
                source=source,
            )

        self._set_phase(job.id, PHASE_READY)
        self._recorder(job.id).record(
            PHASE_LIFECYCLE,
            f"Planning complete — {len(steps)} step(s); starting work.",
            steps=len(steps),
            job_phase=PHASE_READY,
        )
        ws = self._workspace(job.id)
        if ws is not None:
            try:
                ws.append_note(f"planned {len(steps)} step(s)")
            except Exception:  # noqa: BLE001
                pass

        self._logger.info(
            "planned job %s (%d step(s)%s)",
            job.id,
            len(steps),
            ", fallback" if fallback else "",
        )
        self._enqueue_advance(job.id)
        return {
            "status": "planned",
            "job_id": job.id,
            "steps": len(steps),
            "fallback": fallback,
        }

    def job_detail(self, job_id: str) -> dict[str, Any]:
        job = self._repo.get_job(job_id)
        if job is None:
            raise KeyError(f"no job {job_id}")
        steps = self._repo.list_steps(job_id)
        # Prefer finalized usage; otherwise approximate from the live workspace.
        usage = None
        if isinstance(getattr(job, "result", None), dict) and job.result.get("usage"):
            usage = job.result["usage"]
        else:
            usage = self._usage_for_job(job_id, steps) or None
        return {
            "job": job,
            "steps": steps,
            "progress": self._progress(steps),
            "blocked": [self._blocked_view(s) for s in steps if s.status == STEP_BLOCKED],
            "activity": self._activity_tail(job_id),
            "usage": usage,
            "phase": self._phase_of(job),
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
            blocked_result: dict[str, Any] = {
                "answer": outcome.answer,
                "tool_calls": tool_calls,
            }
            if getattr(outcome, "extras", None):
                blocked_result.update(outcome.extras)
            self._repo.set_step_status(
                step.id,
                STEP_BLOCKED,
                result=blocked_result,
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
        done_result: dict[str, Any] = {
            "answer": outcome.answer,
            "citations": outcome.citations,
            "run_id": outcome.run_id,
            "tool_calls": tool_calls,
        }
        if getattr(outcome, "extras", None):
            done_result.update(outcome.extras)
        self._repo.set_step_status(
            step.id,
            STEP_DONE,
            result=done_result,
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
        # Prefer research-pipeline confidence from workspace evidence when present
        # (C4/C6) — the scientific report written during the research step.
        self._enrich_from_research(job_id, result)
        usage = self._usage_for_job(job_id, steps)
        if usage:
            result["usage"] = usage
            # Append a short data-usage footer to the report markdown.
            footer = "\n\n## Data usage\n" + usage.get("human", "") + "\n"
            if result.get("report"):
                result["report"] = (result["report"] or "").rstrip() + footer
            if isinstance(result.get("answer"), str) and result["answer"]:
                result["answer"] = result["answer"].rstrip() + "\n\nData usage: " + usage.get(
                    "human", ""
                )
        self._enrich_learning_signals(steps, result)
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

    def _enrich_learning_signals(
        self, steps: list[JobStep], result: dict[str, Any]
    ) -> None:
        """Attach research pipeline extras so Experience observation is rich (3B.5)."""
        for key in ("pipeline", "blocked", "recommendations", "readers"):
            if result.get(key):
                continue
            for step in steps:
                step_result = step.result or {}
                if not isinstance(step_result, dict):
                    continue
                val = step_result.get(key)
                if val:
                    result[key] = val
                    break
        # Collect reader_ids from nested documents if still empty.
        if not result.get("readers"):
            readers: list[str] = []
            for step in steps:
                step_result = step.result or {}
                docs = step_result.get("documents") if isinstance(step_result, dict) else None
                if isinstance(docs, dict):
                    for doc in docs.values():
                        if isinstance(doc, dict) and doc.get("reader_id"):
                            readers.append(str(doc["reader_id"]))
                elif isinstance(docs, list):
                    for doc in docs:
                        if isinstance(doc, dict) and doc.get("reader_id"):
                            readers.append(str(doc["reader_id"]))
            if readers:
                # Preserve order, unique.
                seen: set[str] = set()
                uniq: list[str] = []
                for r in readers:
                    if r not in seen:
                        seen.add(r)
                        uniq.append(r)
                result["readers"] = uniq

    def _observe_learning(
        self, job_id: str, steps: list[JobStep], result: dict[str, Any]
    ) -> None:
        """Propose Experience + promote research artifacts (S18b + Stage 3 C6/A6).

        Governed and best-effort: never auto-verifies and never fails the job.
        """
        if self._learning is None and self._knowledge is None:
            return
        try:
            job = self._repo.get_job(job_id)
            if self._learning is not None:
                self._learning.observe_job(
                    {"job": job, "steps": steps, "result": result}
                )
            # Domain-tagged Knowledge promotion from the research workspace (A6).
            from atlas.research.learn import promote_research

            ws = self._workspace(job_id)
            promote_research(
                knowledge=self._knowledge,
                learning=self._learning,
                workspace=ws,
                job_id=str(job_id),
                objective=getattr(job, "objective", "") if job else "",
                embed=False,  # embeddings deferred — avoid blocking finalize
            )
        except Exception:  # noqa: BLE001 - learning must never break finalization
            self._logger.debug("job %s learning observation failed", job_id)

    def _enrich_from_research(self, job_id: str, result: dict[str, Any]) -> None:
        """Pull overall confidence / claims counts from the research workspace."""
        ws = self._workspace(job_id)
        if ws is None:
            return
        try:
            from atlas.evidence.models import CONFIDENCE_INSUFFICIENT

            claims = ws.read_json("claims.json") or []
            if claims:
                from collections import Counter

                counts = Counter(
                    (c.get("confidence") or "UNVERIFIED") for c in claims
                    if isinstance(c, dict)
                )
                if counts:
                    from_claims = counts.most_common(1)[0][0]
                    current = result.get("overall_confidence")
                    # Workspace claims win over an empty finalize render that
                    # stamped INSUFFICIENT / None.
                    if current in (None, CONFIDENCE_INSUFFICIENT) or not current:
                        result["overall_confidence"] = from_claims
                result["research_claims"] = len(claims)
        except Exception:  # noqa: BLE001
            pass

    def _usage_for_job(self, job_id: str, steps: list[JobStep]) -> dict[str, Any]:
        """Approximate data size read/stored for this job (workspace + pipeline)."""
        usage: dict[str, Any] = {}
        ws = self._workspace(job_id)
        if ws is not None:
            try:
                usage.update(ws.usage_stats())
            except Exception:  # noqa: BLE001
                pass
        # Merge any pipeline usage the research step already recorded.
        for step in steps:
            pipe = (step.result or {}).get("pipeline") or {}
            if not pipe and isinstance((step.result or {}).get("answer"), str):
                continue
            # tool_calls may carry the research payload indirectly; also check nested.
            for key in ("chars_read", "bytes_downloaded", "documents_read"):
                if key in pipe and key not in usage:
                    usage[key] = pipe[key]
            nested = (step.result or {}).get("usage")
            if isinstance(nested, dict):
                for k, v in nested.items():
                    usage.setdefault(k, v)
        # D32.14 / A32.23: per-job verified work rate, not CPU utilization.
        claims = ws.read_json("claims.json", []) if ws is not None else []
        if isinstance(claims, list) and claims:
            graded = sum(
                1
                for claim in claims
                if isinstance(claim, dict)
                and claim.get("confidence") in {"LOW", "MEDIUM", "HIGH"}
            )
            starts = [step.started_at for step in steps if step.started_at is not None]
            ends = [step.completed_at for step in steps if step.completed_at is not None]
            if (not starts or not ends) and ws is not None:
                # In-memory/test repositories may not stamp model timestamps;
                # the durable activity feed still records step boundaries.
                try:
                    from datetime import datetime

                    events = ws.read_activity()
                    step_events = [
                        event
                        for event in events
                        if event.get("phase") == "step" and event.get("ts")
                    ]
                    if step_events:
                        parsed = [
                            datetime.fromisoformat(str(event["ts"]))
                            for event in step_events
                        ]
                        starts = starts or [min(parsed)]
                        ends = ends or [max(parsed)]
                except (TypeError, ValueError, OSError):
                    pass
            if graded and starts and ends:
                elapsed = max(0.001, (max(ends) - min(starts)).total_seconds())
                usage["verified_claims"] = graded
                usage["research_elapsed_seconds"] = round(elapsed, 3)
                usage["verified_claims_per_hour"] = round(graded * 3600.0 / elapsed, 3)
        if usage and "human" not in usage:
            from atlas.jobs.workspace import _format_usage
            usage["human"] = _format_usage(
                int(usage.get("workspace_bytes", 0)),
                int(usage.get("downloads_bytes", 0)),
                int(usage.get("documents_bytes", 0)),
                int(usage.get("documents_chars", usage.get("chars_read", 0))),
                int(usage.get("documents_count", usage.get("documents_read", 0))),
            )
        if usage.get("verified_claims_per_hour") is not None:
            rate = usage["verified_claims_per_hour"]
            metric = (
                f"Verified work ≈ {rate:g} graded claim(s)/hour "
                f"({usage['verified_claims']} claim(s))."
            )
            human = str(usage.get("human") or "").strip()
            if metric not in human:
                usage["human"] = f"{human} {metric}".strip()
        return usage

    def add_job_input(self, job_id: str, text: str) -> dict[str, Any]:
        """Queue human guidance for a running or blocked job.

        Inputs land in ``inputs.jsonl`` (and ``notes.md``). Deep research drains
        them at the start of each round and turns them into extra search queries.
        They do not interrupt an in-flight extract/acquire of a single document.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("empty input")
        job = self._repo.get_job(job_id)
        if job is None:
            raise KeyError(f"no job {job_id}")
        ws = self._workspace(job_id)
        if ws is None:
            raise RuntimeError("job has no workspace; inputs require workspace_root")
        # Durable queue: research drains these between rounds; also lands in notes.md.
        ws.append_user_input(text)
        self._recorder(job_id).record(
            PHASE_LIFECYCLE,
            f"User input received: {text[:160]}",
            input_preview=text[:200],
        )
        return self.job_detail(job_id)

    def _build_report(self, job_id: str, steps: list[JobStep]) -> dict[str, Any] | None:
        """Attach a scientific-review report (§5a.5) to the finished job (S17).

        Prefer claims/sources already written by deep research into the job
        workspace. Finalizing with ``claims=[]`` used to overwrite a good
        research report with "_No verified claims._" / INSUFFICIENT.
        """
        if self._reports is None:
            return None
        job = self._repo.get_job(job_id)
        objective = job.objective if job else ""
        answer = self._answer(steps)
        claims, sources = self._research_artifacts(job_id)
        findings, reasoning, pipeline = self._research_synthesis(job_id)
        if not sources:
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
        # If research already wrote a full report and we have no claims to
        # re-render, keep that markdown rather than clobbering it — unless this
        # job stopped at acquire / interactive recovery (RH.5).
        termination = self._acquire_termination_from_steps(steps)
        if not claims and termination is None:
            existing = self._existing_research_report(job_id)
            if existing is not None:
                return existing
        try:
            return self._reports.render(
                objective,
                claims=claims,
                findings=findings or None,
                sources=sources,
                answer=answer if not claims else "",
                notes=answer[:600],
                reasoning=reasoning or None,
                pipeline=pipeline or None,
                termination=termination,
            )
        except Exception:  # noqa: BLE001 - a report must never fail the job
            self._logger.exception("job %s report generation failed", job_id)
            return None

    def _research_artifacts(
        self, job_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load claims + sources from the research workspace when present."""
        ws = self._workspace(job_id)
        if ws is None:
            return [], []
        try:
            claims = ws.read_json("claims.json") or []
            if not isinstance(claims, list):
                claims = []
            evidence = ws.read_json("evidence.json") or {}
            sources = evidence.get("sources") if isinstance(evidence, dict) else []
            if not isinstance(sources, list):
                sources = []
            return claims, sources
        except Exception:  # noqa: BLE001
            return [], []

    def _research_synthesis(
        self, job_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        """Load findings + reasoning + pipeline the research step wrote.

        Re-rendering the job report from ``claims.json`` alone silently dropped
        findings, cross-document patterns/opportunities, and the funnel — the
        report then disagreed with the runtime. Carry them through instead.
        """
        ws = self._workspace(job_id)
        if ws is None:
            return [], {}, {}
        try:
            findings = ws.read_json("findings.json") or []
            if not isinstance(findings, list):
                findings = []
            reasoning = ws.read_json("reasoning.json") or {}
            if not isinstance(reasoning, dict):
                reasoning = {}
            pipeline = ws.read_json("pipeline.json") or {}
            if not isinstance(pipeline, dict):
                pipeline = {}
            return findings, reasoning, pipeline
        except Exception:  # noqa: BLE001
            return [], {}, {}

    def _existing_research_report(self, job_id: str) -> dict[str, Any] | None:
        """Reuse report.md written during the research step, if any."""
        ws = self._workspace(job_id)
        if ws is None:
            return None
        try:
            path = ws.report_path
            if not path.is_file():
                return None
            md = path.read_text(encoding="utf-8")
            if not md or "_No verified claims._" in md:
                return None
            # Prefer confidence from claims when present.
            overall = None
            claims = ws.read_json("claims.json") or []
            if isinstance(claims, list) and claims:
                from collections import Counter

                counts = Counter(
                    (c.get("confidence") or "UNVERIFIED")
                    for c in claims
                    if isinstance(c, dict)
                )
                if counts:
                    overall = counts.most_common(1)[0][0]
            return {
                "markdown": md,
                "sections": {},
                "overall_confidence": overall,
            }
        except Exception:  # noqa: BLE001
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
                    "usage": result.get("usage"),
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
        parts: list[str] = []
        for s in steps:
            result = s.result or {}
            ans = result.get("answer") or ""
            if not ans:
                continue
            if s.status == STEP_DONE:
                parts.append(ans)
            elif s.status == STEP_BLOCKED:
                # RH.6: blocked / waiting steps carry the operator summary.
                parts.append(ans)
        return "\n\n".join(parts)

    def _acquire_termination_from_steps(
        self, steps: list[JobStep]
    ) -> dict[str, Any] | None:
        """Build ReportGenerator termination for media.learn / acquire wait (RH.5)."""
        for step in steps:
            if step.status != STEP_BLOCKED:
                continue
            result = step.result if isinstance(step.result, dict) else {}
            interactive = bool(result.get("interactive_recovery"))
            acq = result.get("acquisition") if isinstance(result.get("acquisition"), dict) else {}
            strategies = result.get("strategies") or acq.get("strategies_tried") or []
            suggestions = (
                result.get("suggested_next_strategies")
                or acq.get("suggested_next_strategies")
                or []
            )
            reason = (
                step.blocked_reason
                or result.get("blocked_reason")
                or acq.get("reason_code")
                or "interactive_recovery_required"
            )
            if not interactive and step.intent not in ("media_learn",) and not acq:
                # Generic blocked (needs file / capability) — still report honestly
                # if media.learn-shaped extras exist; otherwise skip.
                if step.intent != "media_learn" and "interactive_recovery" not in reason:
                    continue
            status = "waiting" if (
                interactive
                or reason in (
                    "interactive_recovery_required",
                    "operator_upload_required",
                )
            ) else "blocked"
            return {
                "stage": "acquire",
                "status": status,
                "reason": reason,
                "reason_code": acq.get("reason_code") or reason,
                "knowledge_produced": 0,
                "reasoning": "not_started",
                "verification": "not_executed",
                "waiting_for": result.get("waiting_for") or "media_asset",
                "suggested_next_strategies": list(suggestions) if suggestions else None,
                "speech_to_text_status": result.get("speech_to_text_status")
                or acq.get("speech_to_text_status"),
                "strategies_tried": strategies,
                "audience": "job",
            }
        return None

    def _build_context(self, job: Job) -> ConversationContext:
        # Stage 3 (C0/RL + C4): attach the live activity recorder + workspace so
        # deep research (and later learners) can stream progress into the feed
        # and persist claims/evidence on disk during the step.
        activity = self._recorder(job.id)
        workspace = self._workspace(job.id)
        if job.session_id and self._conversation is not None:
            try:
                ctx = self._conversation.build_context(job.session_id, job.objective)
                return ConversationContext(
                    session_id=ctx.session_id,
                    recent=list(ctx.recent),
                    memories=list(ctx.memories),
                    job_id=str(job.id),
                    activity=activity,
                    workspace=workspace,
                )
            except Exception:  # noqa: BLE001 - context is best-effort
                self._logger.exception("failed to build job context")
        return ConversationContext(
            session_id=job.session_id or f"job:{job.id}",
            job_id=str(job.id),
            activity=activity,
            workspace=workspace,
        )

    def _enqueue_advance(self, job_id: str) -> None:
        if self._enqueue is None:
            return
        self._enqueue(ADVANCE_TASK, {"job_id": str(job_id)})

    def _enqueue_plan(self, job_id: str) -> None:
        if self._enqueue is None:
            return
        self._enqueue(PLAN_TASK, {"job_id": str(job_id)})

    @staticmethod
    def _phase_of(job: Job) -> str:
        meta = job.metadata if isinstance(job.metadata, dict) else {}
        phase = meta.get(JOB_PHASE_KEY)
        if isinstance(phase, str) and phase:
            return phase
        return PHASE_READY

    def _set_phase(self, job_id: str, phase: str) -> None:
        try:
            self._repo.merge_job_metadata(job_id, {JOB_PHASE_KEY: phase})
        except Exception:  # noqa: BLE001 - phase is best-effort observability
            self._logger.debug("job %s phase update failed", job_id)

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
        planned = 0
        advanced = 0
        for job in unfinished:
            steps = self._repo.list_steps(job.id)
            phase = self._phase_of(job)
            if not steps or phase in JOB_PLANNING_PHASES:
                self._enqueue_plan(job.id)
                planned += 1
            else:
                self._enqueue_advance(job.id)
                advanced += 1
        if planned or advanced:
            self._logger.info(
                "re-enqueued %d planning + %d advance job(s)", planned, advanced
            )

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            total = self._repo.count_jobs()
            running = self._repo.count_jobs(status=JOB_RUNNING)
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"job store unreachable: {exc}")
        return HealthStatus.ok(f"{total} job(s), {running} running", jobs=total, running=running)
