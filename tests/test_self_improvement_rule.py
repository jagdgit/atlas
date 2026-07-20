"""Hermetic tests for self-improvement analysis + decision rule (Phase D · §D.10)."""

from __future__ import annotations

from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import DecisionRequest
from atlas.improvement.analyze import analyze_baseline, flatten_metrics
from atlas.improvement.decision_rule import SelfImprovementDecisionRule

RULE = SelfImprovementDecisionRule()
CTX = IntelligenceContext()


def test_flatten_and_analyze_floor_and_regression():
    sections = {
        "retrieval_hermetic": {"precision_at_k": 0.3, "recall_at_k": 0.8, "n_cases": 5},
        "notes": {"x": "ignore"},
    }
    metrics = flatten_metrics(sections)
    assert metrics["retrieval_hermetic.precision_at_k"] == 0.3
    assert "notes.x" not in metrics

    findings = analyze_baseline(
        metrics,
        previous={"retrieval_hermetic.precision_at_k": 0.9, "retrieval_hermetic.recall_at_k": 0.8},
        floors={"retrieval_hermetic.precision_at_k": 0.5},
        regression_drop=0.05,
    )
    kinds = {f["kind"] for f in findings}
    assert "below_floor" in kinds
    assert "regression" in kinds


def test_rule_holds_when_healthy():
    opts = RULE.score(
        DecisionRequest(mission_id="m", mission_type="self_improvement", context={"findings": []}),
        CTX,
    )
    assert len(opts) == 1 and opts[0].key == "hold"


def test_rule_proposes_gated_fix():
    finding = {
        "id": "regression:retrieval_hermetic.precision_at_k",
        "metric": "retrieval_hermetic.precision_at_k",
        "kind": "regression",
        "severity": "high",
        "current": 0.4,
        "previous": 0.9,
        "floor": 0.5,
    }
    opts = RULE.score(
        DecisionRequest(
            mission_id="m",
            mission_type="self_improvement",
            context={"findings": [finding], "gate_fixes": True},
        ),
        CTX,
    )
    keys = {o.key.split(":")[0] for o in opts}
    assert "investigate" in keys and "propose_fix" in keys and "hold" in keys
    fix = next(o for o in opts if o.key.startswith("propose_fix"))
    assert fix.side_effecting is True
    assert fix.score > next(o for o in opts if o.key == "hold").score
