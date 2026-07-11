"""Tests for the Job Engine service (S12): advance loop, blocking, resume, recovery.

Hermetic: an in-memory JobRepository stand-in and a scripted step runner drive the
service without a database or LLM.
"""

from __future__ import annotations

import dataclasses

from atlas.jobs.planner import DecomposedStep
from atlas.jobs.service import JobService
from atlas.models.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_COMPLETED_WITH_BLOCKS,
    JOB_QUEUED,
    JOB_RUNNING,
    STEP_BLOCKED,
    STEP_DONE,
    STEP_PENDING,
    STEP_RUNNING,
    Job,
    JobStep,
)


class FakeJobRepo:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._steps: dict[str, JobStep] = {}
        self._seq = 0

    def _id(self, prefix):
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def create_job(self, objective, *, session_id=None, metadata=None):
        jid = self._id("job")
        job = Job(id=jid, objective=objective, session_id=session_id)
        self._jobs[jid] = job
        return job

    def get_job(self, job_id):
        return self._jobs.get(str(job_id))

    def list_jobs(self, *, status=None, limit=50):
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs[:limit]

    def set_job_status(self, job_id, status, *, result=None, error=None):
        job = self._jobs[str(job_id)]
        changes = {"status": status}
        if result is not None:
            changes["result"] = result
        if error is not None:
            changes["error"] = error
        self._jobs[str(job_id)] = dataclasses.replace(job, **changes)
        return True

    def count_jobs(self, *, status=None):
        return len(self.list_jobs(status=status, limit=10_000))

    def add_step(self, job_id, ordinal, intent, capability, *, args=None,
                 description="", depends_on=None):
        sid = self._id("step")
        step = JobStep(
            id=sid, job_id=str(job_id), ordinal=ordinal, intent=intent,
            capability=capability, args=args or {}, description=description,
            depends_on=depends_on,
        )
        self._steps[sid] = step
        return step

    def list_steps(self, job_id):
        steps = [s for s in self._steps.values() if s.job_id == str(job_id)]
        return sorted(steps, key=lambda s: s.ordinal)

    def set_step_status(self, step_id, status, *, result=None, error=None,
                        blocked_reason=None, bump_attempts=False):
        step = self._steps[str(step_id)]
        changes = {"status": status, "error": error, "blocked_reason": blocked_reason}
        if result is not None:
            changes["result"] = result
        if bump_attempts:
            changes["attempts"] = step.attempts + 1
        self._steps[str(step_id)] = dataclasses.replace(step, **changes)
        return True

    def reset_blocked_steps(self, job_id):
        n = 0
        for sid, step in list(self._steps.items()):
            if step.job_id == str(job_id) and step.status in {STEP_BLOCKED, "skipped"}:
                self._steps[sid] = dataclasses.replace(
                    step, status=STEP_PENDING, blocked_reason=None, error=None
                )
                n += 1
        return n

    def recover_interrupted_steps(self):
        n = 0
        for sid, step in list(self._steps.items()):
            if step.status == STEP_RUNNING:
                self._steps[sid] = dataclasses.replace(step, status=STEP_PENDING)
                n += 1
        return n

    def list_unfinished_jobs(self):
        return [j for j in self._jobs.values() if j.status in {JOB_QUEUED, JOB_RUNNING}]


@dataclasses.dataclass
class _Outcome:
    answer: str = "ok"
    citations: list = dataclasses.field(default_factory=list)
    run_id: str | None = None
    blocked: bool = False
    blocked_reason: str | None = None


class ScriptedRunner:
    """Runner whose behaviour depends on the step's capability."""

    def __init__(self, blocked_caps=()):
        self._blocked = set(blocked_caps)
        self.calls = []

    def run_step(self, intent, args, *, context=None, tool_calls=None, capability=None):
        self.calls.append((intent, capability))
        if capability in self._blocked:
            return _Outcome(answer="blocked", blocked=True,
                            blocked_reason=f"needs capability: {capability}")
        return _Outcome(answer=f"did {intent}")


class FakePlanner:
    def __init__(self, steps):
        self._steps = steps

    def decompose(self, objective):
        return list(self._steps)


def _drive(service, job_id, enqueue_log, limit=50):
    """Simulate the scheduler: advance while the job re-enqueues itself."""
    enqueue_log.clear()
    enqueue_log.append(job_id)
    seen = 0
    while enqueue_log and seen < limit:
        enqueue_log.pop(0)
        service.advance_job_task({"job_id": job_id})
        seen += 1


def _make(planner_steps, runner):
    repo = FakeJobRepo()
    enqueue_log = []

    def enqueue(task_type, payload):
        enqueue_log.append(payload["job_id"])

    service = JobService(
        repo, FakePlanner(planner_steps), runner, enqueue=enqueue
    )
    return repo, service, enqueue_log


def test_create_job_persists_steps_and_enqueues():
    steps = [DecomposedStep("react", "agent", {"query": "x"}, "reason")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("do x")
    assert detail["progress"]["total"] == 1
    assert len(log) == 1  # advance enqueued once


def test_job_runs_to_completion():
    steps = [
        DecomposedStep("react", "agent", {}, "a"),
        DecomposedStep("ask_knowledge", "knowledge", {}, "b"),
    ]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("two step")
    jid = detail["job"].id
    _drive(service, jid, log)
    job = repo.get_job(jid)
    assert job.status == JOB_COMPLETED
    assert all(s.status == STEP_DONE for s in repo.list_steps(jid))
    assert "did react" in job.result["answer"]


def test_blocked_step_yields_completed_with_blocks():
    steps = [
        DecomposedStep("react", "agent", {}, "a"),
        DecomposedStep("web_fetch", "web", {}, "b"),  # web is blocked
    ]
    repo, service, log = _make(steps, ScriptedRunner(blocked_caps={"web"}))
    detail = service.create_job("needs web")
    jid = detail["job"].id
    _drive(service, jid, log)
    job = repo.get_job(jid)
    assert job.status == JOB_COMPLETED_WITH_BLOCKS
    blocked = [s for s in repo.list_steps(jid) if s.status == STEP_BLOCKED]
    assert len(blocked) == 1
    assert "needs capability: web" in blocked[0].blocked_reason


def test_dependency_cascade_blocks_dependents():
    steps = [
        DecomposedStep("web_fetch", "web", {}, "fetch"),  # blocks
        DecomposedStep("ask_knowledge", "knowledge", {}, "use", depends_on=0),
    ]
    repo, service, log = _make(steps, ScriptedRunner(blocked_caps={"web"}))
    detail = service.create_job("chain")
    jid = detail["job"].id
    _drive(service, jid, log)
    job = repo.get_job(jid)
    assert job.status == JOB_COMPLETED_WITH_BLOCKS
    step1 = repo.list_steps(jid)[1]
    assert step1.status == STEP_BLOCKED
    assert "depends on blocked step 0" in step1.blocked_reason


def test_resume_reruns_blocked_steps():
    steps = [DecomposedStep("web_fetch", "web", {}, "fetch")]
    runner = ScriptedRunner(blocked_caps={"web"})
    repo, service, log = _make(steps, runner)
    detail = service.create_job("needs web")
    jid = detail["job"].id
    _drive(service, jid, log)
    assert repo.get_job(jid).status == JOB_COMPLETED_WITH_BLOCKS

    # user "provides" the capability: runner no longer blocks web
    runner._blocked.clear()
    service.resume_job(jid)
    assert repo.get_job(jid).status == JOB_QUEUED
    _drive(service, jid, log)
    assert repo.get_job(jid).status == JOB_COMPLETED


def test_cancel_marks_job_cancelled_and_stops_advance():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("cancel me")
    jid = detail["job"].id
    service.cancel_job(jid)
    assert repo.get_job(jid).status == JOB_CANCELLED
    # advancing a cancelled job is a no-op
    service.advance_job_task({"job_id": jid})
    assert repo.get_job(jid).status == JOB_CANCELLED


def test_recovery_reenqueues_unfinished_and_resets_running_steps():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("recover me")
    jid = detail["job"].id
    # simulate a crash mid-step
    repo.set_job_status(jid, JOB_RUNNING)
    step = repo.list_steps(jid)[0]
    repo.set_step_status(step.id, STEP_RUNNING)
    log.clear()

    service.start()
    assert repo.list_steps(jid)[0].status == STEP_PENDING
    assert jid in log  # re-enqueued


def test_advance_unknown_job_is_safe():
    repo, service, log = _make([], ScriptedRunner())
    assert service.advance_job_task({"job_id": "nope"})["status"] == "unknown_job"
