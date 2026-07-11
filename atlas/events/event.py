"""Event envelope.

A minimal, immutable event carried by the in-process dispatcher. The same shape
maps 1:1 onto the ``audit.events`` table for the future DB-backed phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        type: str,
        payload: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> "Event":
        return cls(type=type, payload=payload or {}, source=source)
