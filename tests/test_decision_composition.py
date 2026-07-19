"""D.2 — Intelligence + Policy composition tests (Phase D · §D.2).

Proves the engine composes the intelligences into a decision: a rule pulls **engineering findings**
and the **personal profile** through the injected :class:`IntelligenceContext`, and the resulting
`Decision` carries real ``knowledge_refs``/``experience_refs``; a `prefer` policy verifiably arbitrates
between equally-scored options and is named in the explanation; the decision is complete with the LLM
off; and a rule reaching for an **unavailable** intelligence yields an honest ``capability_gap`` (P15).
All intelligences are stubbed — no DB, no network.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from atlas.decision import (
    ACTION_CAPABILITY_GAP,
    ACTION_RECOMMEND,
    Decision,
    DecisionEngine,
    DecisionRequest,
    DecisionRuleRegistry,
    ScoredOption,
)


class _FakeRepo:
    def record(self, decision: Decision) -> dict:
        return {"id": uuid.uuid4(), "created_at": datetime.now(timezone.utc)}


class _StubEngineering:
    """Minimal engineering intelligence: findings keyed by claim, plus a skill-shaped recommend."""

    def __init__(self, findings):
        self._findings = findings

    def list_findings(self, **kwargs):
        return list(self._findings)

    def recommend(self, context="", *, limit=None):
        return {"recommendations": []}

    def search(self, query, *, limit=20):
        return []


class _StubPersonal:
    def __init__(self, skills):
        self._skills = skills

    def profile(self, *, include_inferred=True):
        return {"skills": self._skills}

    def skills(self, *, include_inferred=True):
        return list(self._skills)


class _StubPolicy:
    def __init__(self, influences):
        self._influences = influences

    def advice_influence(self, *, scope=None):
        return list(self._influences)

    retrieval_influence = advice_influence


class _CompositionRule:
    """Turns each engineering finding into an option, tagged with the owner's skills; deterministic."""

    mission_type = "demo"
    VERSION = "1.0.0"

    def score(self, request, context) -> list[ScoredOption]:
        findings = context.findings(limit=10)
        skills = {s["key"] for s in context.profile().get("skills", [])}
        options: list[ScoredOption] = []
        for f in findings:
            tag = f["topic"]
            options.append(
                ScoredOption(
                    key=f["topic"],
                    score=float(f.get("confidence_score", 0.5)),
                    tags=(tag,),
                    text=f["topic"],
                    rationale=f"from finding {f['id']}",
                    knowledge_refs=[f["id"]],
                    experience_refs=[k for k in skills if k == tag],
                )
            )
        return options


class _NeedsResearchRule:
    mission_type = "demo"
    VERSION = "1.0.0"

    def score(self, request, context) -> list[ScoredOption]:
        context.research("anything")  # research intelligence is not wired → CapabilityGap (P15)
        return []


def _engine(rule, *, engineering=None, personal=None, policy=None, narrator="__none__"):
    reg = DecisionRuleRegistry()
    reg.register(rule)
    kw = {}
    if narrator != "__none__":
        kw["narrator"] = narrator
    return DecisionEngine(
        _FakeRepo(), rules=reg, engineering=engineering, personal=personal, policy=policy, **kw
    )


def _req():
    return DecisionRequest(mission_id="m1", mission_type="demo", config_version=1)


def test_decision_carries_findings_and_profile_refs():
    eng = _StubEngineering([
        {"id": "F-1", "topic": "redis", "confidence_score": 0.8},
        {"id": "F-2", "topic": "celery", "confidence_score": 0.3},
    ])
    personal = _StubPersonal([{"key": "redis"}, {"key": "python"}])
    engine = _engine(_CompositionRule(), engineering=eng, personal=personal)

    d = engine.decide(_req())
    assert d.action_kind == ACTION_RECOMMEND
    assert d.action["key"] == "redis"                       # higher-confidence finding wins
    assert d.knowledge_refs == ["F-1"]                       # sourced from engineering findings
    assert d.experience_refs == ["redis"]                    # corroborated by the owner's skills
    assert d.alternatives_rejected[0]["key"] == "celery"


def test_policy_prefer_arbitrates_between_equal_findings():
    # Two equally-confident findings; a policy preferring "celery" must flip the choice.
    eng = _StubEngineering([
        {"id": "F-1", "topic": "redis", "confidence_score": 0.5},
        {"id": "F-2", "topic": "celery", "confidence_score": 0.5},
    ])
    personal = _StubPersonal([])
    policy = _StubPolicy([{"id": "P-9", "rule": "prefer", "terms": ["celery"], "weight": 0.2}])
    engine = _engine(_CompositionRule(), engineering=eng, personal=personal, policy=policy)

    d = engine.decide(_req())
    assert d.action["key"] == "celery"
    assert d.policy_ids == ["P-9"]
    assert "P-9" in d.why                                     # arbitration is explained (P9)


def test_complete_decision_with_llm_off():
    eng = _StubEngineering([{"id": "F-1", "topic": "redis", "confidence_score": 0.9}])
    engine = _engine(_CompositionRule(), engineering=eng, personal=_StubPersonal([]))  # no narrator
    d = engine.decide(_req())
    assert d.why and "redis" in d.why                        # deterministic prose, no LLM
    assert d.confidence in ("high", "medium", "low")


def test_missing_intelligence_yields_capability_gap():
    # Rule needs research, which isn't wired → honest capability gap, not a crash.
    engine = _engine(_NeedsResearchRule(), engineering=_StubEngineering([]))
    d = engine.decide(_req())
    assert d.action_kind == ACTION_CAPABILITY_GAP
    assert d.action["capability"] == "intelligence:research"


def test_rule_using_absent_engineering_is_a_gap():
    # The composition rule calls context.findings() but engineering is not provided.
    engine = _engine(_CompositionRule(), engineering=None, personal=_StubPersonal([]))
    d = engine.decide(_req())
    assert d.action_kind == ACTION_CAPABILITY_GAP
    assert d.action["capability"] == "intelligence:engineering"
