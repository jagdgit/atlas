"""Hermetic tests for the Decision Engine skeleton (Phase D · §D.1).

Covers the deterministic choice + full P9 record, the two honesty outcomes (``hold`` and the P15
``capability_gap``), policy arbitration (DD5), the side-effecting → approval flag (P14), and the
LLM narrator seam with deterministic fallback (CC-D1). No DB — a fake repo captures what was recorded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from atlas.decision import (
    ACTION_CAPABILITY_GAP,
    ACTION_HOLD,
    ACTION_RECOMMEND,
    CapabilityGap,
    Decision,
    DecisionEngine,
    DecisionRequest,
    DecisionRuleRegistry,
    ScoredOption,
    apply_policy_influence,
    derive_confidence,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.recorded: list[Decision] = []

    def record(self, decision: Decision) -> dict:
        self.recorded.append(decision)
        return {"id": uuid.uuid4(), "created_at": datetime.now(timezone.utc)}


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, *, source: str | None = None) -> None:
        self.emitted.append((event_type, payload))


class _TwoOptionRule:
    mission_type = "demo"
    VERSION = "1.0.0"

    def __init__(self, a_score: float = 0.9, b_score: float = 0.2, side_effecting: bool = False):
        self._a, self._b, self._side = a_score, b_score, side_effecting

    def score(self, request: DecisionRequest, context) -> list[ScoredOption]:
        return [
            ScoredOption(key="alpha", score=self._a, tags=("momentum",), rationale="strong signal",
                         knowledge_refs=["k1"], side_effecting=self._side, payload={"n": 1}),
            ScoredOption(key="beta", score=self._b, tags=("index",), rationale="weak signal"),
        ]


class _EmptyRule:
    mission_type = "demo"
    VERSION = "1.0.0"

    def score(self, request: DecisionRequest, context) -> list[ScoredOption]:
        return []


class _GapRule:
    mission_type = "demo"
    VERSION = "1.0.0"

    def score(self, request: DecisionRequest, context) -> list[ScoredOption]:
        raise CapabilityGap("market_data:NASDAQ", "no data source adapter configured")


def _engine(rule=None, *, policy=None, narrator=None):
    reg = DecisionRuleRegistry()
    if rule is not None:
        reg.register(rule)
    repo = _FakeRepo()
    events = _FakeEvents()
    engine = DecisionEngine(repo, rules=reg, policy=policy, narrator=narrator, events=events)
    return engine, repo, events


def _req(**ctx):
    return DecisionRequest(mission_id="m1", mission_type="demo", config_version=3, context=ctx)


def test_decide_picks_top_option_and_records_full_p9_record():
    engine, repo, events = _engine(_TwoOptionRule())
    d = engine.decide(_req())

    assert d.action_kind == ACTION_RECOMMEND
    assert d.action["key"] == "alpha"                      # higher score wins
    assert d.action["payload"] == {"n": 1}
    # Full P9 record.
    assert d.decision_rule == "demo" and d.rule_version == "1.0.0"
    assert d.config_version == 3
    assert d.knowledge_refs == ["k1"]
    assert d.model_versions["decision_engine"] == DecisionEngine.VERSION
    assert d.confidence in ("high", "medium", "low")
    assert len(d.alternatives_rejected) == 1 and d.alternatives_rejected[0]["key"] == "beta"
    assert d.why  # non-empty rationale
    # Persisted + announced.
    assert repo.recorded and repo.recorded[0] is d
    assert d.id is not None and d.created_at is not None
    assert events.emitted and events.emitted[0][0] == "DecisionMade"


def test_confidence_high_on_wide_margin_low_on_tie():
    hi_label, hi = derive_confidence([0.95, 0.05])
    lo_label, lo = derive_confidence([0.5, 0.49])
    assert hi > lo
    assert hi_label == "high"
    assert lo_label in ("low", "medium")
    # A lone option is unopposed → full confidence.
    assert derive_confidence([0.3]) == ("high", 1.0)
    assert derive_confidence([]) == ("low", 0.0)


def test_no_registered_rule_yields_capability_gap_not_error():
    engine, repo, events = _engine(None)  # empty registry
    d = engine.decide(_req())
    assert d.action_kind == ACTION_CAPABILITY_GAP
    assert d.action["capability"] == "decision_rule:demo"
    assert "no decision rule" in d.action["detail"]
    assert d.confidence == "low"
    assert not d.requires_approval
    assert events.emitted[0][0] == "DecisionCapabilityGap"


def test_rule_capability_gap_is_recorded_with_missing_name():
    engine, repo, events = _engine(_GapRule())
    d = engine.decide(_req())
    assert d.action_kind == ACTION_CAPABILITY_GAP
    assert d.action["capability"] == "market_data:NASDAQ"
    assert "no data source adapter" in d.action["detail"]
    assert d.decision_rule == "demo"  # attributed to the rule that reported the gap
    assert events.emitted[0][0] == "DecisionCapabilityGap"


def test_empty_options_holds():
    engine, repo, events = _engine(_EmptyRule())
    d = engine.decide(_req())
    assert d.action_kind == ACTION_HOLD
    assert d.action == {"kind": ACTION_HOLD}
    assert events.emitted[0][0] == "DecisionHold"


def test_side_effecting_option_requires_approval():
    engine, _, _ = _engine(_TwoOptionRule(side_effecting=True))
    d = engine.decide(_req())
    assert d.requires_approval is True


def test_policy_influence_reorders_and_is_explained():
    # Equal base scores; a policy preferring "index" must lift beta above alpha.
    class _EqualRule:
        mission_type = "demo"
        VERSION = "1.0.0"

        def score(self, request, context):
            return [
                ScoredOption(key="alpha", score=0.5, tags=("momentum",)),
                ScoredOption(key="beta", score=0.5, tags=("index",)),
            ]

    class _Policy:
        def advice_influence(self, *, scope=None):
            return [{"id": "P-1", "rule": "prefer", "terms": ["index"], "weight": 0.2}]

    engine, _, _ = _engine(_EqualRule(), policy=_Policy())
    d = engine.decide(_req())
    assert d.action["key"] == "beta"
    assert d.policy_ids == ["P-1"]
    assert "P-1" in d.why


def test_narrator_used_and_falls_back_to_deterministic():
    class _Narrator:
        def narrate(self, decision_dict, *, fallback):
            return "polished narrative"

    class _BadNarrator:
        def narrate(self, decision_dict, *, fallback):
            raise RuntimeError("llm down")

    engine, _, _ = _engine(_TwoOptionRule(), narrator=_Narrator())
    assert engine.decide(_req()).why == "polished narrative"

    engine2, _, _ = _engine(_TwoOptionRule(), narrator=_BadNarrator())
    why = engine2.decide(_req()).why
    assert "polished" not in why and "alpha" in why  # deterministic fallback


def test_apply_policy_influence_helper_signs_and_records_ids():
    opts = [
        ScoredOption(key="crypto note", score=0.4, tags=("crypto",)),
        ScoredOption(key="bond note", score=0.4, tags=("bonds",)),
    ]
    infl = [
        {"id": "A", "terms": ["crypto"], "weight": -0.1},
        {"id": "B", "terms": ["bonds"], "weight": 0.1},
    ]
    apply_policy_influence(opts, infl)
    crypto, bond = opts
    assert crypto.policy_boost == pytest.approx(-0.1) and crypto.policy_ids == ("A",)
    assert bond.policy_boost == pytest.approx(0.1) and bond.policy_ids == ("B",)
    assert bond.final_score > crypto.final_score
