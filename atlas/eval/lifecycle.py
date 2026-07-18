"""Lifecycle / freshness / provenance fixture scorers.

Production freshness policy lives in ``atlas.knowledge.lifecycle``; this module
scores fixtures against that oracle (D3B.16 / 3B.3).
"""

from __future__ import annotations

from typing import Any

from atlas.eval.metrics import citation_coverage, mean
from atlas.knowledge.lifecycle import freshness_label


def expected_freshness_label(
    *,
    knowledge_type: str,
    age_days: int,
    contradicted: bool = False,
) -> str:
    """Eval oracle — delegates to production policy."""
    return freshness_label(
        knowledge_type=knowledge_type,
        age_days=age_days,
        contradicted=contradicted,
    )


def score_freshness_case(case: dict[str, Any]) -> float:
    """1.0 if predicted/oracle label matches gold, else 0.0."""
    gold = str(case.get("gold_freshness", ""))
    predicted = case.get("predicted_freshness")
    if predicted is None:
        predicted = expected_freshness_label(
            knowledge_type=str(case.get("knowledge_type", "")),
            age_days=int(case.get("age_days", 0)),
            contradicted=bool(case.get("contradicted", False)),
        )
    return 1.0 if str(predicted) == gold else 0.0


def score_freshness_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [score_freshness_case(c) for c in cases]
    return {
        "n_cases": len(scores),
        "freshness_label_accuracy": mean(scores),
        "cases": [
            {"id": str(c.get("id", "")), "correct": score_freshness_case(c) == 1.0}
            for c in cases
        ],
    }


def score_supersession_case(case: dict[str, Any]) -> float:
    """Compare predicted transition to gold (create/revise/supersede/archive)."""
    gold = str(case.get("gold_transition", ""))
    predicted = str(case.get("predicted_transition", gold))
    return 1.0 if predicted == gold else 0.0


def score_supersession_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [score_supersession_case(c) for c in cases]
    return {
        "n_cases": len(scores),
        "supersession_correctness": mean(scores),
        "cases": [
            {
                "id": str(c.get("id", "")),
                "correct": score_supersession_case(c) == 1.0,
            }
            for c in cases
        ],
    }


def score_provenance_case(case: dict[str, Any]) -> float:
    """Citation/provenance completeness for a labeled entity."""
    present = list(case.get("present_ids", []) or case.get("present_fields", []) or [])
    required = list(case.get("required_ids", []) or case.get("required_fields", []) or [])
    return citation_coverage(present, required)


def score_provenance_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [score_provenance_case(c) for c in cases]
    return {
        "n_cases": len(scores),
        "provenance_completeness": mean(scores),
        "citation_coverage": mean(scores),
        "cases": [
            {"id": str(c.get("id", "")), "score": score_provenance_case(c)}
            for c in cases
        ],
    }
