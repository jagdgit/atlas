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
    body_fingerprint,
    content_fingerprint,
    decide_lifecycle_transition,
    derive_maturity,
    finding_identity_key,
    independent_source_count,
    merge_confidence,
    merge_confidence_score,
)

# Lineage edge types (mirror atlas.repositories.lineage_repo; kept as literals to avoid importing the
# DB repo into the consolidation core — the lineage recorder is duck-typed).
EDGE_CREATED_BY = "created_by"
EDGE_SUPPORTED_BY = "supported_by"
EDGE_REVISED_BY = "revised_by"
EDGE_SUPERSEDED_BY = "superseded_by"
EDGE_CONTRADICTED_BY = "contradicted_by"


def _source_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("source_id") or entry.get("source") or "")
    return str(entry)


def _sources(raw: Any) -> list[dict[str, Any]]:
    """Normalize a supporting/contradicting field to a list of dict entries."""
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            out.append(entry)
        elif entry:
            out.append({"source_id": str(entry)})
    return out


def _union_sources(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union by source_id, preserving existing order then appending genuinely new sources."""
    seen = {_source_id(e) for e in existing if _source_id(e)}
    merged = list(existing)
    for entry in incoming:
        sid = _source_id(entry)
        if sid and sid not in seen:
            merged.append(entry)
            seen.add(sid)
    return merged


def _evidence_ref(data: dict[str, Any]) -> dict[str, Any]:
    """Best-effort evidence descriptor for a lineage edge (asset/source/reader/provenance)."""
    ref = data.get("evidence_ref")
    if isinstance(ref, dict) and ref:
        return dict(ref)
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    keys = (
        "asset_id", "asset_version", "source", "reader", "reader_version",
        "candidate_id", "mission_id", "job_id", "repo_uid", "path",
    )
    return {k: prov[k] for k in keys if k in prov}


def _observed_at(row: dict[str, Any]) -> Any:
    return (
        row.get("last_verified")
        or row.get("observed_at")
        or row.get("created_at")
        or row.get("updated_at")
    )


def _parse_ts(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_newer(data: dict[str, Any], existing: dict[str, Any]) -> bool:
    """True only when the incoming observation is strictly newer than the existing finding.

    Used to distinguish evolution (newer claim → revise) from same-time conflict (→ contested).
    Unknown timestamps are treated as *not newer* (conservative: prefer contest over silent revise).
    """
    a = _parse_ts(_observed_at(data))
    b = _parse_ts(_observed_at(existing))
    if a is None or b is None:
        return False
    return a > b


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
        lineage=None,
        nn_resolver=None,
        established_min_sources: int = 3,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._enqueue = enqueue
        # Duck-typed lineage recorder (``.record(finding_id, edge_type, ...)``); None → no lineage
        # (back-compatible for callers that predate the evidence graph, C.3b).
        self._lineage = lineage
        # Duck-typed embedding NN resolver (``.resolve(statement,...)`` / ``.index(id, statement)``)
        # for prose semantic dedup (C.3f); None → deterministic identity only.
        self._nn = nn_resolver
        self._established_min_sources = established_min_sources
        self._logger = logger or logging.getLogger("atlas.knowledge.lifecycle")

    # --- SynthesisCapability-adjacent consolidate API -------------------
    def consolidate(
        self, incoming: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Single write path: create, strengthen (evidence-merge), revise, supersede or contest.

        Never overwrites a prior statement body. Evidence accumulation (C.3d): the *same* statement
        seen from a new source strengthens the finding **in place** — one finding, N evidence entries,
        higher confidence, rising maturity — WITHOUT spawning a revision. Revisions are reserved for
        genuine statement/value changes; same-time disagreements become ``contested``.
        """
        data = dict(incoming)
        data["freshness"] = apply_freshness(data, now=now)
        identity = finding_identity_key(data)
        existing = self._store.find_active_by_identity(identity)

        # C.3f hybrid identity: no deterministic match for a *prose* finding → try semantic NN dedup.
        nn_similarity: float | None = None
        if existing is None and self._nn is not None and identity and identity[0] == "prose":
            match = self._resolve_nn(data)
            if match is not None:
                candidate = self._store.get(str(match["finding_id"]))
                if candidate is not None:
                    existing = candidate
                    nn_similarity = match.get("similarity")

        if existing is None:
            row = self._create_new(data)
            self._index_embedding(row, data)
            self._record_lineage(row, EDGE_CREATED_BY, data)
            row["_transition"] = "create"
            return row

        # A semantic (paraphrase) match is the SAME logical finding → merge evidence in place,
        # keeping the established statement (never revise a paraphrase into a new revision).
        if nn_similarity is not None:
            return self._merge_nn(existing, data, similarity=nn_similarity)

        explicit = data.get("transition") or data.get("gold_transition")
        body_changed = body_fingerprint(_row_as_finding_dict(existing)) != body_fingerprint(data)

        # C.3d evidence accumulation / contradiction — only for the implicit path (no explicit
        # transition), so eval fixtures and the revise/supersede APIs keep their exact behavior.
        if not explicit:
            merged = self._accumulate(existing, data, body_changed=body_changed)
            if merged is not None:
                return merged

        changed = (
            content_fingerprint(_row_as_finding_dict(existing))
            != content_fingerprint(data)
        )
        transition = decide_lifecycle_transition(
            existing=existing, incoming=data, content_changed=changed
        )

        if transition == "create":
            row = self._create_new(data)
            self._record_lineage(row, EDGE_CREATED_BY, data)
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
            self._index_embedding(row, data)
            self._record_lineage(row, EDGE_SUPERSEDED_BY, data,
                                 detail={"supersedes": str(existing["id"])})
            row["_transition"] = "supersede"
            return row

        if transition == "split_contested":
            # Contested split: revise head as contested; do not average.
            data["status"] = STATUS_CONTESTED
            row = self._store.append_revision(existing, data)
            row = dict(row)
            self._record_lineage(row, EDGE_CONTRADICTED_BY, data)
            row["_transition"] = "split_contested"
            return row

        # revise (default for a genuine body change)
        row = self._store.append_revision(existing, data)
        row = dict(row)
        self._index_embedding(row, data)
        self._record_lineage(row, EDGE_REVISED_BY, data,
                             detail={"supersedes": str(existing["id"])})
        row["_transition"] = "revise"
        return row

    # --- C.3d evidence accumulation ------------------------------------
    def _accumulate(
        self, existing: dict[str, Any], data: dict[str, Any], *, body_changed: bool
    ) -> dict[str, Any] | None:
        """Strengthen/contest a finding in place when only the *evidence* changed.

        Returns the updated row (with ``_transition``) when it handled the observation, else ``None``
        to defer to the transition machine (create/noop/revise/supersede).
        """
        # In-place merge needs the richer store API; minimal stores fall back to the machine.
        if not hasattr(self._store, "update_evidence"):
            return None

        existing_support = _sources(existing.get("supporting") or existing.get("supporting_sources"))
        existing_contra = _sources(existing.get("contradicting") or existing.get("contradicting_sources"))
        incoming_support = _sources(data.get("supporting_sources") or data.get("supporting"))
        incoming_contra = _sources(data.get("contradicting_sources") or data.get("contradicting"))

        if body_changed:
            # A genuine body change: evolution (newer → revise via machine) vs conflict (same-time
            # disagreement → contested). Only intervene when there's an actual contradiction signal.
            if not (incoming_contra or data.get("conflict")):
                return None
            if _is_newer(data, existing):
                return None  # newer claim → let the machine revise/supersede (evolution)
            contested = {**data, "transition": "split_contested", "status": STATUS_CONTESTED}
            row = self._store.append_revision(existing, contested)
            row = dict(row)
            self._record_lineage(row, EDGE_CONTRADICTED_BY, data)
            row["_transition"] = "split_contested"
            return row

        # Same body — new contradicting evidence → contest in place, no averaging.
        known_contra = {_source_id(c) for c in existing_contra}
        new_contra = [c for c in incoming_contra if _source_id(c) not in known_contra]
        if new_contra:
            merged_contra = existing_contra + new_contra
            merged_support = _union_sources(existing_support, incoming_support)
            row = self._store.update_evidence(
                str(existing["id"]),
                supporting=merged_support,
                contradicting=merged_contra,
                status=STATUS_CONTESTED,
                last_verified=data.get("last_verified"),
            ) or existing
            row = dict(row)
            self._record_lineage(row, EDGE_CONTRADICTED_BY, data)
            row["_transition"] = "contested"
            return row

        # Same body — new supporting evidence → strengthen in place (no revision).
        merged_support = _union_sources(existing_support, incoming_support)
        if len(merged_support) > len(existing_support):
            count = independent_source_count(merged_support)
            confidence = merge_confidence(
                existing=existing.get("confidence"),
                incoming=data.get("confidence"),
                source_count=count,
            )
            score = merge_confidence_score(
                existing=float(existing.get("confidence_score") or 0),
                incoming=float(data.get("confidence_score") or 0),
                source_count=count,
            )
            maturity = derive_maturity(
                supporting_count=count,
                confidence=confidence,
                established_min_sources=self._established_min_sources,
            )
            row = self._store.update_evidence(
                str(existing["id"]),
                supporting=merged_support,
                confidence=confidence,
                confidence_score=score,
                maturity=maturity,
                last_verified=data.get("last_verified"),
            ) or existing
            row = dict(row)
            self._record_lineage(
                row, EDGE_SUPPORTED_BY, data,
                detail={"sources": count, "confidence": confidence, "maturity": maturity},
            )
            row["_transition"] = "merge_evidence"
            return row

        # Same body, no new supporting/contradicting evidence (a repeat or a subset of what we already
        # know) → a definitive no-op. We must handle it here rather than defer: the transition machine
        # compares the *full* content fingerprint (which includes the supporting set), so a re-observation
        # of one already-known source on a multi-source finding would otherwise look "changed" and spawn
        # a spurious revision that discards the accumulated evidence.
        existing = dict(existing)
        existing["_transition"] = "noop"
        return existing

    # --- C.3f semantic (embedding NN) identity ------------------------
    def _resolve_nn(self, data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._nn.resolve(
                str(data.get("statement", "")),
                domain=str(data.get("domain", "research") or "research"),
            )
        except Exception as exc:  # noqa: BLE001 - NN is best-effort; fall back to create
            self._logger.warning("nn resolve failed: %s", exc)
            return None

    def _index_embedding(self, row: dict[str, Any], data: dict[str, Any]) -> None:
        if self._nn is None:
            return
        try:
            self._nn.index(str(row["id"]), str(data.get("statement", "")))
        except Exception as exc:  # noqa: BLE001 - never block a write on indexing
            self._logger.warning("nn index failed: %s", exc)

    def _merge_nn(
        self, existing: dict[str, Any], data: dict[str, Any], *, similarity: float
    ) -> dict[str, Any]:
        """Merge a paraphrase's evidence into the matched finding (keep its statement)."""
        existing_support = _sources(existing.get("supporting") or existing.get("supporting_sources"))
        incoming_support = _sources(data.get("supporting_sources") or data.get("supporting"))
        if not incoming_support:
            # A document-derived prose finding often has no explicit sources — synthesize one from
            # the evidence descriptor so the corroboration is still recorded.
            ev = _evidence_ref(data)
            sid = ev.get("asset_id") or ev.get("source") or str(data.get("statement", ""))[:48]
            incoming_support = [{
                "source_id": str(sid),
                "evidence_level": 2,
                "snippet": str(data.get("statement", ""))[:200],
            }]
        merged_support = _union_sources(existing_support, incoming_support)

        if not hasattr(self._store, "update_evidence") or len(merged_support) <= len(existing_support):
            row = dict(existing)
            row["_transition"] = "noop"
            return row

        count = independent_source_count(merged_support)
        confidence = merge_confidence(
            existing=existing.get("confidence"),
            incoming=data.get("confidence"),
            source_count=count,
        )
        score = merge_confidence_score(
            existing=float(existing.get("confidence_score") or 0),
            incoming=float(data.get("confidence_score") or 0),
            source_count=count,
        )
        maturity = derive_maturity(
            supporting_count=count,
            confidence=confidence,
            established_min_sources=self._established_min_sources,
        )
        row = self._store.update_evidence(
            str(existing["id"]),
            supporting=merged_support,
            confidence=confidence,
            confidence_score=score,
            maturity=maturity,
            last_verified=data.get("last_verified"),
        ) or existing
        row = dict(row)
        self._record_lineage(
            row, EDGE_SUPPORTED_BY, data,
            detail={"sources": count, "confidence": confidence,
                    "maturity": maturity, "nn_similarity": similarity},
        )
        row["_transition"] = "merge_evidence"
        return row

    def _record_lineage(
        self,
        row: dict[str, Any],
        edge_type: str,
        data: dict[str, Any],
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self._lineage is None:
            return
        try:
            self._lineage.record(
                str(row["id"]),
                edge_type,
                canonical_id=str(row.get("canonical_id") or "") or None,
                revision=int(row.get("revision") or 1),
                evidence_ref=_evidence_ref(data),
                detail=detail or {},
            )
        except Exception as exc:  # noqa: BLE001 - lineage is best-effort audit, never blocks a write
            self._logger.warning("lineage record failed: %s", exc)

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
        supporting = list(data.get("supporting_sources") or data.get("supporting") or [])
        confidence = str(data.get("confidence", "UNVERIFIED"))
        maturity = derive_maturity(
            supporting_count=independent_source_count(supporting),
            confidence=confidence,
            established_min_sources=self._established_min_sources,
        )
        return self._store.create(
            str(data.get("statement", "")),
            canonical_id=data.get("canonical_id") or None,
            revision=1,
            value=data.get("value"),
            claim_type=str(data.get("claim_type", "prose") or "prose"),
            confidence=confidence,
            confidence_score=float(data.get("confidence_score", 0) or 0),
            status=str(data.get("status", STATUS_ACTIVE) or STATUS_ACTIVE),
            freshness=str(data.get("freshness", "current")),
            quality=data.get("quality") if isinstance(data.get("quality"), dict) else {},
            supporting=supporting,
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
            maturity=maturity,
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
            "maturity": kwargs.get("maturity", "candidate"),
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

    def set_maturity(self, finding_id: str, maturity: str) -> dict[str, Any] | None:
        row = self.rows.get(finding_id)
        if not row:
            return None
        row["maturity"] = maturity
        row["updated_at"] = _utcnow_iso()
        return dict(row)

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
        """Merge evidence in place — no new revision (mirrors FindingRepository.update_evidence)."""
        row = self.rows.get(finding_id)
        if not row:
            return None
        row["supporting"] = list(supporting)
        if confidence is not None:
            row["confidence"] = confidence
        if confidence_score is not None:
            row["confidence_score"] = float(confidence_score)
        if maturity is not None:
            row["maturity"] = maturity
        if contradicting is not None:
            row["contradicting"] = list(contradicting)
        if status is not None:
            row["status"] = status
        if last_verified is not None:
            row["last_verified"] = last_verified
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
