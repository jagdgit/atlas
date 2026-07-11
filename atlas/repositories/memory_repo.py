"""Repository for ``memory.items`` — the only SQL layer for memory (ADR-0027).

Returns ``MemoryItem`` models (ADR-0036). Vectors are passed as pgvector literals
cast to ``vector``; similarity uses cosine distance (``<=>``). Recall always
filters out expired rows so working-memory TTL is honoured even before a prune.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models import MemoryItem
from atlas.repositories.base import BaseRepository
from atlas.repositories.embedding_repo import to_pgvector

VALID_KINDS = {"working", "episodic", "semantic"}

# Columns to select (never SELECT * — embedding is large and not needed on the model).
_COLS = (
    "id, kind, scope, content, embedding_model, importance, metadata, "
    "occurred_at, expires_at, created_at, updated_at"
)

_NOT_EXPIRED = "(expires_at IS NULL OR expires_at > now())"


class MemoryRepository(BaseRepository):
    def add(
        self,
        kind: str,
        content: str,
        *,
        scope: str = "global",
        embedding: Sequence[float] | None = None,
        embedding_model: str | None = None,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryItem:
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid memory kind: {kind}")
        literal = to_pgvector(embedding) if embedding is not None else None
        row = self.fetch_one(
            f"""
            INSERT INTO memory.items
                (kind, scope, content, embedding, embedding_model, importance,
                 metadata, occurred_at, expires_at)
            VALUES (%s, %s, %s, %s::vector, %s, %s, %s,
                    COALESCE(%s::timestamptz, now()), %s)
            RETURNING {_COLS}
            """,
            (
                kind,
                scope,
                content,
                literal,
                embedding_model,
                importance,
                Jsonb(metadata or {}),
                occurred_at,
                expires_at,
            ),
        )
        return MemoryItem.from_row(row)

    def get(self, memory_id: UUID | str) -> MemoryItem | None:
        row = self.fetch_one(
            f"SELECT {_COLS} FROM memory.items WHERE id = %s", (str(memory_id),)
        )
        return MemoryItem.from_row(row) if row else None

    def semantic_search(
        self,
        query_vector: Sequence[float],
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[MemoryItem]:
        """Return embedded, non-expired memories most similar to ``query_vector``."""
        literal = to_pgvector(query_vector)
        filters = ["embedding IS NOT NULL", _NOT_EXPIRED]
        params: list[Any] = [literal]
        if kind is not None:
            filters.append("kind = %s")
            params.append(kind)
        if scope is not None:
            filters.append("scope = %s")
            params.append(scope)
        where = " AND ".join(filters)
        params.append(literal)  # ORDER BY vector
        params.append(limit)
        rows = self.fetch_all(
            f"""
            SELECT {_COLS}, embedding <=> %s::vector AS distance
            FROM memory.items
            WHERE {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            tuple(params),
        )
        return [self._with_similarity(r) for r in rows]

    def recent(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """Return non-expired memories ordered by event time (newest first)."""
        filters = [_NOT_EXPIRED]
        params: list[Any] = []
        if kind is not None:
            filters.append("kind = %s")
            params.append(kind)
        if scope is not None:
            filters.append("scope = %s")
            params.append(scope)
        params.append(limit)
        rows = self.fetch_all(
            f"""
            SELECT {_COLS}
            FROM memory.items
            WHERE {" AND ".join(filters)}
            ORDER BY occurred_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return MemoryItem.from_rows(rows)

    def forget(self, memory_id: UUID | str) -> bool:
        return (
            self.execute("DELETE FROM memory.items WHERE id = %s", (str(memory_id),))
            > 0
        )

    def prune_expired(self) -> int:
        """Delete expired rows; returns how many were removed."""
        return self.execute(
            "DELETE FROM memory.items WHERE expires_at IS NOT NULL AND expires_at <= now()"
        )

    def count(self) -> int:
        return self.fetch_val("SELECT count(*) FROM memory.items") or 0

    @staticmethod
    def _with_similarity(row: dict[str, Any]) -> MemoryItem:
        item = MemoryItem.from_row(row)
        distance = row.get("distance")
        if distance is None:
            return item
        return dataclasses.replace(item, similarity=1.0 - float(distance))
