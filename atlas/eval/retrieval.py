"""Score ranked retrieval lists against labeled relevance fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from atlas.eval.metrics import mean, precision_at_k, recall_at_k


@dataclass(frozen=True, slots=True)
class RetrievalCaseScore:
    case_id: str
    k: int
    precision_at_k: float
    recall_at_k: float


RetrieverFn = Callable[[str, int], Sequence[str]]


def score_retrieval_case(
    case: dict[str, Any],
    *,
    ranked_ids: Sequence[str] | None = None,
) -> RetrievalCaseScore:
    """Score one retrieval case using provided or fixture ``ranked_ids``."""
    ranking = list(ranked_ids if ranked_ids is not None else case.get("ranked_ids", []))
    relevant = list(case.get("relevant_ids", []))
    k = int(case.get("k", 5))
    return RetrievalCaseScore(
        case_id=str(case.get("id", "")),
        k=k,
        precision_at_k=precision_at_k(ranking, relevant, k),
        recall_at_k=recall_at_k(ranking, relevant, k),
    )


def score_retrieval_corpus(
    cases: list[dict[str, Any]],
    *,
    retriever: RetrieverFn | None = None,
) -> dict[str, Any]:
    """Aggregate precision/recall over a corpus.

    If ``retriever`` is provided it is called as ``retriever(query, k) -> ranked_ids``.
    Otherwise each case must include a hermetic ``ranked_ids`` list (baseline harness).
    """
    scores: list[RetrievalCaseScore] = []
    for case in cases:
        ranking: Sequence[str] | None = None
        if retriever is not None:
            query = str(case.get("query", ""))
            k = int(case.get("k", 5))
            ranking = list(retriever(query, k))
        scores.append(score_retrieval_case(case, ranked_ids=ranking))

    return {
        "n_cases": len(scores),
        "precision_at_k": mean([s.precision_at_k for s in scores]),
        "recall_at_k": mean([s.recall_at_k for s in scores]),
        "cases": [
            {
                "id": s.case_id,
                "k": s.k,
                "precision_at_k": s.precision_at_k,
                "recall_at_k": s.recall_at_k,
            }
            for s in scores
        ],
    }
