"""Mission-template model (Phase A · PHASE_A_PLAN §A.5, B7).

A ``MissionTemplate`` is a reusable, versioned blueprint for a mission: its worker set, default
(versioned) config schema, knowledge domains, and success criteria. Maps a ``mission.templates``
row (ADR-0036). Instantiation stamps the ``template_id + template_version`` onto the mission so a
later built-in bump never silently rewrites existing missions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class MissionTemplate(Model):
    id: str
    name: str
    template_version: int = 1
    description: str = ""
    worker_specs: list[dict[str, Any]] = field(default_factory=list)
    config_schema_type: str = "generic"
    config_schema_version: int = 1
    default_config: dict[str, Any] = field(default_factory=dict)
    knowledge_domains: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
