"""Repository for durable ``knowledge.findings`` (Stage 3B.2 / 3B.3)."""

from __future__ import annotations

from typing import Any, Sequence

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class FindingRepository(BaseRepository):
    def next_canonical_id(self) -> str:
        """Allocate the next stable canonical id (``F-000042``)."""
        n = self.fetch_val("SELECT nextval('knowledge.findings_canonical_seq')")
        return f"F-{int(n):06d}"

    def create(
        self,
        statement: str,
        *,
        canonical_id: str | None = None,
        revision: int = 1,
        value: dict[str, Any] | None = None,
        claim_type: str = "prose",
        confidence: str = "UNVERIFIED",
        confidence_score: float = 0.0,
        status: str = "active",
        freshness: str = "current",
        quality: dict[str, Any] | None = None,
        supporting: list[dict[str, Any]] | None = None,
        contradicting: list[dict[str, Any]] | None = None,
        provenance: dict[str, Any] | None = None,
        domain: str = "research",
        last_verified: str | None = None,
        finding_id: str | None = None,
        supersedes: str | None = None,
        identity_key: list[Any] | None = None,
        mission_id: str | None = None,
        job_id: str | None = None,
        maturity: str = "candidate",
    ) -> dict[str, Any]:
        cid = canonical_id or self.next_canonical_id()
        # P12 provenance columns: who *discovered* this finding (never ownership). Fall back to the
        # provenance JSON so callers that only stamp the JSON still populate the indexed columns.
        prov = provenance or {}
        mission_id = mission_id or (prov.get("mission_id") if isinstance(prov, dict) else None)
        job_id = job_id or (prov.get("job_id") if isinstance(prov, dict) else None)
        params_common = (
            cid,
            revision,
            statement,
            Jsonb(value) if value is not None else None,
            claim_type,
            confidence,
            confidence_score,
            status,
            freshness,
            Jsonb(quality or {}),
            Jsonb(supporting or []),
            Jsonb(contradicting or []),
            Jsonb(provenance or {}),
            domain,
            last_verified,
            supersedes,
            Jsonb(identity_key) if identity_key is not None else None,
            mission_id,
            job_id,
            maturity,
        )
        if finding_id:
            return self.fetch_one(
                """
                INSERT INTO knowledge.findings (
                    id, canonical_id, revision, statement, value, claim_type,
                    confidence, confidence_score, status, freshness, quality,
                    supporting, contradicting, provenance, domain, last_verified,
                    supersedes, identity_key, mission_id, job_id, maturity
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (finding_id, *params_common),
            )
        return self.fetch_one(
            """
            INSERT INTO knowledge.findings (
                canonical_id, revision, statement, value, claim_type,
                confidence, confidence_score, status, freshness, quality,
                supporting, contradicting, provenance, domain, last_verified,
                supersedes, identity_key, mission_id, job_id, maturity
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            params_common,
        )

    def get(self, finding_id: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM knowledge.findings WHERE id = %s", (finding_id,)
        )

    def get_by_canonical_id(self, canonical_id: str) -> dict[str, Any] | None:
        return self.get_head(canonical_id, include_archive=True)

    def get_head(
        self, canonical_id: str, *, include_archive: bool = False
    ) -> dict[str, Any] | None:
        if include_archive:
            return self.fetch_one(
                """
                SELECT * FROM knowledge.findings
                WHERE canonical_id = %s
                ORDER BY revision DESC
                LIMIT 1
                """,
                (canonical_id,),
            )
        return self.fetch_one(
            """
            SELECT * FROM knowledge.findings
            WHERE canonical_id = %s
              AND status IN ('active', 'contested', 'deprecated')
            ORDER BY revision DESC
            LIMIT 1
            """,
            (canonical_id,),
        )

    def find_active_by_identity(self, identity: tuple[Any, ...]) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            SELECT * FROM knowledge.findings
            WHERE identity_key = %s::jsonb
              AND status IN ('active', 'contested')
            ORDER BY revision DESC
            LIMIT 1
            """,
            (Jsonb(list(identity)),),
        )

    def append_revision(
        self, previous: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        """Append a new revision row; mark previous superseded. Never UPDATE statement."""
        from atlas.knowledge.lifecycle import finding_identity_key

        # P12 provenance carries across revisions: prefer the incoming provenance, else the prior row.
        prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
        rev_mission_id = prov.get("mission_id") or previous.get("mission_id")
        rev_job_id = prov.get("job_id") or previous.get("job_id")

        new = self.create(
            str(data.get("statement", previous.get("statement", ""))),
            canonical_id=str(previous["canonical_id"]),
            revision=int(previous.get("revision", 1)) + 1,
            value=data.get("value", previous.get("value")),
            claim_type=str(data.get("claim_type", previous.get("claim_type", "prose"))),
            confidence=str(
                data.get("confidence", previous.get("confidence", "UNVERIFIED"))
            ),
            confidence_score=float(
                data.get("confidence_score", previous.get("confidence_score", 0)) or 0
            ),
            status=str(data.get("status", "active") or "active"),
            freshness=str(data.get("freshness", previous.get("freshness", "current"))),
            quality=data.get("quality")
            if isinstance(data.get("quality"), dict)
            else (previous.get("quality") or {}),
            supporting=list(
                data.get("supporting_sources") or data.get("supporting") or []
            ),
            contradicting=list(
                data.get("contradicting_sources") or data.get("contradicting") or []
            ),
            provenance=data.get("provenance")
            if isinstance(data.get("provenance"), dict)
            else (previous.get("provenance") or {}),
            domain=str(data.get("domain", previous.get("domain", "research"))),
            last_verified=data.get("last_verified"),
            supersedes=str(previous["id"]),
            identity_key=list(finding_identity_key(data)),
            mission_id=rev_mission_id,
            job_id=rev_job_id,
        )
        self.set_status(str(previous["id"]), "superseded", superseded_by=str(new["id"]))
        return new

    def set_status(
        self, finding_id: str, status: str, *, superseded_by: str | None = None
    ) -> dict[str, Any] | None:
        if superseded_by is not None:
            return self.fetch_one(
                """
                UPDATE knowledge.findings
                SET status = %s, superseded_by = %s, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (status, superseded_by, finding_id),
            )
        return self.fetch_one(
            """
            UPDATE knowledge.findings
            SET status = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, finding_id),
        )

    def set_maturity(self, finding_id: str, maturity: str) -> dict[str, Any] | None:
        """Update the maturity axis (candidate/verified/established) in place (CC13)."""
        return self.fetch_one(
            """
            UPDATE knowledge.findings
            SET maturity = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (maturity, finding_id),
        )

    def update_evidence(
        self,
        finding_id: str,
        *,
        supporting: list[dict[str, Any]],
        confidence: str | None = None,
        confidence_score: float | None = None,
        maturity: str | None = None,
        contradicting: list[dict[str, Any]] | None = None,
        status: str | None = None,
        last_verified: str | None = None,
    ) -> dict[str, Any] | None:
        """Merge accumulated evidence into a finding **in place** — NO new revision (C.3d).

        Evidence accumulation (a new source corroborating the *same* statement) must strengthen the
        existing finding without spawning a revision; revisions are reserved for genuine statement/
        value changes. Only the mutable belief fields are touched; the statement body is never
        rewritten here.
        """
        sets = ["supporting = %s", "updated_at = now()"]
        params: list[Any] = [Jsonb(supporting)]
        if confidence is not None:
            sets.append("confidence = %s")
            params.append(confidence)
        if confidence_score is not None:
            sets.append("confidence_score = %s")
            params.append(confidence_score)
        if maturity is not None:
            sets.append("maturity = %s")
            params.append(maturity)
        if contradicting is not None:
            sets.append("contradicting = %s")
            params.append(Jsonb(contradicting))
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        if last_verified is not None:
            sets.append("last_verified = %s")
            params.append(last_verified)
        params.append(finding_id)
        return self.fetch_one(
            f"""
            UPDATE knowledge.findings
            SET {", ".join(sets)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params),
        )

    def set_supersedes(self, finding_id: str, supersedes: str) -> None:
        self.execute(
            """
            UPDATE knowledge.findings
            SET supersedes = %s, updated_at = now()
            WHERE id = %s
            """,
            (supersedes, finding_id),
        )

    def set_freshness(self, finding_id: str, freshness: str) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            UPDATE knowledge.findings
            SET freshness = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (freshness, finding_id),
        )

    def list_by_component(
        self, component_id: str, *, version: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            """
            SELECT * FROM knowledge.findings
            WHERE provenance->>'component' = %s
               OR provenance->>'component_id' = %s
            """,
            (component_id, component_id),
        )
        if version is None:
            return rows
        return [
            r
            for r in rows
            if str((r.get("provenance") or {}).get("component_version", ""))
            == str(version)
        ]

    def list_by_mission(
        self, mission_id: str, *, limit: int = 100, include_archive: bool = False
    ) -> list[dict[str, Any]]:
        """Findings *discovered* under a mission (P12 provenance — never an ownership filter).

        Returns active head revisions (one row per canonical_id). Archiving the mission does not
        touch these rows; this read is purely "who discovered this?".
        """
        archive_clause = "" if include_archive else "AND status <> 'archived'"
        return self.fetch_all(
            f"""
            SELECT DISTINCT ON (canonical_id) *
            FROM knowledge.findings
            WHERE mission_id = %s
              {archive_clause}
            ORDER BY canonical_id, revision DESC
            LIMIT %s
            """,
            (mission_id, limit),
        )

    def list_by_job(
        self, job_id: str, *, limit: int = 100, include_archive: bool = False
    ) -> list[dict[str, Any]]:
        """Findings *discovered* under a job (P12 provenance — never an ownership filter)."""
        archive_clause = "" if include_archive else "AND status <> 'archived'"
        return self.fetch_all(
            f"""
            SELECT DISTINCT ON (canonical_id) *
            FROM knowledge.findings
            WHERE job_id = %s
              {archive_clause}
            ORDER BY canonical_id, revision DESC
            LIMIT %s
            """,
            (job_id, limit),
        )

    def list_active_by_repo_uid(
        self, repo_uid: str, *, domain: str = "code"
    ) -> list[dict[str, Any]]:
        """Active/contested/deprecated findings a repository produced (engineering B.2)."""
        return self.fetch_all(
            """
            SELECT * FROM knowledge.findings
            WHERE domain = %s
              AND provenance->>'repo_uid' = %s
              AND status IN ('active', 'contested', 'deprecated')
            """,
            (domain, repo_uid),
        )

    def enqueue_review(
        self, finding_id: str, *, reason: str, component_id: str = ""
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO knowledge.finding_reviews (finding_id, reason, component_id)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (finding_id, reason, component_id),
        )

    def complete_review(
        self,
        finding_id: str,
        *,
        status: str = "done",
        note: str = "",
    ) -> dict[str, Any] | None:
        """Mark the newest pending review for a finding as done/cancelled."""
        del note  # reserved for audit notes if schema grows
        return self.fetch_one(
            """
            UPDATE knowledge.finding_reviews
            SET status = %s
            WHERE id = (
                SELECT id FROM knowledge.finding_reviews
                WHERE finding_id = %s AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING *
            """,
            (status, finding_id),
        )

    def update_verification(
        self,
        finding_id: str,
        *,
        confidence: str,
        confidence_score: float,
        last_verified: str | None,
        freshness: str | None = None,
    ) -> dict[str, Any] | None:
        """Update verification fields without rewriting statement body."""
        if freshness is None:
            return self.fetch_one(
                """
                UPDATE knowledge.findings
                SET confidence = %s,
                    confidence_score = %s,
                    last_verified = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (confidence, confidence_score, last_verified, finding_id),
            )
        return self.fetch_one(
            """
            UPDATE knowledge.findings
            SET confidence = %s,
                confidence_score = %s,
                last_verified = %s,
                freshness = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (confidence, confidence_score, last_verified, freshness, finding_id),
        )

    def list_active(
        self, *, domain: str | None = None, limit: int = 50, include_archive: bool = False
    ) -> list[dict[str, Any]]:
        """Return active head revisions only (one row per canonical_id)."""
        archive_clause = "" if include_archive else "AND status <> 'archived'"
        domain_clause = "AND domain = %s" if domain else ""
        sql = f"""
            SELECT DISTINCT ON (canonical_id) *
            FROM knowledge.findings
            WHERE status IN ('active', 'contested', 'deprecated')
              {archive_clause}
              {domain_clause}
            ORDER BY canonical_id, revision DESC
            LIMIT %s
        """
        if domain:
            return self.fetch_all(sql, (domain, limit))
        return self.fetch_all(sql, (limit,))

    def upsert_from_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Legacy insert path — prefer KnowledgeLifecycleService.consolidate."""
        from atlas.knowledge.lifecycle import finding_identity_key

        return self.create(
            str(data.get("statement", "")),
            canonical_id=data.get("canonical_id") or None,
            revision=int(data.get("revision", 1) or 1),
            value=data.get("value"),
            claim_type=str(data.get("claim_type", "prose") or "prose"),
            confidence=str(data.get("confidence", "UNVERIFIED")),
            confidence_score=float(data.get("confidence_score", 0) or 0),
            status=str(data.get("status", "active") or "active"),
            freshness=str(data.get("freshness", "current") or "current"),
            quality=data.get("quality") if isinstance(data.get("quality"), dict) else {},
            supporting=list(data.get("supporting_sources") or []),
            contradicting=list(data.get("contradicting_sources") or []),
            provenance=data.get("provenance")
            if isinstance(data.get("provenance"), dict)
            else {},
            domain=str(data.get("domain", "research") or "research"),
            last_verified=data.get("last_verified"),
            finding_id=None,
            identity_key=list(finding_identity_key(data)),
        )

    def promote_many(self, findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in findings:
            statement = (item.get("statement") or "").strip()
            if not statement:
                continue
            rows.append(self.upsert_from_dict(item))
        return rows
