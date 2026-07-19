"""Repository for ``knowledge.lineage`` — the finding evidence graph (Phase C · §C.3, CC12 / P9).

Append-only. Every consolidation decision records one edge here so Atlas can answer *"what evidence
created / strengthened / revised / superseded / contradicted this finding?"*. Never pruned — this is
the durable audit trail behind confidence and maturity changes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

# Edge types (mirror the CHECK in migration 0031).
EDGE_CREATED_BY = "created_by"
EDGE_SUPPORTED_BY = "supported_by"
EDGE_REVISED_BY = "revised_by"
EDGE_SUPERSEDED_BY = "superseded_by"
EDGE_CONTRADICTED_BY = "contradicted_by"

EDGE_TYPES = frozenset(
    {EDGE_CREATED_BY, EDGE_SUPPORTED_BY, EDGE_REVISED_BY, EDGE_SUPERSEDED_BY, EDGE_CONTRADICTED_BY}
)


class LineageRepository(BaseRepository):
    def record(
        self,
        finding_id: str,
        edge_type: str,
        *,
        canonical_id: str | None = None,
        revision: int | None = None,
        evidence_ref: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one lineage edge for a finding revision."""
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"invalid lineage edge_type: {edge_type}")
        return self.fetch_one(
            """
            INSERT INTO knowledge.lineage (
                finding_id, canonical_id, revision, edge_type, evidence_ref, detail
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                finding_id,
                canonical_id,
                revision,
                edge_type,
                Jsonb(evidence_ref or {}),
                Jsonb(detail or {}),
            ),
        )

    def list_for_finding(self, finding_id: UUID | str) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM knowledge.lineage
            WHERE finding_id = %s
            ORDER BY created_at ASC
            """,
            (str(finding_id),),
        )

    def list_for_canonical(self, canonical_id: str) -> list[dict[str, Any]]:
        """The full evidence history for a logical finding across all its revisions."""
        return self.fetch_all(
            """
            SELECT * FROM knowledge.lineage
            WHERE canonical_id = %s
            ORDER BY created_at ASC
            """,
            (canonical_id,),
        )

    def list_by_edge_type(self, edge_type: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"invalid lineage edge_type: {edge_type}")
        return self.fetch_all(
            """
            SELECT * FROM knowledge.lineage
            WHERE edge_type = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (edge_type, limit),
        )

    def count_for_finding(self, finding_id: UUID | str) -> int:
        return int(
            self.fetch_val(
                "SELECT count(*) FROM knowledge.lineage WHERE finding_id = %s",
                (str(finding_id),),
            )
            or 0
        )
