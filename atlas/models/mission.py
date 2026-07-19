"""Mission-domain models (Phase A · PHASE_A_PLAN §A.1).

A ``Mission`` is a long-lived, operator-created objective that owns Jobs and (later)
Persistent Workers, runs off a versioned Configuration, and records every important action
in an append-only ``MissionJournalEntry`` (P9 explainability). Maps ``mission.missions`` /
``mission.journal`` rows (ADR-0036: typed frozen dataclasses above the repository layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model

# Mission lifecycle statuses (A-new5).
MISSION_DRAFT = "draft"
MISSION_ACTIVE = "active"
MISSION_WAITING = "waiting"      # ready but blocked on an external condition (≠ paused)
MISSION_PAUSED = "paused"        # operator-halted
MISSION_COMPLETED = "completed"
MISSION_ARCHIVED = "archived"

MISSION_STATUSES = frozenset(
    {
        MISSION_DRAFT,
        MISSION_ACTIVE,
        MISSION_WAITING,
        MISSION_PAUSED,
        MISSION_COMPLETED,
        MISSION_ARCHIVED,
    }
)
MISSION_TERMINAL = frozenset({MISSION_COMPLETED, MISSION_ARCHIVED})

# Allowed lifecycle transitions (validated in MissionService).
MISSION_TRANSITIONS: dict[str, frozenset[str]] = {
    MISSION_DRAFT: frozenset({MISSION_ACTIVE, MISSION_ARCHIVED}),
    MISSION_ACTIVE: frozenset(
        {MISSION_WAITING, MISSION_PAUSED, MISSION_COMPLETED, MISSION_ARCHIVED}
    ),
    MISSION_WAITING: frozenset(
        {MISSION_ACTIVE, MISSION_PAUSED, MISSION_COMPLETED, MISSION_ARCHIVED}
    ),
    MISSION_PAUSED: frozenset({MISSION_ACTIVE, MISSION_COMPLETED, MISSION_ARCHIVED}),
    MISSION_COMPLETED: frozenset({MISSION_ARCHIVED}),
    MISSION_ARCHIVED: frozenset(),
}

# Scheduling policy → base priority band (A7). The operator sets one stable knob
# (policy); priority/criticality refine it. See compute_effective_priority.
POLICY_REALTIME = "realtime"
POLICY_BACKGROUND = "background"
POLICY_BATCH = "batch"
POLICY_IDLE = "idle"
POLICY_EXCLUSIVE = "exclusive"

SCHEDULING_POLICIES = frozenset(
    {POLICY_REALTIME, POLICY_BACKGROUND, POLICY_BATCH, POLICY_IDLE, POLICY_EXCLUSIVE}
)
POLICY_BANDS: dict[str, int] = {
    POLICY_EXCLUSIVE: 80,
    POLICY_REALTIME: 60,
    POLICY_BACKGROUND: 20,
    POLICY_BATCH: 10,
    POLICY_IDLE: 0,
}

# Criticality → additive weight (A7).
CRIT_LOW = "low"
CRIT_NORMAL = "normal"
CRIT_HIGH = "high"
CRIT_CRITICAL = "critical"

CRITICALITIES = frozenset({CRIT_LOW, CRIT_NORMAL, CRIT_HIGH, CRIT_CRITICAL})
CRITICALITY_WEIGHTS: dict[str, int] = {
    CRIT_LOW: -20,
    CRIT_NORMAL: 0,
    CRIT_HIGH: 20,
    CRIT_CRITICAL: 40,
}


def compute_effective_priority(
    scheduling_policy: str, priority: int, criticality: str
) -> int:
    """Effective scheduler priority = policy band + priority + criticality weight (A7).

    Used in A.6 to stamp ``scheduler.tasks.priority`` on mission-owned tasks. Unknown
    enum values fall back to their neutral band/weight so a bad value never crashes
    scheduling.
    """
    band = POLICY_BANDS.get(scheduling_policy, POLICY_BANDS[POLICY_BACKGROUND])
    weight = CRITICALITY_WEIGHTS.get(criticality, 0)
    return band + int(priority) + weight


@dataclass(frozen=True, slots=True)
class Mission(Model):
    id: str
    title: str
    objective: str = ""
    status: str = MISSION_DRAFT
    success_criteria: dict[str, Any] = field(default_factory=dict)
    knowledge_domains: list[str] = field(default_factory=list)
    active_config_id: str | None = None
    scheduling_policy: str = POLICY_BACKGROUND
    priority: int = 0
    criticality: str = CRIT_NORMAL
    budget: dict[str, Any] = field(default_factory=dict)
    deadline: datetime | None = None
    importance: str | None = None
    labels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    template_id: str | None = None
    template_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def effective_priority(self) -> int:
        return compute_effective_priority(
            self.scheduling_policy, self.priority, self.criticality
        )

    @property
    def max_concurrent_tasks(self) -> int | None:
        """Phase-A budget cap (B1); ``None`` = unlimited."""
        value = self.budget.get("max_concurrent_tasks")
        return int(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class MissionJournalEntry(Model):
    id: str
    mission_id: str
    action: str
    reason: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    ts: datetime | None = None
