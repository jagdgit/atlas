"""System-domain model: HealthRecord."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class HealthRecord(Model):
    """A recorded health check result (``system.health``)."""

    id: str
    service: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime | None = None

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"
