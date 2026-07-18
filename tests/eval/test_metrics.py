"""Unit tests for Stage 3B eval metric helpers."""

from __future__ import annotations

from atlas.eval.metrics import (
    citation_coverage,
    contradiction_recall,
    false_merge_rate,
    merge_accuracy,
    precision_at_k,
    recall_at_k,
)


def test_precision_and_recall_at_k():
    ranked = ["a", "x", "b", "y"]
    relevant = ["a", "b", "c"]
    assert precision_at_k(ranked, relevant, 3) == 2 / 3
    assert recall_at_k(ranked, relevant, 3) == 2 / 3
    assert recall_at_k(ranked, relevant, 4) == 2 / 3


def test_precision_empty_top_is_zero():
    assert precision_at_k([], ["a"], 5) == 0.0


def test_recall_no_relevant_is_one():
    assert recall_at_k(["a"], [], 5) == 1.0


def test_citation_coverage():
    assert citation_coverage(["a", "b"], ["a", "b", "c"]) == 2 / 3
    assert citation_coverage(["a", "b", "c"], ["a", "b"]) == 1.0


def test_merge_accuracy_and_false_merge_rate():
    gold = [["a", "b"], ["c"]]
    predicted = [["a", "b"], ["c"]]
    assert merge_accuracy(predicted, gold) == 1.0
    assert false_merge_rate(predicted, gold) == 0.0

    bad = [["a", "c"], ["b"]]
    assert merge_accuracy(bad, gold) == 0.0
    assert false_merge_rate(bad, gold) == 1.0


def test_contradiction_recall():
    assert contradiction_recall(["p3"], ["p3"]) == 1.0
    assert contradiction_recall([], ["p3"]) == 0.0
    assert contradiction_recall(["p3"], []) == 1.0
