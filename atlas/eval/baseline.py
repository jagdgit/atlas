"""Run the Stage 3B.0 hermetic baseline suite and return a versioned report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.eval.benchmark import benchmark_snapshot
from atlas.eval.fixtures import load_cases
from atlas.eval.lifecycle import (
    score_freshness_corpus,
    score_provenance_corpus,
    score_supersession_corpus,
)
from atlas.eval.retrieval import score_retrieval_corpus
from atlas.eval.synthesis import score_synthesis_corpus

BASELINE_MILESTONE = "3B.0"
BASELINE_VERSION = "3B.0-hermetic-v1"


@dataclass
class BaselineReport:
    """Versioned baseline capture for regression gates."""

    milestone: str = BASELINE_MILESTONE
    version: str = BASELINE_VERSION
    captured_at: str = ""
    sections: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "milestone": self.milestone,
            "version": self.version,
            "captured_at": self.captured_at,
            "sections": self.sections,
        }


def run_baseline_suite(*, root: Path | None = None) -> BaselineReport:
    """Execute all hermetic corpora against current algorithms (dense ranks + group_claims)."""
    retrieval = score_retrieval_corpus(load_cases("retrieval_relevant.json", root=root))
    duplicates = score_synthesis_corpus(
        load_cases("synthesis_duplicates.json", root=root)
    )
    contradictions = score_synthesis_corpus(
        load_cases("synthesis_contradictions.json", root=root)
    )
    freshness = score_freshness_corpus(load_cases("freshness_cases.json", root=root))
    # supersession cases live alongside freshness in the same file under key via second file
    supersession = score_supersession_corpus(
        load_cases("supersession_cases.json", root=root)
    )
    provenance = score_provenance_corpus(load_cases("provenance_cases.json", root=root))
    benchmark = benchmark_snapshot(milestone=BASELINE_MILESTONE, root=root)

    return BaselineReport(
        milestone=BASELINE_MILESTONE,
        version=BASELINE_VERSION,
        captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections={
            "retrieval_hermetic": retrieval,
            "synthesis_duplicates": duplicates,
            "synthesis_contradictions": contradictions,
            "freshness": freshness,
            "supersession": supersession,
            "provenance": provenance,
            "benchmark_set": benchmark,
            "notes": {
                "retrieval": (
                    "Hermetic ranked_ids capture metric harness + labeled relevance; "
                    "live KnowledgeService.search baseline is optional and skipped when "
                    "Postgres/Ollama are unavailable."
                ),
                "synthesis": (
                    "Scores current atlas.research.grouping.group_claims behavior."
                ),
            },
        },
    )
