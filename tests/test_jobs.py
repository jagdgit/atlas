"""Tests for the Job Engine service (S12 + 3.2e): plan, advance, block, resume, recovery.

Hermetic: an in-memory JobRepository stand-in and a scripted step runner drive the
service without a database or LLM.
"""

from __future__ import annotations

import dataclasses
import time

from atlas.jobs.planner import DecomposedStep, JobPlanner
from atlas.jobs.service import ADVANCE_TASK, PLAN_TASK, JobService
from atlas.models.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_COMPLETED_WITH_BLOCKS,
    JOB_PHASE_KEY,
    JOB_QUEUED,
    JOB_RUNNING,
    PHASE_PLANNING_QUEUED,
    PHASE_READY,
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
        job = Job(
            id=jid,
            objective=objective,
            session_id=session_id,
            metadata=dict(metadata or {}),
        )
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

    def merge_job_metadata(self, job_id, patch):
        job = self._jobs[str(job_id)]
        meta = dict(job.metadata or {})
        meta.update(patch)
        self._jobs[str(job_id)] = dataclasses.replace(job, metadata=meta)
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
        self.last_source = "deterministic"

    def decompose(self, objective):
        self.last_source = "deterministic"
        return list(self._steps)


def _drive(service, job_id, enqueue_log, limit=50):
    """Simulate the scheduler: drain plan_job + advance_job for this job."""
    seen = 0
    while enqueue_log and seen < limit:
        item = enqueue_log.pop(0)
        if isinstance(item, tuple):
            task_type, jid = item
        else:
            task_type, jid = ADVANCE_TASK, item
        if jid != job_id:
            continue
        if task_type == PLAN_TASK:
            service.plan_job_task({"job_id": job_id})
        else:
            service.advance_job_task({"job_id": job_id})
        seen += 1


class FakeEvents:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload=None, source=None):
        self.events.append((event_type, payload or {}))


class FakeLearning:
    def __init__(self):
        self.observed = []

    def observe_job(self, detail):
        self.observed.append(detail)
        return {"event": {"id": "evt-1"}, "applied": False}


def _make(planner_steps, runner, *, reports=None, events=None, learning=None,
          workspace_root=None, planner=None):
    repo = FakeJobRepo()
    enqueue_log = []

    def enqueue(task_type, payload):
        enqueue_log.append((task_type, payload["job_id"]))

    service = JobService(
        repo, planner or FakePlanner(planner_steps), runner,
        enqueue=enqueue, reports=reports, events=events, learning=learning,
        workspace_root=workspace_root,
    )
    return repo, service, enqueue_log


def test_create_job_queues_planning_without_steps():
    steps = [DecomposedStep("react", "agent", {"query": "x"}, "reason")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("do x")
    assert detail["phase"] == PHASE_PLANNING_QUEUED
    assert detail["progress"]["total"] == 0
    assert detail["steps"] == []
    assert log == [(PLAN_TASK, detail["job"].id)]
    assert detail["job"].metadata.get(JOB_PHASE_KEY) == PHASE_PLANNING_QUEUED


def test_plan_job_persists_steps_and_enqueues_advance():
    steps = [DecomposedStep("react", "agent", {"query": "x"}, "reason")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("do x")
    jid = detail["job"].id
    out = service.plan_job_task({"job_id": jid})
    assert out["status"] == "planned"
    assert out["steps"] == 1
    planned = service.job_detail(jid)
    assert planned["phase"] == PHASE_READY
    assert planned["progress"]["total"] == 1
    assert (ADVANCE_TASK, jid) in log


def test_create_returns_fast_with_slow_llm_planner(tmp_path):
    """3.2e: HTTP create must not wait on a slow/stuck planner LLM."""

    class SlowRole:
        def chat(self, messages, **options):
            time.sleep(0.35)
            raise TimeoutError("simulated planner timeout")

    class SlowLLM:
        def for_role(self, role):
            return SlowRole()

    planner = JobPlanner(llm=SlowLLM(), timeout=0.05, research_first=True)
    repo, service, log = _make(
        [], ScriptedRunner(), planner=planner, workspace_root=tmp_path
    )

    t0 = time.perf_counter()
    detail = service.create_job("Research soiling estimation")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2  # must not wait on the slow LLM
    assert detail["phase"] == PHASE_PLANNING_QUEUED
    assert detail["progress"]["total"] == 0

    service.plan_job_task({"job_id": detail["job"].id})
    assert planner.last_source == "fallback"
    planned = service.job_detail(detail["job"].id)
    assert planned["progress"]["total"] == 1
    assert planned["phase"] == PHASE_READY
    assert any(
        (a.get("data") or {}).get("fallback")
        or "deterministic" in a["message"].lower()
        for a in planned["activity"]
        if a["phase"] == "planning"
    )


def test_workspace_created_and_report_persisted(tmp_path):
    # §5a/C3: with a workspace root, a job gets an on-disk directory with a manifest
    # at creation and the final report written on finalize.
    from atlas.jobs.workspace import JobWorkspace

    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner(), workspace_root=tmp_path)
    detail = service.create_job("study soiling")
    jid = detail["job"].id

    ws = JobWorkspace.for_job(tmp_path, jid)
    assert ws.manifest_path.is_file()
    assert ws.load_manifest()["objective"] == "study soiling"

    _drive(service, jid, log)
    assert repo.get_job(jid).status == JOB_COMPLETED
    # notes.md records the lifecycle; report.md/result.json exist after finalize.
    notes = ws.notes_path.read_text(encoding="utf-8")
    assert "job created" in notes
    assert "planning" in notes.lower() or "planned" in notes.lower()
    assert ws.read_json("result.json")["status"] == JOB_COMPLETED


def test_activity_feed_recorded_and_exposed(tmp_path):
    # RL/C0: a job emits progress events to the workspace feed and the event bus,
    # and job_detail exposes the tail for the live Console view.
    steps = [DecomposedStep("react", "agent", {}, "reason about it")]
    events = FakeEvents()
    repo, service, log = _make(
        steps, ScriptedRunner(), events=events, workspace_root=tmp_path
    )
    detail = service.create_job("watch me")
    jid = detail["job"].id
    # creation already logged lifecycle + planning events
    phases = [a["phase"] for a in detail["activity"]]
    assert "lifecycle" in phases and "planning" in phases
    assert any("planning queued" in a["message"].lower() for a in detail["activity"])

    _drive(service, jid, log)
    final = service.job_detail(jid)
    phases = [a["phase"] for a in final["activity"]]
    messages = " ".join(a["message"] for a in final["activity"])
    assert "lifecycle" in phases and "step" in phases and "planning" in phases
    assert "submitted" in messages.lower() or "planning" in messages.lower()
    assert "completed" in messages.lower()
    # the same events were pushed live on the bus
    assert any(e[0] == "job.activity" for e in events.events)


def test_job_context_carries_activity_and_workspace(tmp_path):
    # Stage 3 fast-follow: JobService attaches the recorder + workspace to the
    # ConversationContext so research (and later learners) can stream live.
    steps = [DecomposedStep("research", "research", {"objective": "x"}, "research it")]
    repo, service, log = _make(steps, ScriptedRunner(), workspace_root=tmp_path)
    detail = service.create_job("deep research")
    job = repo.get_job(detail["job"].id)
    ctx = service._build_context(job)
    assert ctx.job_id == str(job.id)
    assert ctx.activity is not None
    assert ctx.workspace is not None
    assert "job_" in str(ctx.workspace.root)


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
    # advancing / planning a cancelled job is a no-op
    assert service.plan_job_task({"job_id": jid})["status"] == JOB_CANCELLED
    service.advance_job_task({"job_id": jid})
    assert repo.get_job(jid).status == JOB_CANCELLED


def test_recovery_reenqueues_unfinished_and_resets_running_steps():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("recover me")
    jid = detail["job"].id
    service.plan_job_task({"job_id": jid})
    # simulate a crash mid-step
    repo.set_job_status(jid, JOB_RUNNING)
    step = repo.list_steps(jid)[0]
    repo.set_step_status(step.id, STEP_RUNNING)
    log.clear()

    service.start()
    assert repo.list_steps(jid)[0].status == STEP_PENDING
    assert (ADVANCE_TASK, jid) in log


def test_recovery_reenqueues_planning_without_steps():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner())
    detail = service.create_job("still planning")
    jid = detail["job"].id
    log.clear()
    service.start()
    assert (PLAN_TASK, jid) in log


def test_advance_unknown_job_is_safe():
    repo, service, log = _make([], ScriptedRunner())
    assert service.advance_job_task({"job_id": "nope"})["status"] == "unknown_job"
    assert service.plan_job_task({"job_id": "nope"})["status"] == "unknown_job"


# --- S17: report on finalize + notifications + blocked queue --------------
def _reports():
    from atlas.reports.service import ReportService

    return ReportService()  # no verification/LLM → deterministic render


def test_report_attached_on_finalize():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner(), reports=_reports())
    jid = service.create_job("investigate x")["job"].id
    _drive(service, jid, log)
    job = repo.get_job(jid)
    assert "# Research Report:" in job.result["report"]
    assert "report_sections" in job.result
    assert job.result["overall_confidence"] is not None


def test_notifications_emitted_on_block_and_finalize():
    steps = [DecomposedStep("web_fetch", "web", {}, "b")]
    events = FakeEvents()
    repo, service, log = _make(
        steps, ScriptedRunner(blocked_caps={"web"}), events=events
    )
    jid = service.create_job("needs web")["job"].id
    _drive(service, jid, log)
    types = [t for t, _ in events.events]
    assert "job.step_blocked" in types
    assert "job.finalized" in types


def test_learning_observed_on_finalize():
    steps = [DecomposedStep("react", "agent", {}, "a")]
    learning = FakeLearning()
    repo, service, log = _make(steps, ScriptedRunner(), learning=learning)
    jid = service.create_job("investigate x")["job"].id
    _drive(service, jid, log)
    assert len(learning.observed) == 1
    detail = learning.observed[0]
    assert detail["job"].id == jid
    assert detail["steps"]


def test_list_blocked_aggregates_across_jobs():
    steps = [DecomposedStep("web_fetch", "web", {}, "b")]
    repo, service, log = _make(steps, ScriptedRunner(blocked_caps={"web"}))
    jid = service.create_job("needs web")["job"].id
    _drive(service, jid, log)
    blocked = service.list_blocked()
    assert len(blocked) == 1
    assert blocked[0]["job_id"] == jid
    assert blocked[0]["capability"] == "web"
    assert blocked[0]["objective"] == "needs web"


def test_add_job_input_queues_for_workspace(tmp_path):
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner(), workspace_root=tmp_path)
    jid = service.create_job("study soiling")["job"].id
    detail = service.add_job_input(jid, "prefer peer-reviewed soiling loss %")
    assert any("User input" in a["message"] for a in detail["activity"])
    from atlas.jobs.workspace import JobWorkspace

    ws = JobWorkspace.for_job(tmp_path, jid)
    assert ws.pending_user_inputs() == ["prefer peer-reviewed soiling loss %"]


def test_finalize_attaches_usage(tmp_path):
    steps = [DecomposedStep("react", "agent", {}, "a")]
    repo, service, log = _make(steps, ScriptedRunner(), workspace_root=tmp_path)
    jid = service.create_job("measure usage")["job"].id
    from atlas.jobs.workspace import JobWorkspace

    ws = JobWorkspace.for_job(tmp_path, jid)
    ws.document_path("s1").write_text("soiling loss data " * 50, encoding="utf-8")
    _drive(service, jid, log)
    job = repo.get_job(jid)
    assert "usage" in (job.result or {})
    assert "human" in job.result["usage"]
    assert "Text read" in job.result["usage"]["human"]


def test_finalize_uses_workspace_claims_not_empty_report(tmp_path):
    # Regression: finalize used to render claims=[] and overwrite research
    # report.md with "_No verified claims._" / INSUFFICIENT.
    steps = [DecomposedStep("research", "research", {}, "research it")]
    repo, service, log = _make(
        steps, ScriptedRunner(), reports=_reports(), workspace_root=tmp_path
    )
    jid = service.create_job("study soiling estimators")["job"].id
    from atlas.jobs.workspace import JobWorkspace

    ws = JobWorkspace.for_job(tmp_path, jid)
    ws.write_json(
        "claims.json",
        [
            {
                "id": "c1",
                "statement": "SVR linear kernel beat ridge by roughly 0.4%.",
                "confidence": "LOW",
                "confidence_score": 0.4,
                "supporting_sources": [
                    {
                        "source_id": "https://arxiv.org/abs/2301.12939",
                        "evidence_level": 3,
                        "level_name": "L3 government/lab",
                    }
                ],
                "contradicting_sources": [],
            }
        ],
    )
    ws.write_json(
        "evidence.json",
        {
            "sources": [
                {
                    "id": "https://arxiv.org/abs/2301.12939",
                    "title": "Data-driven soiling detection in PV modules",
                    "url": "https://arxiv.org/abs/2301.12939",
                    "evidence_level": 3,
                    "level_name": "L3 government/lab",
                }
            ],
            "claims": [],
        },
    )
    _drive(service, jid, log)
    job = repo.get_job(jid)
    md = job.result["report"]
    assert "_No verified claims._" not in md
    assert "SVR linear kernel" in md
    assert job.result["overall_confidence"] == "LOW"
    assert "Data-driven soiling detection" in md
