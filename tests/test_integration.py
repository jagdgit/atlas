"""End-to-end integration test (S22) — the research spine, hermetically.

This is the missing full-flow test the S22 audit flagged: it drives a real
objective through the *real* Job Engine → AssistantService dispatch → ResearchService
gather→verify→decide loop → Verification Engine → Report Generator, with only the
external providers (scholar/search) faked. No database, no network, no LLM.

It wires the same objects ``build_application`` wires, but with an in-memory job
repo and a synchronous scheduler stand-in, so a job advances step-by-step to
completion and produces a verified report — proving the components compose.
"""

from __future__ import annotations

import dataclasses
import uuid

from atlas.conversation.service import ConversationService
from atlas.execution.executor import ToolExecutor
from atlas.jobs.planner import JobPlanner
from atlas.jobs.service import JobService
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.tools import ToolRegistry
from atlas.models.job import (
    JOB_COMPLETED,
    JOB_QUEUED,
    JOB_TERMINAL,
    STEP_PENDING,
    Job,
    JobStep,
)
from atlas.planner.planner import Planner
from atlas.reports.generator import ReportGenerator
from atlas.reports.service import ReportService
from atlas.research.service import ResearchService
from atlas.search.scholarly import Paper, ScholarlyResponse
from atlas.services.assistant_service import AssistantService
from atlas.verification.engine import EvidenceBudget, VerificationEngine
from atlas.verification.service import VerificationService

from tests.test_assistant import FakeAgent, FakeConvRepo, FakeKnowledge, FakeLLM


# --- fakes: only the *external* edges ------------------------------------
class FakeScholar:
    def search_scholar(self, query, max_results=None):
        papers = [
            Paper(title=f"Study {i}", url=f"https://s2.org/{i}", doi=f"10.1/{i}",
                  abstract="the measured value is 42 units", evidence_level=lvl)
            for i, lvl in enumerate([4, 4, 4, 3, 3])
        ]
        return ScholarlyResponse(query, "fake_scholar", "ok", papers=papers)


class InMemoryJobRepo:
    """A faithful in-memory stand-in for JobRepository (job.* tables)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._steps: dict[str, JobStep] = {}

    def create_job(self, objective, *, session_id=None) -> Job:
        job = Job(id=str(uuid.uuid4()), objective=objective, status=JOB_QUEUED,
                  session_id=session_id)
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id) -> Job | None:
        return self._jobs.get(job_id)

    def add_step(self, job_id, ordinal, intent, capability, *, args=None,
                 description="", depends_on=None) -> JobStep:
        step = JobStep(
            id=str(uuid.uuid4()), job_id=job_id, ordinal=ordinal, intent=intent,
            capability=capability, args=args or {}, description=description,
            depends_on=depends_on,
        )
        self._steps[step.id] = step
        return step

    def list_steps(self, job_id) -> list[JobStep]:
        return sorted(
            (s for s in self._steps.values() if s.job_id == job_id),
            key=lambda s: s.ordinal,
        )

    def list_jobs(self, *, status=None, limit=50) -> list[Job]:
        jobs = [j for j in self._jobs.values() if status is None or j.status == status]
        return jobs[:limit]

    def set_step_status(self, step_id, status, *, result=None, blocked_reason=None,
                        error=None, bump_attempts=False) -> None:
        step = self._steps[step_id]
        changes = {"status": status}
        if result is not None:
            changes["result"] = result
        if blocked_reason is not None:
            changes["blocked_reason"] = blocked_reason
        if error is not None:
            changes["error"] = error
        if bump_attempts:
            changes["attempts"] = step.attempts + 1
        self._steps[step_id] = dataclasses.replace(step, **changes)

    def set_job_status(self, job_id, status, *, result=None) -> None:
        job = self._jobs[job_id]
        changes = {"status": status}
        if result is not None:
            changes["result"] = result
        self._jobs[job_id] = dataclasses.replace(job, **changes)

    def count_jobs(self, *, status=None) -> int:
        return len(self.list_jobs(status=status, limit=10_000))


def _research_service() -> ResearchService:
    verification = VerificationService(
        VerificationEngine(numeric_tolerance=0.15), default_budget=EvidenceBudget()
    )
    reports = ReportService(verification, ReportGenerator())
    return ResearchService(verification, reports, scholar=FakeScholar())


def _assistant_with_research(tools: ToolRegistry) -> AssistantService:
    research = _research_service()
    tools.register("research.run", research.research,
                   description="run research loop", plugin="research")
    caps = CapabilityRegistry()
    caps.register("research", research, kind="service")
    return AssistantService(
        ConversationService(FakeConvRepo(), None),
        Planner(),
        ToolExecutor(tools, retry_base=0.0),
        knowledge=FakeKnowledge(),
        agent=FakeAgent(),
        llm=FakeLLM(),
        tools=tools,
        capabilities=caps,
    )


def _drain(job_service: JobService, pending: list) -> None:
    # Synchronous scheduler stand-in: keep advancing until the job is terminal.
    guard = 0
    while pending:
        guard += 1
        assert guard < 50, "job did not converge to a terminal state"
        job_service.advance_job_task(pending.pop(0))


def test_research_job_runs_end_to_end_and_reports():
    tools = ToolRegistry()
    assistant = _assistant_with_research(tools)
    repo = InMemoryJobRepo()
    reports = ReportService(VerificationService(VerificationEngine()), ReportGenerator())

    pending: list = []
    job_service = JobService(
        repo,
        JobPlanner(Planner(), None),  # deterministic decomposition (no LLM)
        assistant,
        enqueue=lambda task_type, payload: pending.append(payload),
        reports=reports,
    )

    detail = job_service.create_job("research the value of X")
    job_id = detail["job"].id
    _drain(job_service, pending)

    job = repo.get_job(job_id)
    assert job.status == JOB_COMPLETED
    # The research step ran through the real loop and produced a HIGH-confidence answer.
    assert "HIGH" in job.result["answer"]
    assert "Study" in job.result["answer"]  # sources surfaced
    # A scientific-review report was attached on finalize.
    assert job.result["report"]  # non-empty markdown
    assert "report_sections" in job.result


def test_research_job_decomposes_to_research_capability():
    tools = ToolRegistry()
    assistant = _assistant_with_research(tools)
    repo = InMemoryJobRepo()
    pending: list = []
    job_service = JobService(
        repo, JobPlanner(Planner(), None), assistant,
        enqueue=lambda task_type, payload: pending.append(payload),
    )
    job_service.create_job("investigate the value of Y with evidence")
    job = repo.list_jobs()[0]
    steps = repo.list_steps(job.id)
    assert steps and steps[0].capability == "research"
    assert steps[0].status == STEP_PENDING  # not yet advanced
    assert job.status == JOB_QUEUED
    assert JOB_COMPLETED in JOB_TERMINAL
