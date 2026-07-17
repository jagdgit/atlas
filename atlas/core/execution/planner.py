"""Kernel Execution Planner (Stage 3.2d).

This service orders eligible work deterministically and asks the Resource
Manager for admission advice.  It never executes tasks itself.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from atlas.core.execution.costs import TaskCostModel
from atlas.core.execution.models import ExecutionTask, PlannedTask
from atlas.services.base import HealthStatus


class ExecutionPlanner:
    name = "execution"

    def __init__(
        self,
        resources,
        costs: TaskCostModel | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._resources = resources
        self._costs = costs or TaskCostModel()
        self._logger = logger or logging.getLogger("atlas.execution")

    @property
    def costs(self) -> TaskCostModel:
        return self._costs

    def order(
        self,
        tasks: Iterable[ExecutionTask],
        *,
        completed: Iterable[str] = (),
    ) -> list[ExecutionTask]:
        """Return dependency-ready tasks in a stable priority/cost/id order."""
        done = set(completed)
        ready = [
            task
            for task in tasks
            if task.id not in done
            and all(dependency in done for dependency in task.depends_on)
        ]
        return sorted(
            ready,
            key=lambda task: (
                -int(task.priority),
                self._costs.for_kind(task.kind).units,
                task.id,
            ),
        )

    def plan(
        self,
        tasks: Iterable[ExecutionTask],
        *,
        completed: Iterable[str] = (),
        profile: str | None = None,
    ) -> list[PlannedTask]:
        """Annotate ready tasks with current Resource Manager admission advice."""
        planned: list[PlannedTask] = []
        for task in self.order(tasks, completed=completed):
            cost = self._costs.for_kind(task.kind)
            decision = self._resources.can_admit(
                cost_units=cost.units,
                expected_ram_mb=cost.ram_mb,
                llm_slots=cost.llm_slots,
                profile=profile,
            )
            planned.append(
                PlannedTask(
                    task=task,
                    cost=cost,
                    admitted=decision.allowed,
                    reason=decision.reason,
                )
            )
        # Prefer admitted tasks while preserving deterministic order within groups.
        return sorted(planned, key=lambda item: (not item.admitted,))

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(
            "execution planner ready",
            task_kinds=len(self._costs.as_dict()),
        )
