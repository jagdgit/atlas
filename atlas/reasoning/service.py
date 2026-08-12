"""ReasoningService — mandatory cognitive façade for Belief Core (OI-SELF-REASON).

Domain workers must not call LLMService for semantic worldview ops.
Phase 1: consult / why / mind-change / revise / promote / seed / metrics.
Influence stays advice-only. LLM revise is optional (works without LLM).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from atlas.reasoning.aging import with_effective
from atlas.reasoning.seed import seed_worldview
from atlas.services.base import HealthStatus

VERSION = "self0.reasoning.v1"


class ReasoningService:
    """Sole cognitive choke point for belief worldview (Phase 1)."""

    name = "reasoning"

    def __init__(
        self,
        repo: Any,
        *,
        llm: Any | None = None,
        goals: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm
        self._goals = goals
        self._logger = logger or logging.getLogger("atlas.reasoning")
        self._seeded = False

    def health(self) -> HealthStatus:
        try:
            identity = self._repo.latest_identity()
            n = len(self._repo.list_beliefs(limit=1))
            detail = (
                f"identity_v{identity.get('version')}" if identity else "no_identity"
            )
            return HealthStatus(
                healthy=True,
                detail=f"{detail}; beliefs_reachable={n >= 0}; version={VERSION}",
            )
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, detail=f"beliefs unhealthy: {exc}")

    # --- identity / goals -----------------------------------------------
    def identity(self) -> dict[str, Any] | None:
        row = self._repo.latest_identity()
        return dict(row) if row else None

    def ensure_seeded(self) -> dict[str, Any]:
        """Idempotent identity + operator seed beliefs."""
        out = seed_worldview(self._repo)
        self._seeded = True
        return out

    def goals_snapshot(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self._goals is None:
            return []
        try:
            if hasattr(self._goals, "list"):
                return list(self._goals.list(status="active", limit=limit) or [])
            if hasattr(self._goals, "list_goals"):
                return list(self._goals.list_goals(status="active", limit=limit) or [])
        except Exception:  # noqa: BLE001
            self._logger.debug("goals snapshot failed", exc_info=True)
        return []

    # --- consult (instrumented) -----------------------------------------
    def _record_consult(
        self,
        belief: dict[str, Any] | None,
        *,
        domain: str | None = None,
        purpose: str = "consult",
    ) -> None:
        dom = domain or (str(belief.get("domain")) if belief else "cross")
        try:
            self._repo.record_consultation(
                domain=dom,
                purpose=purpose,
                belief_id=belief.get("id") if belief else None,
            )
            if belief and belief.get("id"):
                self._repo.touch_consulted(belief["id"])
        except Exception:  # noqa: BLE001
            self._logger.debug("consultation record failed", exc_info=True)

    def consult(
        self,
        *,
        domain: str | None = None,
        theme: str | None = None,
        query: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
        purpose: str = "consult",
    ) -> dict[str, Any]:
        """Retrieve beliefs for inheritance. Always increments consultation metrics."""
        statuses = statuses or ["active", "weakened"]
        rows: list[dict[str, Any]]
        if query:
            rows = self._repo.search_beliefs(query, limit=limit)
            if domain:
                rows = [r for r in rows if r.get("domain") == domain]
            # Broad query with no token hits → still surface active worldview
            if not rows:
                rows = self._repo.list_beliefs(
                    domain=domain,
                    statuses=statuses,
                    theme=theme,
                    limit=limit,
                )
        else:
            rows = self._repo.list_beliefs(
                domain=domain,
                statuses=statuses,
                theme=theme,
                limit=limit,
            )
        enriched = [with_effective(r) for r in rows]
        # One consultation per returned belief (plus a domain rollup if empty)
        if enriched:
            for b in enriched:
                self._record_consult(b, domain=b.get("domain"), purpose=purpose)
        else:
            self._record_consult(None, domain=domain or "cross", purpose=purpose)
        return {
            "version": VERSION,
            "count": len(enriched),
            "beliefs": enriched,
            "identity": self.identity(),
            "goals": self.goals_snapshot(limit=10),
            "consultations_today": self.consultation_metrics(),
        }

    def get_belief(self, belief_id: str, *, purpose: str = "consult") -> dict[str, Any] | None:
        row = self._repo.get_belief(belief_id)
        if not row:
            return None
        self._record_consult(row, purpose=purpose)
        return with_effective(row)

    # --- explain benchmarks ---------------------------------------------
    def why(self, query_or_id: str) -> dict[str, Any]:
        """Benchmark: Why do you believe X?"""
        q = (query_or_id or "").strip()
        belief = None
        if q:
            # UUID lookup only when it looks like one (avoid PG uuid cast errors).
            if len(q) >= 32 and all(c in "0123456789abcdef-ABCDEF" for c in q):
                try:
                    belief = self._repo.get_belief(q)
                except Exception:  # noqa: BLE001
                    belief = None
            if belief is None:
                belief = self._repo.get_by_key(q)
            if belief is None:
                hits = self._repo.search_beliefs(q, limit=1)
                belief = hits[0] if hits else None
        if belief is None:
            self._record_consult(None, domain="cross", purpose="why")
            return {
                "ok": False,
                "version": VERSION,
                "error": "belief_not_found",
                "query": q,
            }
        self._record_consult(belief, purpose="why")
        evidence = self._repo.list_evidence(belief["id"])
        contradictions = self._repo.list_contradictions(belief["id"])
        revisions = self._repo.list_revisions(belief["id"], limit=5)
        influence = self._repo.list_influence(belief["id"])
        enriched = with_effective(belief)
        last_rev = revisions[0] if revisions else None
        return {
            "ok": True,
            "version": VERSION,
            "belief": enriched,
            "confidence": {
                "stored": float(belief.get("confidence") or 0),
                "effective": enriched.get("effective_confidence"),
                "evidence_age_days": enriched.get("evidence_age_days"),
            },
            "evidence": evidence,
            "contradictions": contradictions,
            "last_revision": last_rev,
            "falsifiers": list(belief.get("open_questions") or []),
            "influence": influence,
            "status": belief.get("status"),
            "answer": self._format_why(enriched, evidence, contradictions, last_rev),
        }

    def what_changed_your_mind(self, query_or_id: str) -> dict[str, Any]:
        """Benchmark: What changed your mind?"""
        base = self.why(query_or_id)
        if not base.get("ok"):
            return base
        belief = base["belief"]
        revisions = self._repo.list_revisions(belief["id"], limit=20)
        material = [
            r
            for r in revisions
            if r.get("action")
            in {"revise", "promote", "weaken", "falsify", "supersede"}
        ]
        self._record_consult(belief, purpose="mind_change")
        if not material:
            return {
                **base,
                "ok": True,
                "mind_changes": [],
                "answer": (
                    f"No material mind-change yet for belief {belief.get('id')}. "
                    f"Current status={belief.get('status')}; "
                    f"confidence={base['confidence']['stored']}→"
                    f"{base['confidence']['effective']} effective."
                ),
            }
        latest = material[0]
        answer = (
            f"I believed: {latest.get('before_snapshot', {}).get('statement') if isinstance(latest.get('before_snapshot'), dict) else '(prior)'} "
            f"\nThat belief was {latest.get('action')}d"
            f" (revision r{latest.get('revision_no')})."
            f"\nReason: {latest.get('reason') or '(none)'}"
            f"\nEvidence: {latest.get('evidence_summary') or '(none)'}"
            f"\nConfidence: {latest.get('confidence_before')} → {latest.get('confidence_after')}"
            f"\nNow: {belief.get('statement')} "
            f"(status={belief.get('status')}, "
            f"confidence={base['confidence']['stored']} stored / "
            f"{base['confidence']['effective']} effective)."
        )
        return {
            **base,
            "mind_changes": material,
            "latest_change": latest,
            "answer": answer,
        }

    @staticmethod
    def _format_why(
        belief: dict[str, Any],
        evidence: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
        last_rev: dict[str, Any] | None,
    ) -> str:
        lines = [
            f"Belief ({belief.get('id')}): {belief.get('statement')}",
            f"Status: {belief.get('status')} · domain={belief.get('domain')} · "
            f"level={belief.get('level')}",
            f"Confidence: stored={belief.get('confidence')} · "
            f"effective={belief.get('effective_confidence')} "
            f"(age_days={belief.get('evidence_age_days')})",
        ]
        if evidence:
            lines.append("Evidence:")
            for e in evidence[:5]:
                lines.append(f"  - [{e.get('kind')}] {e.get('summary')}")
        else:
            lines.append("Evidence: (none linked)")
        if contradictions:
            lines.append("Contradictions:")
            for c in contradictions[:3]:
                lines.append(f"  - {c.get('summary')} ({c.get('status')})")
        else:
            lines.append("Contradictions: (none)")
        falsifiers = list(belief.get("open_questions") or [])
        if falsifiers:
            lines.append("What would change this:")
            for f in falsifiers[:5]:
                lines.append(f"  - {f}")
        if last_rev:
            lines.append(
                f"Last revision: r{last_rev.get('revision_no')} "
                f"{last_rev.get('action')} — {last_rev.get('reason')}"
            )
        return "\n".join(lines)

    # --- mutations ------------------------------------------------------
    def propose_candidate(
        self,
        *,
        statement: str,
        domain: str,
        confidence: float = 0.35,
        themes: list[str] | None = None,
        open_questions: list[str] | None = None,
        evidence_summary: str = "",
        origin: str = "llm",
        actor: str = "reasoning",
    ) -> dict[str, Any]:
        row = self._repo.create_belief(
            statement=statement,
            domain=domain,
            status="candidate",
            origin=origin,
            confidence=confidence,
            themes=themes or [],
            open_questions=open_questions or [],
            actor=actor,
        )
        if evidence_summary:
            self._repo.add_evidence(
                row["id"], kind="note", summary=evidence_summary
            )
        self._repo.add_influence(
            row["id"], target="general", strength="advice", note="candidate"
        )
        return with_effective(row)

    def promote(
        self,
        belief_id: str,
        *,
        reason: str,
        actor: str = "operator",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        before = self._repo.get_belief(belief_id)
        if before is None:
            raise KeyError(f"belief not found: {belief_id}")
        if before.get("status") not in {"candidate", "dormant", "weakened"}:
            raise ValueError(
                f"cannot promote from status={before.get('status')}; "
                "expected candidate/dormant/weakened"
            )
        after = self._repo.update_belief(
            belief_id,
            status="active",
            confidence=confidence,
        )
        rev = self._repo.add_revision(
            belief_id,
            action="promote",
            before=before,
            after=after,
            reason=reason,
            confidence_before=float(before.get("confidence") or 0),
            confidence_after=float((after or {}).get("confidence") or 0),
            actor=actor,
        )
        return {"belief": with_effective(after or before), "revision": rev}

    def revise(
        self,
        belief_id: str,
        *,
        reason: str,
        evidence_summary: str = "",
        new_statement: str | None = None,
        new_confidence: float | None = None,
        new_status: str | None = None,
        open_questions: list[str] | None = None,
        actor: str = "reasoning",
        use_llm: bool = False,
    ) -> dict[str, Any]:
        """Revise a belief with explainable reason. LLM optional (Phase 1)."""
        before = self._repo.get_belief(belief_id)
        if before is None:
            raise KeyError(f"belief not found: {belief_id}")
        statement = new_statement
        confidence = new_confidence
        status = new_status
        if use_llm and self._llm is not None and statement is None:
            statement = self._llm_suggest_revision(before, reason=reason)
        if (
            statement is None
            and confidence is None
            and status is None
            and open_questions is None
        ):
            raise ValueError(
                "revise requires statement, confidence, status, or open_questions change"
            )
        # Normalize weaken alias
        action = "revise"
        if status in {"weaken", "weakened"}:
            status = "weakened"
            action = "weaken"
        elif status == "falsified":
            action = "falsify"
        elif status == "superseded":
            action = "supersede"
        after = self._repo.update_belief(
            belief_id,
            statement=statement,
            confidence=confidence,
            status=status,
            open_questions=open_questions,
        )
        if evidence_summary:
            self._repo.add_evidence(
                belief_id, kind="note", summary=evidence_summary
            )
        rev = self._repo.add_revision(
            belief_id,
            action=action,
            before=before,
            after=after,
            reason=reason,
            evidence_summary=evidence_summary,
            confidence_before=float(before.get("confidence") or 0),
            confidence_after=float((after or {}).get("confidence") or 0),
            actor=actor,
        )
        return {"belief": with_effective(after or before), "revision": rev}

    def _llm_suggest_revision(
        self, before: dict[str, Any], *, reason: str
    ) -> str | None:
        """Optional researcher-role suggestion; never invents if LLM absent/fails."""
        try:
            client = (
                self._llm.for_role("researcher")
                if hasattr(self._llm, "for_role")
                else self._llm
            )
            from atlas.llm.provider import ChatMessage

            resp = client.chat(
                [
                    ChatMessage(
                        role="system",
                        content=(
                            "You revise Atlas beliefs. Return ONLY the new belief "
                            "statement as one sentence. Do not invent evidence."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            f"Current belief: {before.get('statement')}\n"
                            f"Reason for revision: {reason}\n"
                            "New statement:"
                        ),
                    ),
                ]
            )
            text = (getattr(resp, "text", None) or str(resp) or "").strip()
            return text or None
        except Exception:  # noqa: BLE001
            self._logger.debug("LLM revise suggestion failed", exc_info=True)
            return None

    # --- WSO projection (read-path) -------------------------------------
    def project_for_symbol(
        self,
        symbol: str,
        *,
        laboratory_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Market working-memory projection: Belief Core slice for a symbol.

        Does not mutate WSO files. Callers may merge into WSO read models.
        """
        sym = (symbol or "").strip().upper()
        hits = self.consult(
            domain="market",
            query=sym,
            limit=limit,
            purpose="wso_projection",
        )
        # Also pull general market active beliefs
        general = self._repo.list_beliefs(
            domain="market", statuses=["active", "weakened"], limit=limit
        )
        general_e = [with_effective(g) for g in general]
        for g in general_e:
            self._record_consult(g, purpose="wso_projection")
        return {
            "version": VERSION,
            "symbol": sym,
            "laboratory_id": laboratory_id,
            "matched": hits.get("beliefs") or [],
            "market_active": general_e,
            "note": "WSO remains entity working memory; this is Belief Core projection.",
            "influence_strength": "advice",
        }

    # --- metrics --------------------------------------------------------
    def consultation_metrics(self, *, day_ist: date | None = None) -> dict[str, Any]:
        return self._repo.consultation_counts(day_ist=day_ist)

    def revision_metrics(self, *, days: int = 7) -> dict[str, Any]:
        return self._repo.revision_counts(days=days)

    def metrics(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "consultations_today": self.consultation_metrics(),
            "revisions": self.revision_metrics(days=7),
            "identity": self.identity(),
            "belief_counts": {
                "active": len(
                    self._repo.list_beliefs(status="active", limit=200)
                ),
                "candidate": len(
                    self._repo.list_beliefs(status="candidate", limit=200)
                ),
                "weakened": len(
                    self._repo.list_beliefs(status="weakened", limit=200)
                ),
            },
        }

    def list_beliefs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [with_effective(r) for r in self._repo.list_beliefs(**kwargs)]

    # --- OI-SELF-EXP closed loop ----------------------------------------
    def close_experience_loop(
        self,
        experience_os: Any,
        journal_kwargs: dict[str, Any],
        *,
        ingest_beliefs: bool = True,
        actor: str = "reasoning",
    ) -> dict[str, Any]:
        from atlas.reasoning.experience_loop import close_loop

        return close_loop(
            experience_os=experience_os,
            reasoning=self,
            journal_kwargs=journal_kwargs,
            ingest_beliefs=ingest_beliefs,
            actor=actor,
        )

    def ingest_experience_lesson(
        self,
        *,
        lesson: str,
        domain: str,
        experience_id: str | None = None,
        affected_beliefs: list[str] | None = None,
        delta_label: str | None = None,
        evidence_summary: str = "",
    ) -> dict[str, Any]:
        from atlas.reasoning.experience_loop import ingest_experience_to_beliefs

        return ingest_experience_to_beliefs(
            self,
            lesson=lesson,
            domain=domain,
            experience_id=experience_id,
            affected_beliefs=affected_beliefs,
            delta_label=delta_label,
            evidence_summary=evidence_summary,
        )

    def close_packet_outcome(
        self,
        experience_os: Any,
        packet: dict[str, Any],
        outcome_structured: dict[str, Any],
        *,
        affected_beliefs: list[str] | None = None,
        no_belief_link_reason: str | None = None,
        lesson: str = "",
    ) -> dict[str, Any]:
        from atlas.reasoning.experience_loop import (
            journal_kwargs_from_packet_outcome,
            close_loop,
        )

        kwargs = journal_kwargs_from_packet_outcome(
            packet,
            outcome_structured=outcome_structured,
            affected_beliefs=affected_beliefs,
            no_belief_link_reason=no_belief_link_reason
            or (
                None
                if affected_beliefs
                else "packet outcome logged; no belief yet mapped"
            ),
            lesson=lesson,
        )
        return close_loop(
            experience_os=experience_os,
            reasoning=self,
            journal_kwargs=kwargs,
            ingest_beliefs=bool(affected_beliefs),
            actor="packet_loop",
        )
    def reflect(
        self,
        *,
        laboratory_id: str | None = None,
        allow_llm_narrative: bool = True,
    ) -> dict[str, Any]:
        """OI-SELF-REFLECT — nightly Belief Core reflection."""
        from atlas.reasoning.reflection import run_nightly_reflection

        return run_nightly_reflection(
            self,
            laboratory_id=laboratory_id,
            allow_llm_narrative=allow_llm_narrative,
        )
