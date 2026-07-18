"""Atlas Benchmark Set — fixed research problems for milestone regression."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.eval.fixtures import load_json_fixture


@dataclass(frozen=True, slots=True)
class BenchmarkProblem:
    id: str
    topic: str
    objective: str
    domains: tuple[str, ...]
    acceptance_notes: str
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkProblem":
        return cls(
            id=str(data["id"]),
            topic=str(data.get("topic", "")),
            objective=str(data.get("objective", "")),
            domains=tuple(str(d) for d in (data.get("domains") or [])),
            acceptance_notes=str(data.get("acceptance_notes", "")),
            tags=tuple(str(t) for t in (data.get("tags") or [])),
        )


def load_benchmark_set(*, root: Path | None = None) -> list[BenchmarkProblem]:
    """Load the durable Atlas Benchmark Set (10–20 fixed research problems)."""
    data = load_json_fixture("benchmark_set.json", root=root)
    problems = data.get("problems")
    if not isinstance(problems, list):
        raise ValueError("benchmark_set.json missing problems list")
    return [BenchmarkProblem.from_dict(p) for p in problems]


def benchmark_snapshot(
    problems: list[BenchmarkProblem] | None = None,
    *,
    milestone: str = "3B.0",
    root: Path | None = None,
) -> dict[str, Any]:
    """Record Benchmark Set membership for a milestone (execution comes later)."""
    items = problems if problems is not None else load_benchmark_set(root=root)
    return {
        "milestone": milestone,
        "n_problems": len(items),
        "status": "seeded",
        "problems": [
            {
                "id": p.id,
                "topic": p.topic,
                "domains": list(p.domains),
                "tags": list(p.tags),
                "run_status": "not_run",
            }
            for p in items
        ],
    }
