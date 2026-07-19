"""Repository for ``knowledge.coverage`` — the extraction coverage map (Phase C · §C.4, A10/CC15).

One row per ``(asset_id, asset_version, reader, reader_version)`` recording *what was read and how it
went*. Backs the coverage-% rollups ("Python 100%, MATLAB 20%") and targeted re-extraction (enumerate
assets processed by an older reader/extractor version).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from atlas.repositories.base import BaseRepository

VALID_STATUSES = {"pending", "done", "failed", "unsupported", "empty"}


class CoverageRepository(BaseRepository):
    def record(
        self,
        asset_id: UUID | str,
        asset_version: int,
        reader: str,
        reader_version: str,
        *,
        status: str = "done",
        extractor_version: str = "",
        domain: str = "external",
        source: str | None = None,
        repo_uid: str | None = None,
        findings_count: int = 0,
        chunks_count: int = 0,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Upsert a coverage row for one (asset version × reader version). Idempotent per the key."""
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid coverage status: {status}")
        extracted_at_expr = "now()" if status == "done" else "NULL"
        return self.fetch_one(
            f"""
            INSERT INTO knowledge.coverage (
                asset_id, asset_version, reader, reader_version, extractor_version,
                domain, source, repo_uid, status, findings_count, chunks_count, reason,
                extracted_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                {extracted_at_expr}
            )
            ON CONFLICT (asset_id, asset_version, reader, reader_version) DO UPDATE SET
                extractor_version = EXCLUDED.extractor_version,
                domain = EXCLUDED.domain,
                source = EXCLUDED.source,
                repo_uid = EXCLUDED.repo_uid,
                status = EXCLUDED.status,
                findings_count = EXCLUDED.findings_count,
                chunks_count = EXCLUDED.chunks_count,
                reason = EXCLUDED.reason,
                extracted_at = CASE WHEN EXCLUDED.status = 'done' THEN now()
                                    ELSE knowledge.coverage.extracted_at END,
                updated_at = now()
            RETURNING *
            """,
            (
                str(asset_id), asset_version, reader, reader_version, extractor_version,
                domain, source, repo_uid, status, findings_count, chunks_count, reason,
            ),
        )

    def get(
        self, asset_id: UUID | str, asset_version: int, reader: str, reader_version: str
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            SELECT * FROM knowledge.coverage
            WHERE asset_id = %s AND asset_version = %s
              AND reader = %s AND reader_version = %s
            """,
            (str(asset_id), asset_version, reader, reader_version),
        )

    def list(
        self,
        *,
        domain: str | None = None,
        reader: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain is not None:
            clauses.append("domain = %s")
            params.append(domain)
        if reader is not None:
            clauses.append("reader = %s")
            params.append(reader)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT * FROM knowledge.coverage
            {where}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def summary(self, *, by: str = "domain") -> list[dict[str, Any]]:
        """Coverage rollup grouped by ``domain`` or ``source``.

        Returns one row per group with total attempts, done, and the failing statuses so the service
        can compute coverage % = done / total.
        """
        column = "domain" if by == "domain" else "source"
        return self.fetch_all(
            f"""
            SELECT COALESCE({column}, 'unknown') AS group_key,
                   count(*) AS total,
                   count(*) FILTER (WHERE status = 'done')        AS done,
                   count(*) FILTER (WHERE status = 'failed')      AS failed,
                   count(*) FILTER (WHERE status = 'unsupported') AS unsupported,
                   count(*) FILTER (WHERE status = 'empty')       AS empty,
                   count(*) FILTER (WHERE status = 'pending')     AS pending,
                   COALESCE(sum(findings_count), 0) AS findings
            FROM knowledge.coverage
            GROUP BY group_key
            ORDER BY group_key
            """,
        )

    def stale(
        self,
        reader: str,
        *,
        reader_version: str | None = None,
        extractor_version: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Coverage rows for ``reader`` processed by an OLDER reader/extractor version (A10).

        These are exactly the assets that a version bump should re-extract; everything already at the
        current version is left untouched.
        """
        if reader_version is None and extractor_version is None:
            raise ValueError("stale() needs reader_version and/or extractor_version to compare")
        clauses = ["reader = %s", "status = 'done'"]
        params: list[Any] = [reader]
        version_clauses: list[str] = []
        if reader_version is not None:
            version_clauses.append("reader_version <> %s")
            params.append(reader_version)
        if extractor_version is not None:
            version_clauses.append("extractor_version <> %s")
            params.append(extractor_version)
        clauses.append("(" + " OR ".join(version_clauses) + ")")
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT * FROM knowledge.coverage
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at ASC
            LIMIT %s
            """,
            tuple(params),
        )

    def mark_pending(self, coverage_id: UUID | str) -> dict[str, Any] | None:
        """Flag a coverage row for re-extraction (A10)."""
        return self.fetch_one(
            """
            UPDATE knowledge.coverage
            SET status = 'pending', updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (str(coverage_id),),
        )

    def count(self) -> int:
        return int(self.fetch_val("SELECT count(*) FROM knowledge.coverage") or 0)
