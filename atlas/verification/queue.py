"""Knowledge verification queue (KV.2–KV.5 / KV.6).

Select UNVERIFIED findings → adapt to Claim → optional Research gather (KV.4) →
VerificationEngine.verify_claim → write back confidence. Reuses finding_reviews +
the existing engine — no second verifier.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from atlas.evidence.models import EvidenceItem, LEVEL_TECHNICAL, STANCE_SUPPORT
from atlas.knowledge.lifecycle import normalize_statement
from atlas.knowledge.normalize import normalize_claim_statement
from atlas.verification.adapt import claim_verification_writeback, finding_row_to_claim
from atlas.verification.contradiction import attach_contradictions, find_contradictions

REASON_VERIFY_CLAIM = "verify_claim"
_DEFAULT_CLAIM_TYPES = frozenset({"claim", "prose", "hypothesis", "observation", "conclusion"})
# Default gather budget for verify path (looser than a full research job).
_DEFAULT_GATHER_ITERATIONS = 3


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class KnowledgeVerificationService:
    """Operator / scheduler entry points for single-claim knowledge verification."""

    name = "knowledge_verification"
    VERSION = "kv.10"

    def __init__(
        self,
        store: Any,
        verification: Any,
        *,
        research: Any | None = None,
        gather: Callable[..., dict[str, Any]] | None = None,
        enqueue: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._verification = verification
        self._research = research
        # Optional injectable gather(claim, **kwargs) → dict — for hermetic tests
        # or a custom gatherer. Prefer ResearchService.gather_evidence when set.
        self._gather = gather
        self._enqueue = enqueue
        self._logger = logger or logging.getLogger("atlas.verification.queue")

    # --- selection ---------------------------------------------------------
    def list_pending(
        self,
        *,
        asset_id: str | None = None,
        job_id: str | None = None,
        source_url: str | None = None,
        claim_types: Sequence[str] | None = None,
        confidence: str = "UNVERIFIED",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """UNVERIFIED findings matching optional provenance filters."""
        types = (
            frozenset(str(t).lower() for t in claim_types)
            if claim_types is not None
            else _DEFAULT_CLAIM_TYPES
        )
        if hasattr(self._store, "list_unverified"):
            rows = self._store.list_unverified(
                asset_id=asset_id,
                job_id=job_id,
                source_url=source_url,
                claim_types=sorted(types) if types else None,
                confidence=confidence,
                limit=limit,
            )
            return list(rows or [])

        # In-memory / minimal stores: scan active heads.
        heads: list[dict[str, Any]] = []
        if hasattr(self._store, "list_active_heads"):
            heads = list(self._store.list_active_heads(include_archive=False) or [])
        elif hasattr(self._store, "list_active"):
            heads = list(self._store.list_active(limit=max(limit * 4, 100)) or [])
        else:
            rows_map = getattr(self._store, "rows", None)
            if isinstance(rows_map, dict):
                heads = [dict(r) for r in rows_map.values()]

        out: list[dict[str, Any]] = []
        for row in heads:
            if str(row.get("confidence") or "") != confidence:
                continue
            ctype = str(row.get("claim_type") or "").lower()
            if types and ctype and ctype not in types:
                continue
            prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            if asset_id and str(prov.get("asset_id") or "") != str(asset_id):
                continue
            if job_id:
                row_job = str(row.get("job_id") or prov.get("job_id") or "")
                if row_job != str(job_id):
                    continue
            if source_url:
                url = str(prov.get("source_url") or prov.get("url") or "")
                if source_url.rstrip("/") not in url:
                    continue
            out.append(dict(row))
            if len(out) >= limit:
                break
        return out

    def enqueue(
        self,
        finding_ids: Sequence[str],
        *,
        reason: str = REASON_VERIFY_CLAIM,
    ) -> dict[str, Any]:
        """Queue findings onto knowledge.finding_reviews (+ optional scheduler)."""
        queued: list[str] = []
        for fid in finding_ids:
            fid_s = str(fid or "").strip()
            if not fid_s:
                continue
            if hasattr(self._store, "enqueue_review"):
                self._store.enqueue_review(fid_s, reason=reason, component_id="verification")
            if self._enqueue is not None:
                try:
                    self._enqueue(
                        "verify_finding",
                        {"finding_id": fid_s, "reason": reason},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("enqueue verify_finding failed: %s", exc)
            queued.append(fid_s)
        return {"queued": queued, "count": len(queued), "reason": reason}

    # --- verify ------------------------------------------------------------
    def verify_finding(
        self, payload: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Scheduler handler: normalize → Claim → optional gather → verify → write-back."""
        data = dict(payload or {})
        data.update(kwargs)
        finding_id = str(data.get("finding_id") or "")
        if not finding_id:
            return {"status": "error", "reason": "missing finding_id"}
        row = self._store.get(finding_id)
        if row is None:
            return {"status": "missing", "finding_id": finding_id}

        do_gather = _truthy(data.get("gather"))
        # KV.8 / KV9: on by default now that single-claim verify is stable.
        do_contra = True if data.get("detect_contradictions") is None else _truthy(
            data.get("detect_contradictions")
        )
        max_gather = data.get("max_gather_iterations")
        try:
            max_gather_i = (
                int(max_gather) if max_gather is not None else _DEFAULT_GATHER_ITERATIONS
            )
        except (TypeError, ValueError):
            max_gather_i = _DEFAULT_GATHER_ITERATIONS

        claim = finding_row_to_claim(row)
        before_sources = len(claim.evidence)
        claim = self._attach_kb_corroboration(row, claim)
        gather_meta: dict[str, Any] | None = None
        if do_gather:
            gather_meta = self._run_gather(claim, max_iterations=max_gather_i)

        contra_hits: list[Any] = []
        if do_contra:
            peers = self._peer_findings()
            contra_hits = find_contradictions(row, peers)
            claim = attach_contradictions(claim, contra_hits)

        claim = self._verification.verify_claim(claim)
        writeback = claim_verification_writeback(
            claim, row=row, contradictions=contra_hits or None
        )
        # Contested when cross-source contradictions were attached (KV.8).
        contested = bool(contra_hits) or bool(claim.contradicting)
        if contested:
            from atlas.knowledge.conflict import conflict_record, merge_conflict_quality

            conflict = conflict_record(
                kind="verification",
                signal="cross_source_contradiction",
                peer_ids=[str(getattr(h, "peer_id", "") or "") for h in (contra_hits or [])],
                detail={"hits": len(contra_hits or [])},
            )
            merge_conflict_quality(self._store, finding_id, conflict)
            writeback["freshness"] = "stale"

        updated = None
        if hasattr(self._store, "update_verification"):
            updated = self._store.update_verification(
                finding_id,
                confidence=writeback["confidence"],
                confidence_score=writeback["confidence_score"],
                last_verified=writeback["last_verified"] or _utcnow_iso(),
                freshness=writeback["freshness"],
            )
        # Persist newly gathered / KB-corroborated / contradicting evidence in place.
        if (
            len(claim.evidence) > before_sources or contested
        ) and hasattr(self._store, "update_evidence"):
            try:
                updated = self._store.update_evidence(
                    finding_id,
                    supporting=[e.as_dict() for e in claim.supporting],
                    contradicting=[e.as_dict() for e in claim.contradicting],
                    confidence=writeback["confidence"],
                    confidence_score=writeback["confidence_score"],
                    last_verified=writeback["last_verified"] or _utcnow_iso(),
                    status="contested" if contested else None,
                ) or updated
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("update_evidence after verify failed: %s", exc)
        elif contested and hasattr(self._store, "set_status"):
            try:
                self._store.set_status(finding_id, "contested")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("set_status contested failed: %s", exc)

        trust = dict(writeback.get("trust") or {})
        self._merge_trust_slots(finding_id, trust)

        # Best-effort: mark peer findings contested too (cross-source).
        if contested and contra_hits:
            self._mark_peers_contested(contra_hits)

        review_row = None
        if hasattr(self._store, "complete_review"):
            review_row = self._store.complete_review(
                finding_id, status="done", note=data.get("reason") or REASON_VERIFY_CLAIM
            )

        self._logger.info(
            "verified finding %s → %s (%.3f) gather=%s contra=%d",
            finding_id,
            writeback["confidence"],
            writeback["confidence_score"],
            bool(gather_meta),
            len(contra_hits),
        )
        return {
            "status": "done",
            "finding_id": finding_id,
            "statement": claim.statement,
            "confidence": writeback["confidence"],
            "confidence_score": writeback["confidence_score"],
            "freshness": writeback["freshness"],
            "trust": trust,
            "contested": contested,
            "contradictions": [h.as_dict() for h in contra_hits],
            "finding": updated,
            "review": review_row,
            "reasoning_trace": writeback.get("reasoning_trace") or [],
            "supporting_count": len(claim.supporting),
            "contradicting_count": len(claim.contradicting),
            "gather": gather_meta,
            "verification_version": self.VERSION,
        }

    def verify_batch(
        self,
        *,
        asset_id: str | None = None,
        job_id: str | None = None,
        source_url: str | None = None,
        finding_ids: Sequence[str] | None = None,
        claim_types: Sequence[str] | None = None,
        limit: int = 25,
        enqueue_only: bool = False,
        gather: bool = False,
        max_gather_iterations: int | None = None,
        detect_contradictions: bool = True,
    ) -> dict[str, Any]:
        """Operator entry: select pending findings and verify (or enqueue)."""
        if finding_ids:
            rows = []
            for fid in finding_ids:
                row = self._store.get(str(fid))
                if row is not None:
                    rows.append(row)
        else:
            rows = self.list_pending(
                asset_id=asset_id,
                job_id=job_id,
                source_url=source_url,
                claim_types=claim_types,
                limit=limit,
            )

        ids = [str(r["id"]) for r in rows if r.get("id")]
        if enqueue_only:
            queued = self.enqueue(ids)
            return {
                "status": "queued",
                "selected": len(ids),
                "results": [],
                **queued,
                "before_after": [],
                "gather_requested": bool(gather),
            }

        results: list[dict[str, Any]] = []
        before_after: list[dict[str, Any]] = []
        contested_n = 0
        for row in rows:
            before = {
                "finding_id": row.get("id"),
                "statement": row.get("statement"),
                "confidence": row.get("confidence"),
                "confidence_score": row.get("confidence_score"),
            }
            if hasattr(self._store, "enqueue_review"):
                self._store.enqueue_review(
                    str(row["id"]), reason=REASON_VERIFY_CLAIM, component_id="verification"
                )
            payload: dict[str, Any] = {
                "finding_id": row["id"],
                "reason": REASON_VERIFY_CLAIM,
                "gather": gather,
                "detect_contradictions": detect_contradictions,
            }
            if max_gather_iterations is not None:
                payload["max_gather_iterations"] = max_gather_iterations
            result = self.verify_finding(payload)
            results.append(result)
            if result.get("contested"):
                contested_n += 1
            before_after.append(
                {
                    **before,
                    "after_confidence": result.get("confidence"),
                    "after_confidence_score": result.get("confidence_score"),
                    "overall_trust": (result.get("trust") or {}).get("overall_trust"),
                    "extraction_confidence": (result.get("trust") or {}).get(
                        "extraction_confidence"
                    ),
                    "source_reliability": (result.get("trust") or {}).get(
                        "source_reliability"
                    ),
                    "status": result.get("status"),
                    "gather_added": (result.get("gather") or {}).get("added"),
                    "contested": result.get("contested"),
                    "contradictions": len(result.get("contradictions") or []),
                }
            )

        promoted = sum(
            1 for r in results if r.get("confidence") in {"HIGH", "MEDIUM", "LOW"}
        )
        still = sum(
            1 for r in results if r.get("confidence") in {"UNVERIFIED", "INSUFFICIENT"}
        )
        return {
            "status": "done",
            "selected": len(rows),
            "verified": len(results),
            "promoted_or_scored": promoted,
            "still_unverified": still,
            "contested": contested_n,
            "results": results,
            "before_after": before_after,
            "verification": "executed",
            "gather_requested": bool(gather),
            "orchestrator": "knowledge.verify",
            "version": self.VERSION,
        }

    # tool / assistant surface ---------------------------------------------
    def knowledge_verify(
        self,
        *,
        source_url: str | None = None,
        asset_id: str | None = None,
        job_id: str | None = None,
        finding_id: str | None = None,
        limit: int = 25,
        enqueue_only: bool = False,
        gather: bool | str = False,
        max_gather_iterations: int | None = None,
        detect_contradictions: bool | str = True,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Tool entry: verify claims learned from a media source / asset / finding."""
        ids = [finding_id] if finding_id else None
        return self.verify_batch(
            asset_id=asset_id,
            job_id=job_id,
            source_url=source_url,
            finding_ids=ids,
            limit=limit,
            enqueue_only=_truthy(enqueue_only),
            gather=_truthy(gather),
            max_gather_iterations=max_gather_iterations,
            detect_contradictions=(
                True
                if detect_contradictions is None
                else _truthy(detect_contradictions)
            ),
        )

    # --- internals ---------------------------------------------------------
    def _peer_findings(self) -> list[dict[str, Any]]:
        if hasattr(self._store, "list_active_heads"):
            return list(self._store.list_active_heads(include_archive=False) or [])
        if hasattr(self._store, "rows") and isinstance(self._store.rows, dict):
            return [dict(r) for r in self._store.rows.values()]
        if hasattr(self._store, "list_active"):
            return list(self._store.list_active(limit=200) or [])
        return []

    def _mark_peers_contested(self, hits: Sequence[Any]) -> None:
        for hit in hits:
            pid = str(getattr(hit, "peer_id", "") or "")
            if not pid:
                continue
            peer = self._store.get(pid) if hasattr(self._store, "get") else None
            if not peer:
                continue
            if str(peer.get("status") or "") == "contested":
                continue
            if hasattr(self._store, "set_status"):
                try:
                    self._store.set_status(pid, "contested")
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("peer contested mark failed: %s", exc)
    def _run_gather(self, claim: Any, *, max_iterations: int) -> dict[str, Any]:
        """KV.4 — optional Research gather onto the claim (budget-capped)."""
        try:
            if self._gather is not None:
                return dict(
                    self._gather(claim, max_iterations=max_iterations) or {}
                )
            if self._research is not None and hasattr(self._research, "gather_evidence"):
                return dict(
                    self._research.gather_evidence(
                        claim, max_iterations=max_iterations
                    )
                    or {}
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("gather_evidence failed: %s", exc)
            return {"outcome": "error", "reason": str(exc), "added": 0}
        return {
            "outcome": "skipped",
            "reason": "no research gather provider wired",
            "added": 0,
        }

    def _attach_kb_corroboration(self, row: dict[str, Any], claim: Any) -> Any:
        """KV.3: attach evidence from other KB findings that overlap concepts/entities."""
        value = row.get("value") if isinstance(row.get("value"), dict) else {}
        concepts = {
            normalize_statement(str(c))
            for c in (value.get("related_concepts") or [])
            if c
        }
        entities = {
            normalize_statement(str(e))
            for e in (value.get("related_entities") or [])
            if e
        }
        if not concepts and not entities:
            return claim

        peers: list[dict[str, Any]] = []
        if hasattr(self._store, "list_active_heads"):
            peers = list(self._store.list_active_heads(include_archive=False) or [])
        elif hasattr(self._store, "rows") and isinstance(self._store.rows, dict):
            peers = list(self._store.rows.values())

        existing_ids = {e.source_id for e in claim.evidence}
        added = 0
        for peer in peers:
            if str(peer.get("id")) == str(row.get("id")):
                continue
            if str(peer.get("confidence") or "") in {"UNVERIFIED", "INSUFFICIENT", ""}:
                continue
            pval = peer.get("value") if isinstance(peer.get("value"), dict) else {}
            p_concepts = {
                normalize_statement(str(c))
                for c in (pval.get("related_concepts") or [])
                if c
            }
            p_entities = {
                normalize_statement(str(e))
                for e in (pval.get("related_entities") or [])
                if e
            }
            # Also match concept/entity *names* in peer statement.
            stmt_n = normalize_statement(str(peer.get("statement") or ""))
            overlap = (concepts & p_concepts) or (entities & p_entities)
            if not overlap:
                if concepts and any(c and c in stmt_n for c in concepts):
                    overlap = True
                elif entities and any(e and e in stmt_n for e in entities):
                    overlap = True
            if not overlap:
                continue
            source_id = f"kb:{peer.get('id')}"
            if source_id in existing_ids:
                continue
            claim.evidence.append(
                EvidenceItem(
                    source_id=source_id,
                    evidence_level=LEVEL_TECHNICAL,
                    snippet=normalize_claim_statement(str(peer.get("statement") or ""))[:200],
                    stance=STANCE_SUPPORT,
                )
            )
            existing_ids.add(source_id)
            added += 1
            if added >= 5:
                break
        return claim

    def _merge_trust_slots(self, finding_id: str, trust: dict[str, Any]) -> None:
        if not trust or not hasattr(self._store, "get"):
            return
        row = self._store.get(finding_id)
        if not row:
            return
        quality = dict(row.get("quality") or {}) if isinstance(row.get("quality"), dict) else {}
        quality["trust"] = dict(trust)
        # Best-effort: in-memory stores mutate row; Postgres needs an update helper.
        if finding_id in getattr(self._store, "rows", {}):
            self._store.rows[finding_id]["quality"] = quality
            return
        if hasattr(self._store, "merge_quality"):
            try:
                self._store.merge_quality(finding_id, quality)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("merge_quality skipped: %s", exc)
