"""Job-domain models: Job and JobStep (Stage 2, S12).

A ``Job`` is a persistent, asynchronous unit of work with an objective; a
``JobStep`` is one ordered step in its plan. These map ``job.jobs`` / ``job.steps``
rows (ADR-0036). The step-state model (`pending → running → done | failed | blocked
| skipped`) and job-state model (`queued → running → completed |
completed_with_blocks | failed | cancelled`) implement R1/R3: a ``blocked`` step
needs the user but does not stop the job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model

# Job statuses
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_COMPLETED_WITH_BLOCKS = "completed_with_blocks"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

# Step statuses
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_FAILED = "failed"
STEP_BLOCKED = "blocked"
STEP_SKIPPED = "skipped"

# Terminal states
JOB_TERMINAL = frozenset(
    {JOB_COMPLETED, JOB_COMPLETED_WITH_BLOCKS, JOB_FAILED, JOB_CANCELLED}
)

# Planning phases (3.2e / A32.26) — stored in Job.metadata["phase"], not status.
# Keep familiar status=queued while the LLM JobPlanner runs in the background.
PHASE_PLANNING_QUEUED = "planning_queued"
PHASE_PLANNING = "planning"
PHASE_READY = "ready"
JOB_PHASE_KEY = "phase"
JOB_PLANNING_PHASES = frozenset({PHASE_PLANNING_QUEUED, PHASE_PLANNING})


@dataclass(frozen=True, slots=True)
class JobStep(Model):
    id: str
    job_id: str
    ordinal: int
    intent: str
    capability: str
    args: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: int | None = None
    status: str = STEP_PENDING
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    blocked_reason: str | None = None
    attempts: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Job(Model):
    id: str
    objective: str
    status: str = JOB_QUEUED
    session_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
