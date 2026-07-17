"""Permanent static-first task cost model (D32.10 / A32.19).

Static values are operator-configurable now.  Stage 4 may tune the same model
from observed machine history; callers do not change when that happens.
"""

from __future__ import annotations

from collections.abc import Mapping

from atlas.core.execution.models import TaskCost


DEFAULT_COSTS: dict[str, TaskCost] = {
    "download": TaskCost(units=1, ram_mb=64),
    "read_html": TaskCost(units=2, ram_mb=128),
    "read_pdf": TaskCost(units=3, ram_mb=256),
    "embedding": TaskCost(units=6, ram_mb=700, llm_slots=1),
    "ocr_pdf": TaskCost(units=8, ram_mb=900),
    "llm_extract": TaskCost(units=15, ram_mb=2100, llm_slots=1),
    "llm_plan": TaskCost(units=12, ram_mb=2100, llm_slots=1),
    "llm_summarize": TaskCost(units=12, ram_mb=2100, llm_slots=1),
    "verify": TaskCost(units=2, ram_mb=128),
    "report": TaskCost(units=3, ram_mb=256),
}


class TaskCostModel:
    """Typed lookup over static task costs."""

    def __init__(self, costs: Mapping[str, TaskCost | Mapping[str, int]] | None = None) -> None:
        merged = dict(DEFAULT_COSTS)
        for kind, value in (costs or {}).items():
            if isinstance(value, TaskCost):
                merged[str(kind)] = value
            else:
                merged[str(kind)] = TaskCost(
                    units=max(0, int(value.get("units", 0))),
                    ram_mb=max(0, int(value.get("ram_mb", 0))),
                    llm_slots=max(0, int(value.get("llm_slots", 0))),
                )
        self._costs = merged

    def for_kind(self, kind: str) -> TaskCost:
        return self._costs.get(kind, TaskCost(units=1, ram_mb=64))

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {kind: cost.as_dict() for kind, cost in sorted(self._costs.items())}
