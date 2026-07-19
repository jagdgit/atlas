"""Knowledge consolidation — append-only Finding revisions (Stage 3B.3).

Never overwrite statement bodies in place. Content changes append a revision with
``supersedes`` / ``superseded_by`` links (D3B.27).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence
from uuid import uuid4

from atlas.knowledge.lifecycle import (
    ACTIVE_STATUSES,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_CONTESTED,
    STATUS_DEPRECATED,
    STATUS_SUPERSEDED,
    apply_freshness,
    content_fingerprint,
    decide_lifecycle_transition,
    finding_identity_key,
)


class FindingStore(Protocol):
    def next_canonical_id(self) -> str: ...
    def create(self, statement: str, **kwargs: Any) -> dict[str, Any]: ...
    def get(self, finding_id: str) -> dict[str, Any] | None: ...
    def get_head(self, canonical_id: str, *, include_archive: bool = False) -> dict[str, Any] | None: ...
    def find_active_by_identity(self, identity: tuple[Any, ...]) -> dict[str, Any] | None: ...
    def append_revision(self, previous: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]: ...
    def set_status(self, finding_id: str, status: str, *, superseded_by: str | None = None) -> dict[str, Any] | None: ...
    def set_freshness(self, finding_id: str, freshness: str) -> dict[str, Any] | None: ...
    def list_by_component(self, component_id: str, *, version: str | None = None) -> list[dict[str, Any]]: ...
    def enqueue_review(self, finding_id: str, *, reason: str, component_id: str = "") -> dict[str, Any]: ...


class KnowledgeLifecycleService:
    """``KnowledgeLifecycleCapability`` — revise / supersede / archive / invalidate."""

    name = "knowledge_lifecycle"

    def __init__(
        self,
        store: FindingStore,
        *,
        enqueue=None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._enqueue = enqueue
        self._logger = logger or logging.getLogger("atlas.knowledge.lifecycle")

    # --- SynthesisCapability-adjacent consolidate API -------------------
    def consolidate(
        self, incoming: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Create or append-revision a finding; never overwrites prior statement."""
        data = dict(incoming)
        data["freshness"] = apply_freshness(data, now=now)
        identity = finding_identity_key(data)
        existing = self._store.find_active_by_identity(identity)
        changed = (
            existing is not None
            and content_fingerprint(_row_as_finding_dict(existing))
            != content_fingerprint(data)
        )
        transition = decide_lifecycle_transition(
            existing=existing, incoming=data, content_changed=changed
        )

        if transition == "create" or existing is None:
            row = self._create_new(data)
            row["_transition"] = "create"
            return row

        if transition == "noop":
            existing = dict(existing)
            existing["_transition"] = "noop"
            return existing

        if transition == "archive":
            row = self._store.set_status(str(existing["id"]), STATUS_ARCHIVED) or existing
            row = dict(row)
            row["_transition"] = "archive"
            return row

        if transition == "supersede":
            row = self._supersede(existing, data)
            row["_transition"] = "supersede"
            return row

        if transition == "split_contested":
            # Contested split: revise head as contested; do not average.
            data["status"] = STATUS_CONTESTED
            row = self._store.append_revision(existing, data)
            row = dict(row)
            row["_transition"] = "split_contested"
            return row

        # revise (default for content change)
        row = self._store.append_revision(existing, data)
        row = dict(row)
        row["_transition"] = "revise"
        return row

    def revise(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Capability contract: revise an existing finding with new evidence/content."""
        incoming = args[0] if args else kwargs.get("incoming") or kwargs
        if not isinstance(incoming, dict):
            raise TypeError("revise expects a finding dict")
        incoming = {**incoming, "transition": "revise"}
        return self.consolidate(incoming)

    def supersede(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Capability contract: supersede prior head with a replacement finding."""
        incoming = args[0] if args else kwargs.get("incoming") or kwargs
        if not isinstance(incoming, dict):
            raise TypeError("supersede expects a finding dict")
        incoming = {**incoming, "transition": "supersede"}
        return self.consolidate(incoming)

    def archive(self, finding_id: str) -> dict[str, Any] | None:
        return self._store.set_status(finding_id, STATUS_ARCHIVED)

    def deprecate(self, finding_id: str) -> dict[str, Any] | None:
        return self._store.set_status(finding_id, STATUS_DEPRECATED)

    def reactivate(self, finding_id: str) -> dict[str, Any] | None:
        row = self._store.get(finding_id)
        if row is None:
            return None
        status = STATUS_CONTESTED if row.get("contradicting") not in (None, [], {}) else STATUS_ACTIVE
        return self._store.set_status(finding_id, status)

    def invalidate_component(
        self,
        component_id: str,
        *,
        version: str | None = None,
        reason: str = "component bug",
    ) -> dict[str, Any]:
        """Mark descendant findings stale and enqueue review (D3B.19)."""
        rows = self._store.list_by_component(component_id, version=version)
        stale_ids: list[str] = []
        for row in rows:
            fid = str(row["id"])
            self._store.set_freshness(fid, "stale")
            self._store.enqueue_review(fid, reason=reason, component_id=component_id)
            stale_ids.append(fid)
            if self._enqueue is not None:
                try:
                    self._enqueue(
                        "review_finding",
                        {
                            "finding_id": fid,
                            "reason": reason,
                            "component_id": component_id,
                            "component_version": version,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("enqueue review_finding failed: %s", exc)
        return {
            "component_id": component_id,
            "version": version,
            "stale_count": len(stale_ids),
            "finding_ids": stale_ids,
        }

    def review_finding(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """Scheduler handler: re-verify a stale finding and refresh verification fields.

        Does not overwrite statement bodies — only confidence / freshness /
        last_verified (and marks the review row done).
        """
        data = dict(payload or {})
        data.update(kwargs)
        finding_id = str(data.get("finding_id") or "")
        if not finding_id:
            return {"status": "error", "reason": "missing finding_id"}
        row = self._store.get(finding_id)
        if row is None:
            return {"status": "missing", "finding_id": finding_id}

        from atlas.evidence.models import Claim
        from atlas.verification.engine import VerificationEngine

        claim_ids = (row.get("provenance") or {}).get("claim_ids") or []
        claim_id = (
            str(claim_ids[0])
            if isinstance(claim_ids, list) and claim_ids
            else f"review:{finding_id}"
        )
        claim = Claim.from_dict(
            {
                "id": claim_id,
                "statement": row.get("statement", ""),
                "value": row.get("value"),
                "supporting_sources": list(
                    row.get("supporting") or row.get("supporting_sources") or []
                ),
                "contradicting_sources": list(
                    row.get("contradicting") or row.get("contradicting_sources") or []
                ),
            }
        )

        VerificationEngine().verify_claim(claim)
        freshness = "current"
        if claim.confidence in {"INSUFFICIENT", "UNVERIFIED"}:
            freshness = "stale"
        elif row.get("freshness") == "stale" and claim.confidence in {"HIGH", "MEDIUM"}:
            freshness = "current"

        updated = None
        if hasattr(self._store, "update_verification"):
            updated = self._store.update_verification(
                finding_id,
                confidence=claim.confidence,
                confidence_score=float(claim.confidence_score or 0.0),
                last_verified=claim.last_verified or _utcnow_iso(),
                freshness=freshness,
            )
        else:
            self._store.set_freshness(finding_id, freshness)
            updated = self._store.get(finding_id)

        review_row = None
        if hasattr(self._store, "complete_review"):
            review_row = self._store.complete_review(
                finding_id, status="done", note=data.get("reason") or ""
            )

        self._logger.info(
            "reviewed finding %s → confidence=%s freshness=%s",
            finding_id,
            claim.confidence,
            freshness,
        )
        return {
            "status": "done",
            "finding_id": finding_id,
            "confidence": claim.confidence,
            "confidence_score": claim.confidence_score,
            "freshness": freshness,
            "finding": updated,
            "review": review_row,
            "reasoning_trace": list(claim.reasoning_trace or []),
        }

    def promote_many(self, findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Consolidate a batch (used by research promote)."""
        out: list[dict[str, Any]] = []
        for item in findings:
            statement = (item.get("statement") or "").strip()
            if not statement:
                continue
            out.append(self.consolidate(item))
        return out

    def _create_new(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._store.create(
            str(data.get("statement", "")),
            canonical_id=data.get("canonical_id") or None,
            revision=1,
            value=data.get("value"),
            claim_type=str(data.get("claim_type", "prose") or "prose"),
            confidence=str(data.get("confidence", "UNVERIFIED")),
            confidence_score=float(data.get("confidence_score", 0) or 0),
            status=str(data.get("status", STATUS_ACTIVE) or STATUS_ACTIVE),
            freshness=str(data.get("freshness", "current")),
            quality=data.get("quality") if isinstance(data.get("quality"), dict) else {},
            supporting=list(data.get("supporting_sources") or data.get("supporting") or []),
            contradicting=list(
                data.get("contradicting_sources") or data.get("contradicting") or []
            ),
            provenance=data.get("provenance")
            if isinstance(data.get("provenance"), dict)
            else {},
            domain=str(data.get("domain", "research") or "research"),
            last_verified=data.get("last_verified") or _utcnow_iso(),
            finding_id=None,  # always new UUID for durable create
            identity_key=list(finding_identity_key(data)),
        )

    def _supersede(self, existing: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """New canonical finding replaces prior; old head marked superseded."""
        new = self._create_new({**data, "canonical_id": None})
        self._store.set_status(
            str(existing["id"]), STATUS_SUPERSEDED, superseded_by=str(new["id"])
        )
        # Link new.supersedes → old for traceability
        if hasattr(self._store, "set_supersedes"):
            self._store.set_supersedes(str(new["id"]), str(existing["id"]))
        return new


def _row_as_finding_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a DB/fake row into the fingerprint/identity dict shape."""
    supporting = row.get("supporting") or row.get("supporting_sources") or []
    contradicting = row.get("contradicting") or row.get("contradicting_sources") or []
    if hasattr(supporting, "__iter__") and not isinstance(supporting, (list, tuple)):
        supporting = list(supporting) if supporting is not None else []
    return {
        "statement": row.get("statement", ""),
        "value": row.get("value"),
        "domain": row.get("domain", "research"),
        "confidence": row.get("confidence", ""),
        "status": row.get("status", ""),
        "claim_type": row.get("claim_type", ""),
        "supporting_sources": list(supporting or []),
        "contradicting_sources": list(contradicting or []),
        "provenance": row.get("provenance") or {},
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class InMemoryFindingStore:
    """Hermetic store for unit tests (append-only revisions)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.reviews: list[dict[str, Any]] = []
        self._seq = 0

    def next_canonical_id(self) -> str:
        self._seq += 1
        return f"F-{self._seq:06d}"

    def create(self, statement: str, **kwargs: Any) -> dict[str, Any]:
        fid = str(kwargs.get("finding_id") or uuid4())
        cid = kwargs.get("canonical_id") or self.next_canonical_id()
        row = {
            "id": fid,
            "canonical_id": cid,
            "revision": int(kwargs.get("revision", 1) or 1),
            "statement": statement,
            "value": kwargs.get("value"),
            "claim_type": kwargs.get("claim_type", "prose"),
            "confidence": kwargs.get("confidence", "UNVERIFIED"),
            "confidence_score": float(kwargs.get("confidence_score", 0) or 0),
            "status": kwargs.get("status", STATUS_ACTIVE),
            "freshness": kwargs.get("freshness", "current"),
            "quality": kwargs.get("quality") or {},
            "supporting": kwargs.get("supporting") or [],
            "contradicting": kwargs.get("contradicting") or [],
            "provenance": kwargs.get("provenance") or {},
            "domain": kwargs.get("domain", "research"),
            "last_verified": kwargs.get("last_verified"),
            "supersedes": kwargs.get("supersedes"),
            "superseded_by": kwargs.get("superseded_by"),
            "identity_key": kwargs.get("identity_key"),
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
        }
        self.rows[fid] = row
        return dict(row)

    def get(self, finding_id: str) -> dict[str, Any] | None:
        row = self.rows.get(finding_id)
        return dict(row) if row else None

    def get_head(
        self, canonical_id: str, *, include_archive: bool = False
    ) -> dict[str, Any] | None:
        candidates = [
            r for r in self.rows.values() if r["canonical_id"] == canonical_id
        ]
        if not include_archive:
            candidates = [r for r in candidates if r["status"] != STATUS_ARCHIVED]
        # Prefer non-superseded heads
        live = [r for r in candidates if r["status"] in ACTIVE_STATUSES | {STATUS_DEPRECATED}]
        pool = live or candidates
        if not pool:
            return None
        best = max(pool, key=lambda r: int(r.get("revision", 1)))
        return dict(best)

    def find_active_by_identity(self, identity: tuple[Any, ...]) -> dict[str, Any] | None:
        matches = [
            r
            for r in self.rows.values()
            if tuple(r.get("identity_key") or ()) == identity
            and r["status"] in ACTIVE_STATUSES
        ]
        if not matches:
            return None
        best = max(matches, key=lambda r: int(r.get("revision", 1)))
        return dict(best)

    def append_revision(
        self, previous: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        new = self.create(
            str(data.get("statement", previous.get("statement", ""))),
            canonical_id=previous["canonical_id"],
            revision=int(previous.get("revision", 1)) + 1,
            value=data.get("value", previous.get("value")),
            claim_type=str(data.get("claim_type", previous.get("claim_type", "prose"))),
            confidence=str(data.get("confidence", previous.get("confidence", "UNVERIFIED"))),
            confidence_score=float(
                data.get("confidence_score", previous.get("confidence_score", 0)) or 0
            ),
            status=str(data.get("status", STATUS_ACTIVE) or STATUS_ACTIVE),
            freshness=str(data.get("freshness", previous.get("freshness", "current"))),
            quality=data.get("quality") if isinstance(data.get("quality"), dict) else previous.get("quality") or {},
            supporting=list(data.get("supporting_sources") or data.get("supporting") or []),
            contradicting=list(
                data.get("contradicting_sources") or data.get("contradicting") or []
            ),
            provenance=data.get("provenance")
            if isinstance(data.get("provenance"), dict)
            else previous.get("provenance") or {},
            domain=str(data.get("domain", previous.get("domain", "research"))),
            last_verified=data.get("last_verified") or _utcnow_iso(),
            supersedes=previous["id"],
            identity_key=list(finding_identity_key(data))
            if data.get("statement")
            else previous.get("identity_key"),
        )
        self.set_status(previous["id"], STATUS_SUPERSEDED, superseded_by=new["id"])
        return new

    def set_status(
        self, finding_id: str, status: str, *, superseded_by: str | None = None
    ) -> dict[str, Any] | None:
        row = self.rows.get(finding_id)
        if not row:
            return None
        row["status"] = status
        if superseded_by is not None:
            row["superseded_by"] = superseded_by
        row["updated_at"] = _utcnow_iso()
        return dict(row)

    def set_supersedes(self, finding_id: str, supersedes: str) -> None:
        row = self.rows.get(finding_id)
        if row:
            row["supersedes"] = supersedes

    def set_freshness(self, finding_id: str, freshness: str) -> dict[str, Any] | None:
        row = self.rows.get(finding_id)
        if not row:
            return None
        row["freshness"] = freshness
        row["updated_at"] = _utcnow_iso()
        return dict(row)

    def list_by_component(
        self, component_id: str, *, version: str | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for row in self.rows.values():
            prov = row.get("provenance") or {}
            if not isinstance(prov, dict):
                continue
            if prov.get("component") != component_id and prov.get("component_id") != component_id:
                continue
            if version is not None and str(prov.get("component_version", "")) != str(version):
                continue
            out.append(dict(row))
        return out

    def enqueue_review(
        self, finding_id: str, *, reason: str, component_id: str = ""
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid4()),
            "finding_id": finding_id,
            "reason": reason,
            "component_id": component_id,
            "status": "pending",
            "created_at": _utcnow_iso(),
        }
        self.reviews.append(item)
        return item

    def complete_review(
        self, finding_id: str, *, status: str = "done", note: str = ""
    ) -> dict[str, Any] | None:
        del note
        for review in reversed(self.reviews):
            if review["finding_id"] == finding_id and review.get("status") == "pending":
                review["status"] = status
                return dict(review)
        return None

    def update_verification(
        self,
        finding_id: str,
        *,
        confidence: str,
        confidence_score: float,
        last_verified: str | None,
        freshness: str | None = None,
    ) -> dict[str, Any] | None:
        row = self.rows.get(finding_id)
        if not row:
            return None
        row["confidence"] = confidence
        row["confidence_score"] = float(confidence_score or 0)
        row["last_verified"] = last_verified
        if freshness is not None:
            row["freshness"] = freshness
        row["updated_at"] = _utcnow_iso()
        return dict(row)

    def list_active_heads(self, *, include_archive: bool = False) -> list[dict[str, Any]]:
        by_canon: dict[str, dict[str, Any]] = {}
        for row in self.rows.values():
            if not include_archive and row["status"] == STATUS_ARCHIVED:
                continue
            if row["status"] == STATUS_SUPERSEDED:
                continue
            cid = row["canonical_id"]
            prev = by_canon.get(cid)
            if prev is None or int(row["revision"]) > int(prev["revision"]):
                by_canon[cid] = row
        return [dict(r) for r in by_canon.values()]
