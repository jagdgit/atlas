"""Schedule-domain model (Phase A · PHASE_A_PLAN §A.3).

A ``Schedule`` is a durable recurrence rule: "run ``task_type`` with ``payload`` every
``interval_seconds``". Maps a ``scheduler.schedules`` row (ADR-0036). The next fire time
(``next_run_at``) is persisted so recurrence survives a crash + reboot (P1/P4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class Schedule(Model):
    id: str
    task_type: str
    interval_seconds: int
    payload: dict[str, Any] = field(default_factory=dict)
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    enabled: bool = True
    mission_id: str | None = None
    worker_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
