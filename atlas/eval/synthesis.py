"""Score ``group_claims`` against labeled synthesis fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from atlas.eval.metrics import contradiction_recall, false_merge_rate, mean, merge_accuracy
from atlas.evidence.models import Claim
from atlas.research.grouping import group_claims


@dataclass(frozen=True, slots=True)
class SynthesisCaseScore:
    case_id: str
    merge_accuracy: float
    false_merge_rate: float
    contradiction_recall: float
    predicted_group_count: int
    expected_group_count: int


def _claim_from_case(raw: dict[str, Any]) -> Claim:
    return Claim.from_dict(raw)


def _clusters_from_grouped(grouped: Iterable[Claim]) -> list[frozenset[str]]:
    """Cluster key = set of evidence source_ids on each merged claim."""
    return [frozenset(e.source_id for e in claim.evidence) for claim in grouped]


def score_synthesis_case(case: dict[str, Any]) -> SynthesisCaseScore:
    """Run ``group_claims`` on a labeled case and score merge/contradiction metrics."""
    claims = [_claim_from_case(c) for c in case.get("claims", [])]
    grouped = group_claims(claims)
    predicted = _clusters_from_grouped(grouped)

    gold_clusters = [frozenset(c) for c in case.get("gold_clusters", [])]
    gold_contradict = set(case.get("gold_contradict_sources", []) or [])

    predicted_contradict: set[str] = set()
    for claim in grouped:
        predicted_contradict.update(e.source_id for e in claim.contradicting)

    expected_count = int(case.get("expected_group_count", len(gold_clusters)))
    return SynthesisCaseScore(
        case_id=str(case.get("id", "")),
        merge_accuracy=merge_accuracy(predicted, gold_clusters),
        false_merge_rate=false_merge_rate(predicted, gold_clusters),
        contradiction_recall=contradiction_recall(predicted_contradict, gold_contradict),
        predicted_group_count=len(grouped),
        expected_group_count=expected_count,
    )


def score_synthesis_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate synthesis metrics over a corpus of cases."""
    scores = [score_synthesis_case(case) for case in cases]
    return {
        "n_cases": len(scores),
        "merge_accuracy": mean([s.merge_accuracy for s in scores]),
        "false_merge_rate": mean([s.false_merge_rate for s in scores]),
        "contradiction_recall": mean([s.contradiction_recall for s in scores]),
        "group_count_match_rate": mean(
            [
                1.0 if s.predicted_group_count == s.expected_group_count else 0.0
                for s in scores
            ]
        ),
        "cases": [
            {
                "id": s.case_id,
                "merge_accuracy": s.merge_accuracy,
                "false_merge_rate": s.false_merge_rate,
                "contradiction_recall": s.contradiction_recall,
                "predicted_group_count": s.predicted_group_count,
                "expected_group_count": s.expected_group_count,
            }
            for s in scores
        ],
    }
