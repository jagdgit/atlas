"""Repository for ``knowledge.candidates`` (Phase C · §C.3, CC11 / P11/P13).

Candidates are the **transient inbox** of the Knowledge Consolidator: readers/extractors emit one
per observation ("I saw claim X in asset A"), and only the Consolidator turns them into findings.
Rows are marked ``consumed`` when processed and pruned after a retention window — the durable audit
trail is the lineage graph (``knowledge.lineage``), not these rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

VALID_STATUSES = {"pending", "consumed", "discarded"}


class CandidateRepository(BaseRepository):
    def create(
        self,
        statement: str,
        *,
        claim_type: str = "prose",
        value: dict[str, Any] | None = None,
        domain: str = "research",
        identity_key: list[Any] | None = None,
        evidence_ref: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        confidence: str | None = None,
        confidence_score: float | None = None,
        reader: str | None = None,
        reader_version: str | None = None,
        mission_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Emit one candidate observation. Soft provenance columns fall back to the refs/JSON."""
        prov = provenance or {}
        ev = evidence_ref or {}
        mission_id = mission_id or ev.get("mission_id") or prov.get("mission_id")
        job_id = job_id or ev.get("job_id") or prov.get("job_id")
        reader = reader or ev.get("reader") or prov.get("reader")
        reader_version = reader_version or ev.get("reader_version") or prov.get("reader_version")
        return self.fetch_one(
            """
            INSERT INTO knowledge.candidates (
                statement, claim_type, value, domain, identity_key, evidence_ref,
                provenance, confidence, confidence_score, reader, reader_version,
                mission_id, job_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                statement,
                claim_type,
                Jsonb(value) if value is not None else None,
                domain,
                Jsonb(identity_key) if identity_key is not None else None,
                Jsonb(ev),
                Jsonb(prov),
                confidence,
                confidence_score,
                reader,
                reader_version,
                mission_id,
                job_id,
            ),
        )

    def get(self, candidate_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM knowledge.candidates WHERE id = %s", (str(candidate_id),)
        )

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Unconsumed candidates, oldest-first (the Consolidator's work queue)."""
        return self.fetch_all(
            """
            SELECT * FROM knowledge.candidates
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )

    def mark_consumed(
        self, candidate_id: UUID | str, *, finding_id: str | None = None
    ) -> dict[str, Any] | None:
        """Mark a candidate consumed by consolidation, linking the finding it fed."""
        return self.fetch_one(
            """
            UPDATE knowledge.candidates
            SET status = 'consumed', consumed_at = now(), consolidated_finding_id = %s
            WHERE id = %s
            RETURNING *
            """,
            (finding_id, str(candidate_id)),
        )

    def mark_discarded(self, candidate_id: UUID | str) -> dict[str, Any] | None:
        """Mark a candidate discarded (e.g. empty/invalid) without consolidating it."""
        return self.fetch_one(
            """
            UPDATE knowledge.candidates
            SET status = 'discarded', consumed_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (str(candidate_id),),
        )

    def count_by_status(self, status: str) -> int:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return int(
            self.fetch_val(
                "SELECT count(*) FROM knowledge.candidates WHERE status = %s", (status,)
            )
            or 0
        )

    def prune_consumed(self, *, older_than_days: int = 30) -> int:
        """Delete consumed candidates older than the retention window; returns rows removed."""
        return self.execute(
            """
            DELETE FROM knowledge.candidates
            WHERE status IN ('consumed', 'discarded')
              AND consumed_at IS NOT NULL
              AND consumed_at < now() - make_interval(days => %s)
            """,
            (int(older_than_days),),
        )
