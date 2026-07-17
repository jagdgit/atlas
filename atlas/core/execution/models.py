"""Execution-planning contracts (Stage 3.2d).

The Execution Planner decides *what should run next*.  The Resource Manager
separately decides *whether it may run now*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskCost:
    """Static resource estimate for one task class."""

    units: int
    ram_mb: int = 0
    llm_slots: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "units": self.units,
            "ram_mb": self.ram_mb,
            "llm_slots": self.llm_slots,
        }


@dataclass(frozen=True, slots=True)
class ExecutionTask:
    """A deterministic, schedulable work item."""

    id: str
    kind: str
    priority: int = 0
    depends_on: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlannedTask:
    """A ready task annotated with its static cost and admission state."""

    task: ExecutionTask
    cost: TaskCost
    admitted: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.task.id,
            "kind": self.task.kind,
            "priority": self.task.priority,
            "cost": self.cost.as_dict(),
            "admitted": self.admitted,
            "reason": self.reason,
        }
