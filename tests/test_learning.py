"""Hermetic tests for the Learning Pipeline (S18b, D11/§5d).

A small in-memory ``FakeLearningRepo`` stands in for the SQL repository so the
service's governance behaviour (propose → apply → revert, never silent, reversible,
explainable, recall) is exercised without a database.
"""

from __future__ import annotations

import dataclasses

from atlas.config import LearningConfig
from atlas.models.learning import (
    EVENT_APPLIED,
    EVENT_PROPOSED,
    EVENT_REVERTED,
    EXP_ACTIVE,
    EXP_REVERTED,
    Experience,
    LearningEvent,
)
from atlas.services.learning_service import LearningService, _experience_from_job


class FakeLearningRepo:
    def __init__(self):
        self._events: dict[str, LearningEvent] = {}
        self._exps: dict[str, Experience] = {}
        self._seq = 0

    def _id(self, prefix):
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def record_event(self, source_type, store, **kw):
        eid = self._id("evt")
        event = LearningEvent(
            id=eid, source_type=source_type, store=store,
            source_id=kw.get("source_id"), policy=kw.get("policy", "temporary"),
            level=kw.get("level", 1), status=kw.get("status", "proposed"),
            summary=kw.get("summary", ""), reason=kw.get("reason", ""),
            origin=kw.get("origin", ""), project=kw.get("project"),
            ref_id=kw.get("ref_id"), metadata=kw.get("metadata") or {},
        )
        self._events[eid] = event
        return event

    def get_event(self, event_id):
        return self._events.get(str(event_id))

    def list_events(self, *, status=None, store=None, limit=50):
        out = list(self._events.values())
        if status:
            out = [e for e in out if e.status == status]
        if store:
            out = [e for e in out if e.store == store]
        return out[:limit]

    def set_event_status(self, event_id, status, *, policy=None, level=None,
                         ref_id=None, reviewed=True):
        e = self._events[str(event_id)]
        self._events[str(event_id)] = dataclasses.replace(
            e, status=status,
            policy=policy or e.policy, level=level or e.level,
            ref_id=ref_id or e.ref_id,
        )
        return True

    def count_events(self, *, status=None):
        return len(self.list_events(status=status, limit=10_000))

    def add_experience(self, **kw):
        xid = self._id("exp")
        exp = Experience(
            id=xid, title=kw.get("title", ""), problem=kw.get("problem", ""),
            diagnosis=kw.get("diagnosis", ""), actions=kw.get("actions") or [],
            mistakes=kw.get("mistakes", ""), solution=kw.get("solution", ""),
            lessons=kw.get("lessons", ""), tags=kw.get("tags") or [],
            source_job_id=kw.get("source_job_id"), policy=kw.get("policy", "temporary"),
        )
        self._exps[xid] = exp
        return exp

    def get_experience(self, exp_id):
        return self._exps.get(str(exp_id))

    def list_experiences(self, *, limit=50):
        return [e for e in self._exps.values() if e.status == EXP_ACTIVE][:limit]

    def search_experiences(self, query, *, limit=5):
        q = query.lower()
        hits = [
            e for e in self._exps.values()
            if e.status == EXP_ACTIVE and (
                q in e.title.lower() or q in e.problem.lower()
                or q in e.solution.lower() or q in e.lessons.lower()
            )
        ]
        return hits[:limit]

    def set_experience_status(self, exp_id, status):
        e = self._exps[str(exp_id)]
        self._exps[str(exp_id)] = dataclasses.replace(e, status=status)
        return True

    def count_experiences(self):
        return len(self.list_experiences(limit=10_000))


@dataclasses.dataclass
class _FakeJob:
    id: str
    objective: str
    result: dict


@dataclasses.dataclass
class _FakeStep:
    intent: str
    status: str
    description: str = ""
    error: str | None = None
    blocked_reason: str | None = None


def _svc(**cfg):
    repo = FakeLearningRepo()
    return repo, LearningService(repo, LearningConfig(**cfg))


def _job_detail():
    job = _FakeJob(
        id="job-1", objective="Find the fastest sort for small arrays",
        result={"answer": "Insertion sort wins for n<16.",
                "report_sections": {"limitations": "single machine",
                                    "next_research": "test on ARM"}},
    )
    steps = [
        _FakeStep("web_search", "done", "search benchmarks"),
        _FakeStep("run_python", "done", "benchmark sorts"),
        _FakeStep("web_fetch", "blocked", "paywalled paper", blocked_reason="login"),
    ]
    return {"job": job, "steps": steps, "result": job.result}


# --- observing jobs (never silent) ---------------------------------------
def test_observe_job_proposes_only_by_default():
    repo, svc = _svc()
    out = svc.observe_job(_job_detail())
    assert out is not None
    assert out["applied"] is False
    events = repo.list_events()
    assert len(events) == 1
    assert events[0].status == EVENT_PROPOSED
    assert events[0].store == "experience"
    # nothing entered the store yet — Atlas never silently learns
    assert repo.count_experiences() == 0


def test_observe_disabled_returns_none():
    repo, svc = _svc(observe_jobs=False)
    assert svc.observe_job(_job_detail()) is None
    repo2, svc2 = _svc(enabled=False)
    assert svc2.observe_job(_job_detail()) is None


def test_observe_empty_objective_returns_none():
    repo, svc = _svc()
    detail = {"job": _FakeJob("j", "", {}), "steps": [], "result": {}}
    assert svc.observe_job(detail) is None


def test_auto_apply_promotes_immediately():
    repo, svc = _svc(auto_apply=True)
    out = svc.observe_job(_job_detail())
    assert out["applied"] is True
    assert repo.count_experiences() == 1


# --- apply / revert (governed & reversible) ------------------------------
def test_apply_creates_experience_and_marks_event():
    repo, svc = _svc()
    event = svc.observe_job(_job_detail())["event"]
    result = svc.apply(event["id"], policy="verified", level=2)
    assert result["applied"] is True
    applied = repo.get_event(event["id"])
    assert applied.status == EVENT_APPLIED
    assert applied.policy == "verified"
    assert applied.ref_id is not None
    exp = repo.get_experience(applied.ref_id)
    assert exp.problem.startswith("Find the fastest sort")
    assert "benchmark sorts" in exp.actions
    assert "paywalled paper" in exp.mistakes


def test_apply_rejects_unknown_policy():
    repo, svc = _svc()
    event = svc.observe_job(_job_detail())["event"]
    try:
        svc.apply(event["id"], policy="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_unknown_event_raises():
    repo, svc = _svc()
    try:
        svc.apply("nope")
        assert False
    except KeyError:
        pass


def test_revert_deactivates_experience():
    repo, svc = _svc(auto_apply=True)
    event = svc.observe_job(_job_detail())["event"]
    assert repo.count_experiences() == 1
    svc.revert(event["id"])
    reverted = repo.get_event(event["id"])
    assert reverted.status == EVENT_REVERTED
    assert repo.count_experiences() == 0  # record deactivated (reversible)


# --- explainable ---------------------------------------------------------
def test_explain_describes_what_why_where():
    repo, svc = _svc(auto_apply=True)
    event = svc.observe_job(_job_detail())["event"]
    data = svc.explain(event["id"])
    assert "explanation" in data
    assert "experience store" in data["explanation"]
    assert data["record"] is not None


# --- Experience store & recall -------------------------------------------
def test_remember_experience_is_applied():
    repo, svc = _svc()
    out = svc.remember_experience(
        title="pg lock", problem="deadlock on migrate",
        solution="add lock_timeout", lessons="run migrations serially",
    )
    assert out["applied"] is True
    assert repo.count_experiences() == 1


def test_recall_matches_lexically():
    repo, svc = _svc()
    svc.remember_experience(problem="deadlock on migrate", solution="lock_timeout")
    svc.remember_experience(problem="slow query", solution="add index")
    hits = svc.recall("deadlock")
    assert len(hits) == 1
    assert "deadlock" in hits[0]["problem"]


def test_recall_empty_query_lists_recent():
    repo, svc = _svc()
    svc.remember_experience(problem="a")
    svc.remember_experience(problem="b")
    assert len(svc.recall("")) == 2


# --- health --------------------------------------------------------------
def test_health_reports_counts():
    repo, svc = _svc(auto_apply=True)
    svc.observe_job(_job_detail())
    status = svc.health_check()
    assert status.healthy
    assert "experience" in status.detail


# --- store sinks (S19: promotion into other stores, governed) ------------
class _RecordingSink:
    def __init__(self):
        self.records = {}
        self._seq = 0
        self.reverted = []

    def apply(self, payload, *, policy=None):
        self._seq += 1
        rid = f"rec-{self._seq}"
        self.records[rid] = {"payload": payload, "policy": policy}
        return rid

    def revert(self, ref_id):
        self.reverted.append(ref_id)


def test_sink_routes_apply_and_revert_for_nonexperience_store():
    repo, svc = _svc()
    sink = _RecordingSink()
    svc.register_sink("code", sink)
    result = svc.propose(
        "repo", "code", summary="learn X", reason="r", origin="/x",
        payload={"name": "X"}, level=2, apply=True,
    )
    assert result["applied"] is True
    event = result["event"]
    assert event["store"] == "code"
    assert event["ref_id"] in sink.records
    # revert calls the sink
    svc.revert(event["id"])
    assert sink.reverted == [event["ref_id"]]


# --- pure extractor ------------------------------------------------------
def test_experience_from_job_partitions_actions_and_mistakes():
    payload = _experience_from_job(
        "objective",
        [_FakeStep("a", "done", "did a"),
         _FakeStep("b", "failed", "tried b", error="boom")],
        {"answer": "solved"},
        "job-x",
    )
    assert payload["actions"] == ["did a"]
    assert "tried b: boom" in payload["mistakes"]
    assert payload["solution"] == "solved"
