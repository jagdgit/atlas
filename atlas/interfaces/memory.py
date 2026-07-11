"""Memory provider interface (ADR-0038).

The abstraction for the memory store (pgvector today via ``MemoryService``;
Redis/other later). Services/agents depend on this protocol, not the concrete
store. ``recall`` returns typed ``MemoryItem`` models (ADR-0036).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from atlas.models import MemoryItem


@runtime_checkable
class MemoryProvider(Protocol):
    name: str

    def remember(self, content: str, **options: Any) -> "MemoryItem":
        """Persist a memory item and return it."""
        ...

    def recall(self, query: str, *, limit: int = 10, **options: Any) -> "list[MemoryItem]":
        """Return memory items relevant to ``query`` (semantic search)."""
        ...

    def forget(self, memory_id: str) -> bool:
        """Remove a memory item; return whether it existed."""
        ...
