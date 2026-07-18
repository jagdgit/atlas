"""Persist retrieval diagnostics (dense / lexical / rrf scores) for later tuning."""

from __future__ import annotations

from typing import Any, Sequence

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class RetrievalDiagnosticsRepository(BaseRepository):
    def record(
        self,
        query: str,
        hits: Sequence[dict[str, Any]],
        *,
        role: str = "research",
        mode: str = "hybrid",
        domains: Sequence[str] | None = None,
        tiers: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Insert one diagnostics row; returns the stored row (incl. id)."""
        return self.fetch_one(
            """
            INSERT INTO knowledge.retrieval_diagnostics
                (query, role, mode, domains, tiers, hits)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, query, role, mode, domains, tiers, hits, created_at
            """,
            (
                query,
                role,
                mode,
                list(domains) if domains is not None else None,
                list(tiers) if tiers is not None else None,
                Jsonb(list(hits)),
            ),
        )
