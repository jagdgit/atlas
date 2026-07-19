"""Agent-domain models: AgentRecord, AgentRun, AgentStep."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class AgentRecord(Model):
    """A registered agent in the catalog (``agent.agents``)."""

    id: str
    name: str
    kind: str
    description: str | None = None
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentRun(Model):
    """One agent invocation — the unit of observability/recovery (``agent.runs``)."""

    id: str
    agent_name: str
    status: str = "pending"
    agent_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentStep(Model):
    """An ordered step in a run's trace (``agent.steps``)."""

    id: str
    run_id: str
    ordinal: int
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
