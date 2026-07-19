"""Worker-domain models (Phase A · PHASE_A_PLAN §A.4).

A ``Worker`` is a long-running, mission-owned Persistent Worker executed as a short-task +
checkpoint loop; a ``WorkerInput`` is one durable operator input awaiting consumption at the
top of a tick. Both map ``worker.workers`` / ``worker.inputs`` rows (ADR-0036).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model

# Lifecycle status (A-new6).
WORKER_RUNNING = "running"
WORKER_RECOVERING = "recovering"   # a tick failed; backing off before retry (B4)
WORKER_PAUSED = "paused"           # operator-halted, or crash-looped past the retry cap
WORKER_FAILED = "failed"
WORKER_STOPPED = "stopped"

WORKER_STATUSES = frozenset(
    {WORKER_RUNNING, WORKER_RECOVERING, WORKER_PAUSED, WORKER_FAILED, WORKER_STOPPED}
)
# Statuses whose scheduled ticks are still processed (recovering may *skip* until next_retry_at).
WORKER_TICKABLE = frozenset({WORKER_RUNNING, WORKER_RECOVERING})

# Health tier for the dashboard (A-new6), separate from lifecycle status.
HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_BLOCKED = "blocked"
HEALTH_RECOVERING = "recovering"
HEALTH_FAILED = "failed"

# Crash policy (B4): consecutive-failure backoff, then pause on the 5th failure.
CRASH_BACKOFF_SECONDS = (10, 30, 60, 300)
CRASH_PAUSE_AFTER = 5


def backoff_for(restart_count: int) -> float:
    """Backoff (seconds) for the given consecutive-failure count (1-indexed)."""
    idx = max(0, min(restart_count, len(CRASH_BACKOFF_SECONDS)) - 1)
    return float(CRASH_BACKOFF_SECONDS[idx])


@dataclass(frozen=True, slots=True)
class Worker(Model):
    id: str
    mission_id: str
    type: str
    worker_version: int = 1
    status: str = WORKER_RUNNING
    health: str = HEALTH_HEALTHY
    schedule_id: str | None = None
    config_version: int | None = None
    restart_count: int = 0
    next_retry_at: datetime | None = None
    last_tick_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class WorkerInput(Model):
    id: str
    worker_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: datetime | None = None
    consumed_at: datetime | None = None
