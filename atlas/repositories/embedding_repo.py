"""Repository for ``knowledge.embeddings`` — vectors + similarity search.

Vectors are passed as pgvector literals (``[a,b,c]``) and cast to ``vector`` in
SQL, so no per-connection adapter registration is needed. Similarity uses cosine
distance (``<=>``); smaller distance = more similar.
"""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from atlas.repositories.base import BaseRepository


def to_pgvector(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class EmbeddingRepository(BaseRepository):
    def upsert(
        self, chunk_id: UUID | str, model: str, vector: Sequence[float]
    ) -> dict[str, Any]:
        literal = to_pgvector(vector)
        return self.fetch_one(
            """
            INSERT INTO knowledge.embeddings (chunk_id, model, dim, embedding)
            VALUES (%s, %s, %s, %s::vector)
            ON CONFLICT (chunk_id, model) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    dim = EXCLUDED.dim,
                    created_at = now()
            RETURNING id, chunk_id, model, dim, created_at
            """,
            (str(chunk_id), model, len(vector), literal),
        )

    def get_for_chunk(
        self, chunk_id: UUID | str, model: str
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            SELECT id, chunk_id, model, dim, created_at
            FROM knowledge.embeddings
            WHERE chunk_id = %s AND model = %s
            """,
            (str(chunk_id), model),
        )

    def search(
        self,
        query_vector: Sequence[float],
        model: str,
        *,
        limit: int = 5,
        domains: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the most similar chunks to ``query_vector`` (cosine distance).

        Optional ``domains`` filters to knowledge-universe tags (Stage 3 / D3.13).
        """
        literal = to_pgvector(query_vector)
        if domains:
            return self.fetch_all(
                """
                SELECT c.id AS chunk_id,
                       c.document_id,
                       c.ordinal,
                       c.content,
                       e.embedding <=> %s::vector AS distance
                FROM knowledge.embeddings e
                JOIN knowledge.chunks c ON c.id = e.chunk_id
                JOIN knowledge.documents d ON d.id = c.document_id
                WHERE e.model = %s
                  AND d.domain = ANY(%s)
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, model, list(domains), literal, limit),
            )
        return self.fetch_all(
            """
            SELECT c.id AS chunk_id,
                   c.document_id,
                   c.ordinal,
                   c.content,
                   e.embedding <=> %s::vector AS distance
            FROM knowledge.embeddings e
            JOIN knowledge.chunks c ON c.id = e.chunk_id
            WHERE e.model = %s
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
            """,
            (literal, model, literal, limit),
        )

    def count(self) -> int:
        return self.fetch_val("SELECT count(*) FROM knowledge.embeddings")
