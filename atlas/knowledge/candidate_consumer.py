"""Candidate → Consolidator → Finding (Phase C · §C.3, CC11 / P11/P13).

The **only** path from a knowledge candidate to a durable finding. Readers/extractors emit candidates
(the transient inbox, ``knowledge.candidates``); this consumer is the single component that reads them
and calls ``KnowledgeLifecycleService.consolidate()`` — so readers never write ``knowledge.findings``
directly (P11), and the same fact seen many ways becomes one cumulative finding (P13).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CandidateConsumer:
    """Emit candidates and consolidate them into findings (the single write path's front door)."""

    name = "candidate_consumer"

    def __init__(
        self,
        store: Any,
        consolidator: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store              # CandidateRepository | InMemoryCandidateStore
        self._consolidator = consolidator  # KnowledgeLifecycleService
        self._logger = logger or logging.getLogger("atlas.knowledge.candidate_consumer")

    # --- emit ----------------------------------------------------------
    def emit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one candidate observation (from a reader/extractor)."""
        return self._store.create(
            str(payload["statement"]),
            claim_type=str(payload.get("claim_type", "prose")),
            domain=str(payload.get("domain", "external")),
            value=payload.get("value"),
            evidence_ref=payload.get("evidence_ref") or {},
            provenance=payload.get("provenance") or {},
            confidence=payload.get("confidence"),
            confidence_score=payload.get("confidence_score"),
            reader=payload.get("reader"),
            reader_version=payload.get("reader_version"),
            mission_id=payload.get("mission_id"),
            job_id=payload.get("job_id"),
        )

    def emit_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.emit(p) for p in payloads]

    # --- consume -------------------------------------------------------
    def consume(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Consolidate one candidate into a finding and mark it consumed."""
        finding = self._to_finding(candidate)
        row = self._consolidator.consolidate(finding)
        finding_id = str(row.get("id")) if row.get("id") is not None else None
        try:
            self._store.mark_consumed(candidate["id"], finding_id=finding_id)
        except Exception as exc:  # noqa: BLE001 - the finding is written; consumption bookkeeping is best-effort
            self._logger.warning("mark_consumed failed for %s: %s", candidate.get("id"), exc)
        return {
            "candidate_id": str(candidate["id"]),
            "finding_id": finding_id,
            "transition": row.get("_transition"),
            "finding": row,
        }

    def consume_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Drain the pending candidate inbox through the Consolidator."""
        return [self.consume(c) for c in self._store.list_pending(limit=limit)]

    # --- internals -----------------------------------------------------
    def _to_finding(self, candidate: dict[str, Any]) -> dict[str, Any]:
        ev = candidate.get("evidence_ref") or {}
        if not isinstance(ev, dict):
            ev = {}
        source = ev.get("source") or "document"
        source_id = ev.get("asset_id") or str(candidate.get("id") or uuid4())
        provenance = {**ev, "source": source}
        mission_id = candidate.get("mission_id") or ev.get("mission_id")
        job_id = candidate.get("job_id") or ev.get("job_id")
        if mission_id:
            provenance["mission_id"] = str(mission_id)
        if job_id:
            provenance["job_id"] = str(job_id)
        return {
            "statement": str(candidate.get("statement", "")),
            "claim_type": str(candidate.get("claim_type", "prose") or "prose"),
            "domain": str(candidate.get("domain", "external") or "external"),
            "status": "active",
            "confidence": candidate.get("confidence") or "UNVERIFIED",
            "confidence_score": float(candidate.get("confidence_score") or 0),
            "value": candidate.get("value"),
            "supporting_sources": [{
                "source_id": str(source_id),
                "evidence_level": 2,
                "snippet": str(candidate.get("statement", ""))[:200],
            }],
            "provenance": provenance,
            "evidence_ref": ev,
            "last_verified": ev.get("observed_at") or _utcnow_iso(),
        }


class InMemoryCandidateStore:
    """Hermetic candidate inbox for unit tests (mirrors CandidateRepository's surface)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def create(self, statement: str, **kw: Any) -> dict[str, Any]:
        self._seq += 1
        cid = f"cand-{self._seq:06d}"
        row = {
            "id": cid,
            "statement": statement,
            "status": "pending",
            "consumed_at": None,
            "consolidated_finding_id": None,
            "created_at": _utcnow_iso(),
            **kw,
        }
        self.rows[cid] = row
        return dict(row)

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        pending = [dict(r) for r in self.rows.values() if r["status"] == "pending"]
        return pending[:limit]

    def mark_consumed(self, candidate_id: str, *, finding_id: str | None = None) -> dict[str, Any] | None:
        row = self.rows.get(str(candidate_id))
        if not row:
            return None
        row["status"] = "consumed"
        row["consumed_at"] = _utcnow_iso()
        row["consolidated_finding_id"] = finding_id
        return dict(row)

    def mark_discarded(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.rows.get(str(candidate_id))
        if not row:
            return None
        row["status"] = "discarded"
        row["consumed_at"] = _utcnow_iso()
        return dict(row)
