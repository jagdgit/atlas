"""Repository for ``knowledge.finding_embeddings`` — semantic dedup of prose findings (C.3f/CC4).

One vector per (finding, model). Nearest-neighbour search returns the most similar **active** findings
by cosine distance (``<=>``; smaller = closer), so the Consolidator can merge a paraphrase into the
existing finding instead of creating a duplicate.
"""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from atlas.repositories.base import BaseRepository
from atlas.repositories.embedding_repo import to_pgvector


class FindingEmbeddingRepository(BaseRepository):
    def upsert(
        self, finding_id: UUID | str, model: str, vector: Sequence[float]
    ) -> dict[str, Any]:
        literal = to_pgvector(vector)
        return self.fetch_one(
            """
            INSERT INTO knowledge.finding_embeddings (finding_id, model, dim, embedding)
            VALUES (%s, %s, %s, %s::vector)
            ON CONFLICT (finding_id, model) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    dim = EXCLUDED.dim,
                    created_at = now()
            RETURNING id, finding_id, model, dim, created_at
            """,
            (str(finding_id), model, len(vector), literal),
        )

    def search(
        self,
        query_vector: Sequence[float],
        model: str,
        *,
        domains: Sequence[str] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Nearest ACTIVE findings to ``query_vector`` (cosine distance).

        Only ``active``/``contested`` heads are candidates — superseded/archived findings never
        capture new evidence. Optional ``domains`` scopes the search (e.g. only ``external`` prose).
        """
        literal = to_pgvector(query_vector)
        domain_clause = "AND f.domain = ANY(%s)" if domains else ""
        params: list[Any] = [literal, model]
        if domains:
            params.append(list(domains))
        params.extend([literal, limit])
        return self.fetch_all(
            f"""
            SELECT f.id AS finding_id,
                   f.canonical_id,
                   f.statement,
                   f.domain,
                   e.embedding <=> %s::vector AS distance
            FROM knowledge.finding_embeddings e
            JOIN knowledge.findings f ON f.id = e.finding_id
            WHERE e.model = %s
              AND f.status IN ('active', 'contested')
              {domain_clause}
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
            """,
            tuple(params),
        )

    def count(self) -> int:
        return int(self.fetch_val("SELECT count(*) FROM knowledge.finding_embeddings") or 0)
