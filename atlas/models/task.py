"""Scheduler-domain models: Task, TaskRun."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class Task(Model):
    """A unit of deferred work (``scheduler.tasks``)."""

    id: str
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    priority: int = 0
    max_retries: int = 3
    retry_count: int = 0
    scheduled_at: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskRun(Model):
    """One execution attempt of a task (``scheduler.task_runs``)."""

    id: str
    task_id: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    worker_id: str | None = None
