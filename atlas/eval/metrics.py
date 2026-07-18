"""Deterministic metric helpers for Stage 3B evaluation (D3B.22 / D3B.23).

No LLM-as-judge here — labeled fixtures and operator review are authoritative.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of the top-``k`` ranked ids that are relevant."""
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    top = list(ranked_ids)[:k]
    if not top:
        return 0.0
    hits = sum(1 for item in top if item in relevant)
    return hits / len(top)


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of all relevant ids recovered in the top-``k``."""
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    top = set(list(ranked_ids)[:k])
    return len(relevant & top) / len(relevant)


def citation_coverage(
    cited_ids: Iterable[str], required_ids: Iterable[str]
) -> float:
    """Fraction of required provenance/citation ids present in the citation set."""
    required = set(required_ids)
    if not required:
        return 1.0
    cited = set(cited_ids)
    return len(required & cited) / len(required)


def merge_accuracy(
    predicted_clusters: Iterable[Iterable[str]],
    gold_clusters: Iterable[Iterable[str]],
) -> float:
    """Exact-set recovery: fraction of gold clusters present in predictions."""
    gold = {frozenset(c) for c in gold_clusters if c}
    if not gold:
        return 1.0
    predicted = {frozenset(c) for c in predicted_clusters if c}
    return len(gold & predicted) / len(gold)


def false_merge_rate(
    predicted_clusters: Iterable[Iterable[str]],
    gold_clusters: Iterable[Iterable[str]],
) -> float:
    """Fraction of predicted multi-member clusters that are not exact gold matches.

    Singleton predictions are ignored (they cannot be false merges).
    """
    gold = {frozenset(c) for c in gold_clusters if c}
    predicted_multi = [frozenset(c) for c in predicted_clusters if len(frozenset(c)) > 1]
    if not predicted_multi:
        return 0.0
    false = sum(1 for c in predicted_multi if c not in gold)
    return false / len(predicted_multi)


def contradiction_recall(
    predicted_contradict_ids: Iterable[str],
    gold_contradict_ids: Iterable[str],
) -> float:
    """Fraction of gold contradicting source/claim ids recovered."""
    gold = set(gold_contradict_ids)
    if not gold:
        return 1.0
    predicted = set(predicted_contradict_ids)
    return len(gold & predicted) / len(gold)


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; empty → 0.0."""
    if not values:
        return 0.0
    return sum(values) / len(values)
