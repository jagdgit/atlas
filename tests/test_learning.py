"""Hermetic tests for the Learning Pipeline (S18b, D11/§5d).

A small in-memory ``FakeLearningRepo`` stands in for the SQL repository so the
service's governance behaviour (propose → apply → revert, never silent, reversible,
explainable, recall) is exercised without a database.
"""

from __future__ import annotations

import dataclasses
from typing import Any

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
from atlas.knowledge.access import RankedHit, heuristic_rerank
from atlas.services.learning_service import SOFT_BIAS_BOOST


class FakeLearningRepo:
    def __init__(self):
        self._events: dict[str, LearningEvent] = {}
        self._exps: dict[str, Experience] = {}
        self._comps: dict[str, Any] = {}
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
            payload=kw.get("payload") or {},
            bias_enabled=bool(kw.get("bias_enabled", False)),
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
                or q in str(e.payload or {}).lower()
            )
        ]
        return hits[:limit]

    def set_experience_status(self, exp_id, status):
        e = self._exps[str(exp_id)]
        self._exps[str(exp_id)] = dataclasses.replace(e, status=status)
        return True

    def set_bias_enabled(self, exp_id, enabled):
        e = self._exps.get(str(exp_id))
        if e is None or e.status != EXP_ACTIVE:
            return False
        self._exps[str(exp_id)] = dataclasses.replace(e, bias_enabled=bool(enabled))
        return True

    def list_bias_enabled(self, *, limit=50):
        return [
            e for e in self._exps.values()
            if e.status == EXP_ACTIVE and e.bias_enabled
        ][:limit]

    def count_experiences(self):
        return len(self.list_experiences(limit=10_000))

    def add_component_observation(self, **kw):
        oid = self._id("comp")
        from atlas.models.learning import ComponentObservation

        obs = ComponentObservation(
            id=oid,
            component_key=kw["component_key"],
            component_version=str(kw.get("component_version") or "1"),
            corpus=kw.get("corpus"),
            profile=kw.get("profile"),
            metrics=kw.get("metrics") or {},
            source_job_id=kw.get("source_job_id"),
            experience_id=kw.get("experience_id"),
            event_id=kw.get("event_id"),
        )
        self._comps[oid] = obs
        return obs

    def list_component_observations(self, *, component_key=None, limit=50):
        out = list(self._comps.values())
        if component_key:
            out = [o for o in out if o.component_key == component_key]
        return out[:limit]


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
    result: dict | None = None


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


# --- Stage 3B.5: rich experience + components + advice + gated bias ------
def test_experience_from_job_captures_rich_research_signals():
    steps = [
        _FakeStep(
            "research",
            "done",
            "deep research",
            result={
                "pipeline": {
                    "rounds": 2, "acquired": 3, "verified": 4, "findings": 2,
                    "patterns": 1, "hypotheses": 1,
                },
                "blocked": [{"url": "https://paywall.example", "reason": "login"}],
                "recommendations": [{"title": "Try open-access preprint", "why": "paywall"}],
                "readers": ["html", "pdf_ocr"],
                "usage": {
                    "research_elapsed_seconds": 12.5,
                    "verified_claims": 4,
                    "verified_claims_per_hour": 1152.0,
                },
            },
        ),
    ]
    payload = _experience_from_job(
        "soiling loss rates",
        steps,
        {"answer": "≈0.3%/day", "usage": steps[0].result["usage"]},
        "job-rich",
    )
    assert payload is not None
    assert "html" in payload["readers"]
    assert payload["paywalls"]
    assert payload["timings"]["research_elapsed_seconds"] == 12.5
    assert payload["strategies"]["rounds"] == 2
    assert payload["recommendations"]
    keys = {c["component_key"] for c in payload["component_observations"]}
    assert "reader:html" in keys
    assert "reader:ocr" in keys
    assert "retrieval:hybrid" in keys
    assert "synthesizer:v1" in keys


def test_apply_persists_payload_and_component_observations():
    repo, svc = _svc()
    detail = _job_detail()
    detail["job"].result = {
        **detail["job"].result,
        "pipeline": {"rounds": 1, "verified": 2, "findings": 1},
        "readers": ["html"],
        "blocked": [{"url": "x", "reason": "paywall"}],
        "recommendations": [{"title": "prefer OA"}],
        "usage": {"research_elapsed_seconds": 3.0},
    }
    event = svc.observe_job(detail)["event"]
    meta = repo.get_event(event["id"]).metadata["payload"]
    assert meta["readers"] == ["html"]
    assert meta["component_observations"]

    applied = svc.apply(event["id"])
    exp = repo.get_experience(applied["event"]["ref_id"])
    assert exp.payload.get("readers") == ["html"]
    assert exp.bias_enabled is False
    comps = svc.list_component_observations()
    assert any(c["component_key"] == "reader:html" for c in comps)


def test_advice_for_is_non_mutating():
    repo, svc = _svc()
    svc.remember_experience(
        problem="deadlock on migrate",
        solution="add lock_timeout",
        lessons="run migrations serially",
    )
    advice = svc.advice_for("deadlock")
    assert advice["mutating"] is False
    assert advice["count"] == 1
    assert "lock_timeout" in advice["advice"] or "serially" in advice["advice"]
    # No soft bias terms until explicitly enabled.
    assert svc.soft_bias_terms() == []


def test_soft_bias_requires_apply_then_enable():
    repo, svc = _svc()
    out = svc.observe_job(_job_detail())
    assert out["applied"] is False
    assert svc.soft_bias_terms() == []

    applied = svc.apply(out["event"]["id"])
    exp_id = applied["event"]["ref_id"]
    assert svc.soft_bias_terms() == []  # apply alone is not enough

    enabled = svc.enable_bias(exp_id, enabled=True)
    assert enabled["bias_enabled"] is True
    terms = svc.soft_bias_terms()
    assert terms  # now present

    # Soft bias only boosts; never drops hits.
    hits = [
        RankedHit("c1", "d1", 0, "unrelated text about cats", rrf_score=0.1, score=0.1),
        RankedHit(
            "c2", "d2", 0, "Find the fastest sort for small arrays",
            rrf_score=0.1, score=0.1,
        ),
    ]
    ranked = heuristic_rerank(hits, "sort", soft_bias_terms=terms, soft_bias_boost=SOFT_BIAS_BOOST)
    assert len(ranked) == 2
    assert ranked[0].chunk_id == "c2"


def test_knowledge_retrieve_loads_soft_bias_from_learning():
    """Production path: KnowledgeService.retrieve pulls bias terms from learning."""
    from atlas.knowledge.access import RankedContext, RankedHit, TIER_KNOWLEDGE
    from atlas.knowledge.service import KnowledgeService

    class _EmptyEmb:
        def search(self, *a, **k):
            return []

    class _EmptyChunks:
        def search_lexical(self, *a, **k):
            return []

    class _FakeLLM:
        def embed(self, texts, model=None):
            class R:
                vectors = [[0.0] * 3 for _ in texts]
            return R()

    repo, learning = _svc(auto_apply=True)
    evt = learning.observe_job(_job_detail())["event"]
    learning.enable_bias(evt["ref_id"], enabled=True)
    assert learning.soft_bias_terms()

    ks = KnowledgeService(
        documents=None,  # unused
        chunks=_EmptyChunks(),
        embeddings=_EmptyEmb(),
        llm=_FakeLLM(),
        embedding_model="fake",
        learning=learning,
    )
    # Inject empty dense path by monkeypatching retrieve internals via mode lexical
    # with no rows → empty hits, but soft_bias_term_count should still be recorded.
    ranked = ks.retrieve("sort", role="chat", mode="lexical", k=3)
    assert isinstance(ranked, RankedContext)
    assert ranked.meta.get("soft_bias_term_count", 0) > 0


def test_enable_bias_rejects_inactive():
    repo, svc = _svc(auto_apply=True)
    evt = svc.observe_job(_job_detail())["event"]
    exp_id = evt["ref_id"]
    svc.revert(evt["id"])
    try:
        svc.enable_bias(exp_id)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_observe_still_proposes_only_with_rich_payload():
    """Hard boundary: rich extraction must not flip auto-apply on."""
    repo, svc = _svc()  # auto_apply=False
    detail = _job_detail()
    detail["job"].result["pipeline"] = {"rounds": 1, "findings": 1}
    detail["job"].result["readers"] = ["html"]
    out = svc.observe_job(detail)
    assert out["applied"] is False
    assert repo.count_experiences() == 0
    assert "readers" in repo.get_event(out["event"]["id"]).metadata["payload"]

