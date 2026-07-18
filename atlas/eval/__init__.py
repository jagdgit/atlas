"""Stage 3B evaluation harness — metrics, fixtures, baselines, Benchmark Set.

Hermetic by default (labeled fixtures + deterministic scorers). Live
``KnowledgeService.search`` baselines are optional and skip when the stack is down.
"""

from __future__ import annotations

from atlas.eval.baseline import BaselineReport, run_baseline_suite
from atlas.eval.benchmark import BenchmarkProblem, load_benchmark_set
from atlas.eval.contracts import METRIC_CONTRACTS, MetricContract
from atlas.eval.metrics import (
    citation_coverage,
    contradiction_recall,
    false_merge_rate,
    merge_accuracy,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    "BaselineReport",
    "BenchmarkProblem",
    "METRIC_CONTRACTS",
    "MetricContract",
    "citation_coverage",
    "contradiction_recall",
    "false_merge_rate",
    "load_benchmark_set",
    "merge_accuracy",
    "precision_at_k",
    "recall_at_k",
    "run_baseline_suite",
]
