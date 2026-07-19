"""Configuration-domain model (Phase A · PHASE_A_PLAN §A.2).

A ``MissionConfig`` is one immutable, versioned configuration document for a mission
(P6). Maps a ``config.mission_configs`` row (ADR-0036). Editing produces a *new* version;
existing versions are never mutated, so every past result stays reproducible against the
exact config (schema_type + schema_version + document) that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class MissionConfig(Model):
    id: str
    mission_id: str
    version: int
    schema_type: str
    schema_version: int = 1
    document: dict[str, Any] = field(default_factory=dict)
    change_note: str = ""
    created_at: datetime | None = None
