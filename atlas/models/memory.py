"""Memory-domain model: MemoryItem (ADR-0036/0048)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class MemoryItem(Model):
    """A single memory (``memory.items``).

    ``kind`` is working | episodic | semantic. ``occurred_at`` is the event-time
    date dimension (may differ from ``created_at``). ``embedding`` is not carried
    on the model (it lives in pgvector for search); ``similarity`` is populated
    only on recall results.
    """

    id: str
    kind: str
    content: str
    scope: str = "global"
    embedding_model: str | None = None
    importance: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    similarity: float | None = None  # set on recall (1 - cosine distance)
