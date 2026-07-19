"""Experience-store adapter over ``learning.experiences`` (Phase C · §C.6, CC6).

The Knowledge Consolidator (:class:`atlas.knowledge.consolidation.KnowledgeLifecycleService`) binds to
a duck-typed ``FindingStore`` — it never assumes ``knowledge.findings``. This adapter implements that
same surface over ``learning.experiences`` so owner **experiences** become cumulative exactly like
knowledge (P13): the *same* skill/technology + context seen across many projects strengthens ONE
experience (evidence-merge, rising confidence + maturity) instead of writing N rows.

Mapping ``knowledge.findings`` finding-dict ⇄ ``learning.experiences`` columns:
  * ``statement``            ⇄ ``title``
  * ``supporting``           ⇄ ``evidence``
  * ``value/provenance/…``   ⇄ ``payload`` (JSON side-car; keeps the base experience columns clean)
  * everything else (identity_key, canonical_id, revision, contradicting, confidence[_score],
    corroboration_count, maturity, superseded_by, status) is a first-class column (migration 0037).

Freshness / component-review hooks are inert for experiences (they have no scheduled re-verification),
so those Protocol methods are safe no-ops.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from atlas.knowledge.lifecycle import independent_source_count
from atlas.repositories.base import BaseRepository

_ACTIVE = ("active", "contested")
_HEAD = ("active", "contested", "deprecated")


class ExperienceStore(BaseRepository):
    """``FindingStore``-shaped view of ``learning.experiences`` for the shared consolidator."""

    # --- identity / creation ------------------------------------------
    def next_canonical_id(self) -> str:
        return f"XP-{uuid4().hex[:12]}"

    def create(
        self,
        statement: str,
        *,
        canonical_id: str | None = None,
        revision: int = 1,
        value: dict[str, Any] | None = None,
        claim_type: str = "experience",
        confidence: str = "UNVERIFIED",
        confidence_score: float = 0.0,
        status: str = "active",
        freshness: str = "current",
        quality: dict[str, Any] | None = None,
        supporting: list[dict[str, Any]] | None = None,
        contradicting: list[dict[str, Any]] | None = None,
        provenance: dict[str, Any] | None = None,
        domain: str = "experience",
        last_verified: str | None = None,
        identity_key: list[Any] | None = None,
        maturity: str = "candidate",
        policy: str = "project",
        **_ignore: Any,
    ) -> dict[str, Any]:
        cid = canonical_id or self.next_canonical_id()
        supporting = supporting or []
        prov = provenance if isinstance(provenance, dict) else {}
        payload = {
            "value": value,
            "provenance": prov,
            "domain": domain,
            "claim_type": claim_type,
            "freshness": freshness,
            "quality": quality or {},
            "last_verified": last_verified,
        }
        row = self.fetch_one(
            """
            INSERT INTO learning.experiences (
                title, policy, status, payload, source_job_id,
                identity_key, canonical_id, revision, evidence, contradicting,
                confidence, confidence_score, corroboration_count, maturity, superseded_by
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                statement,
                policy,
                status,
                Jsonb(payload),
                prov.get("job_id"),
                Jsonb(list(identity_key)) if identity_key is not None else None,
                cid,
                revision,
                Jsonb(supporting),
                Jsonb(contradicting or []),
                confidence,
                confidence_score,
                independent_source_count(supporting),
                maturity,
                None,
            ),
        )
        return self._as_finding(row)

    def append_revision(
        self, previous: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        """Append a new revision reusing the canonical id; mark the previous superseded."""
        from atlas.knowledge.lifecycle import finding_identity_key

        new = self.create(
            str(data.get("statement", previous.get("statement", ""))),
            canonical_id=str(previous["canonical_id"]),
            revision=int(previous.get("revision", 1)) + 1,
            value=data.get("value", previous.get("value")),
            claim_type=str(data.get("claim_type", previous.get("claim_type", "experience"))),
            confidence=str(data.get("confidence", previous.get("confidence", "UNVERIFIED"))),
            confidence_score=float(
                data.get("confidence_score", previous.get("confidence_score", 0)) or 0
            ),
            status=str(data.get("status", "active") or "active"),
            freshness=str(data.get("freshness", previous.get("freshness", "current"))),
            quality=data.get("quality")
            if isinstance(data.get("quality"), dict)
            else (previous.get("quality") or {}),
            supporting=list(data.get("supporting_sources") or data.get("supporting") or []),
            contradicting=list(
                data.get("contradicting_sources") or data.get("contradicting") or []
            ),
            provenance=data.get("provenance")
            if isinstance(data.get("provenance"), dict)
            else (previous.get("provenance") or {}),
            domain=str(data.get("domain", previous.get("domain", "experience"))),
            last_verified=data.get("last_verified"),
            identity_key=list(finding_identity_key(data)),
        )
        self.set_status(str(previous["id"]), "superseded", superseded_by=str(new["id"]))
        return new

    # --- reads ---------------------------------------------------------
    def get(self, finding_id: str) -> dict[str, Any] | None:
        return self._as_finding(
            self.fetch_one("SELECT * FROM learning.experiences WHERE id = %s", (finding_id,))
        )

    def get_head(
        self, canonical_id: str, *, include_archive: bool = False
    ) -> dict[str, Any] | None:
        if include_archive:
            return self._as_finding(self.fetch_one(
                "SELECT * FROM learning.experiences WHERE canonical_id = %s "
                "ORDER BY revision DESC LIMIT 1",
                (canonical_id,),
            ))
        return self._as_finding(self.fetch_one(
            "SELECT * FROM learning.experiences WHERE canonical_id = %s "
            "AND status IN ('active', 'contested', 'deprecated') "
            "ORDER BY revision DESC LIMIT 1",
            (canonical_id,),
        ))

    def find_active_by_identity(self, identity: tuple[Any, ...]) -> dict[str, Any] | None:
        return self._as_finding(self.fetch_one(
            """
            SELECT * FROM learning.experiences
            WHERE identity_key = %s::jsonb
              AND status IN ('active', 'contested')
            ORDER BY revision DESC
            LIMIT 1
            """,
            (Jsonb(list(identity)),),
        ))

    # --- writes --------------------------------------------------------
    def set_status(
        self, finding_id: str, status: str, *, superseded_by: str | None = None
    ) -> dict[str, Any] | None:
        if superseded_by is not None:
            return self._as_finding(self.fetch_one(
                "UPDATE learning.experiences SET status = %s, superseded_by = %s, "
                "updated_at = now() WHERE id = %s RETURNING *",
                (status, superseded_by, finding_id),
            ))
        return self._as_finding(self.fetch_one(
            "UPDATE learning.experiences SET status = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (status, finding_id),
        ))

    def set_maturity(self, finding_id: str, maturity: str) -> dict[str, Any] | None:
        return self._as_finding(self.fetch_one(
            "UPDATE learning.experiences SET maturity = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (maturity, finding_id),
        ))

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
        """Strengthen/contest an experience in place — NO new revision (C.3d evidence-merge)."""
        sets = [
            "evidence = %s",
            "corroboration_count = %s",
            "updated_at = now()",
        ]
        params: list[Any] = [Jsonb(supporting), independent_source_count(supporting)]
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
        params.append(finding_id)
        return self._as_finding(self.fetch_one(
            f"UPDATE learning.experiences SET {', '.join(sets)} WHERE id = %s RETURNING *",
            tuple(params),
        ))

    # --- inert Protocol hooks (experiences have no scheduled re-verification) --
    def set_freshness(self, finding_id: str, freshness: str) -> dict[str, Any] | None:
        return self.get(finding_id)

    def list_by_component(
        self, component_id: str, *, version: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    def enqueue_review(
        self, finding_id: str, *, reason: str, component_id: str = ""
    ) -> dict[str, Any]:
        return {"finding_id": finding_id, "reason": reason, "component_id": component_id}

    # --- mapping -------------------------------------------------------
    def _as_finding(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Present a ``learning.experiences`` row in the consolidator's finding-dict shape."""
        if row is None:
            return None
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return {
            "id": str(row["id"]),
            "statement": row.get("title") or "",
            "value": payload.get("value"),
            "claim_type": payload.get("claim_type", "experience"),
            "domain": payload.get("domain", "experience"),
            "confidence": row.get("confidence") or "UNVERIFIED",
            "confidence_score": float(row.get("confidence_score") or 0),
            "status": row.get("status") or "active",
            "maturity": row.get("maturity") or "candidate",
            "supporting": list(row.get("evidence") or []),
            "contradicting": list(row.get("contradicting") or []),
            "provenance": payload.get("provenance") or {},
            "identity_key": list(row.get("identity_key") or []),
            "canonical_id": row.get("canonical_id"),
            "revision": int(row.get("revision") or 1),
            "superseded_by": str(row["superseded_by"]) if row.get("superseded_by") else None,
            "corroboration_count": int(row.get("corroboration_count") or 0),
            "last_verified": payload.get("last_verified"),
            "freshness": payload.get("freshness", "current"),
            "quality": payload.get("quality") or {},
            "policy": row.get("policy"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
