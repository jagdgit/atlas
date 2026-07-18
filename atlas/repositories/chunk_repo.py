"""Repository for ``knowledge.chunks`` — ordered segments of a document."""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class ChunkRepository(BaseRepository):
    def create(
        self,
        document_id: UUID | str,
        ordinal: int,
        content: str,
        *,
        token_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO knowledge.chunks
                (document_id, ordinal, content, token_count, metadata)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (document_id, ordinal) DO UPDATE
                SET content = EXCLUDED.content,
                    token_count = EXCLUDED.token_count,
                    metadata = EXCLUDED.metadata
            RETURNING *
            """,
            (
                str(document_id),
                ordinal,
                content,
                token_count,
                Jsonb(metadata or {}),
            ),
        )

    def add_many(
        self, document_id: UUID | str, chunks: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Insert an ordered batch of chunks; ``chunks`` items provide at least
        ``ordinal`` and ``content`` (optional ``token_count``, ``metadata``)."""
        rows: list[dict[str, Any]] = []
        for chunk in chunks:
            rows.append(
                self.create(
                    document_id,
                    chunk["ordinal"],
                    chunk["content"],
                    token_count=chunk.get("token_count"),
                    metadata=chunk.get("metadata"),
                )
            )
        return rows

    def get(self, chunk_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM knowledge.chunks WHERE id = %s", (str(chunk_id),)
        )

    def list_for_document(
        self, document_id: UUID | str
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM knowledge.chunks
            WHERE document_id = %s
            ORDER BY ordinal ASC
            """,
            (str(document_id),),
        )

    def count_for_document(self, document_id: UUID | str) -> int:
        return self.fetch_val(
            "SELECT count(*) FROM knowledge.chunks WHERE document_id = %s",
            (str(document_id),),
        )

    def search_lexical(
        self,
        query: str,
        *,
        limit: int = 5,
        domains: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search over chunk content (tsvector / GIN). Returns rank DESC."""
        q = (query or "").strip()
        if not q or limit <= 0:
            return []
        if domains:
            return self.fetch_all(
                """
                SELECT c.id AS chunk_id, c.document_id, c.ordinal, c.content,
                       ts_rank_cd(c.content_tsv, plainto_tsquery('english', %s)) AS rank
                FROM knowledge.chunks c
                JOIN knowledge.documents d ON d.id = c.document_id
                WHERE c.content_tsv @@ plainto_tsquery('english', %s)
                  AND d.domain = ANY(%s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (q, q, list(domains), limit),
            )
        return self.fetch_all(
            """
            SELECT c.id AS chunk_id, c.document_id, c.ordinal, c.content,
                   ts_rank_cd(c.content_tsv, plainto_tsquery('english', %s)) AS rank
            FROM knowledge.chunks c
            WHERE c.content_tsv @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (q, q, limit),
        )
