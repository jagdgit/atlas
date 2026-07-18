"""Named metric contracts for Stage 3B evaluation gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricContract:
    """A measurable eval contract — name, family, and what a gate means."""

    id: str
    family: str  # retrieval | grounding | synthesis | lifecycle | end_to_end
    summary: str
    higher_is_better: bool = True
    unit: str = "ratio"  # ratio | count | days | label


METRIC_CONTRACTS: dict[str, MetricContract] = {
    "precision_at_k": MetricContract(
        "precision_at_k",
        "retrieval",
        "Fraction of top-k retrieved items that are labeled relevant.",
    ),
    "recall_at_k": MetricContract(
        "recall_at_k",
        "retrieval",
        "Fraction of labeled relevant items recovered in top-k.",
    ),
    "citation_coverage": MetricContract(
        "citation_coverage",
        "grounding",
        "Fraction of required citation/provenance ids present in an answer.",
    ),
    "merge_accuracy": MetricContract(
        "merge_accuracy",
        "synthesis",
        "Fraction of gold claim clusters recovered exactly after grouping.",
    ),
    "false_merge_rate": MetricContract(
        "false_merge_rate",
        "synthesis",
        "Fraction of predicted multi-member merges that are not gold clusters.",
        higher_is_better=False,
    ),
    "contradiction_recall": MetricContract(
        "contradiction_recall",
        "synthesis",
        "Fraction of gold contradicting sources recovered on merged claims.",
    ),
    "freshness_label_accuracy": MetricContract(
        "freshness_label_accuracy",
        "lifecycle",
        "Fraction of freshness policy cases labeled correctly.",
    ),
    "supersession_correctness": MetricContract(
        "supersession_correctness",
        "lifecycle",
        "Fraction of supersede/archive transitions matching gold labels.",
    ),
    "provenance_completeness": MetricContract(
        "provenance_completeness",
        "grounding",
        "Fraction of required provenance parent fields present on an entity.",
    ),
    "benchmark_pass_rate": MetricContract(
        "benchmark_pass_rate",
        "end_to_end",
        "Fraction of Atlas Benchmark Set problems meeting acceptance notes.",
    ),
}
