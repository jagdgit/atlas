"""DecisionEngine — the shared "what should I do next?" Kernel Service (Phase D · §D.1, roadmap §5.5).

The consumer of everything Atlas knows. Given a :class:`~atlas.decision.contracts.DecisionRequest` it:

1. resolves the mission-type :class:`~atlas.decision.rules.DecisionRule` (DD2);
2. lets the rule **deterministically** score candidate options (Q7 — no LLM in the choice);
3. folds in **Policy** as signed, bounded influence (DD5 — arbitration, not filtering);
4. picks the top option, derives a deterministic **confidence** from the score margin, and assembles
   the full **P9 record** (action, why, evidence/knowledge/experience refs, config + model versions,
   alternatives rejected);
5. marks it ``requires_approval`` when the action is **side-effecting** (P14 — the gate consumes this
   in D.3), then **persists** it to ``decision.decisions`` and emits an event.

Honest about limits (P15): if no rule is registered for the mission type, or a rule raises
:class:`~atlas.decision.rules.CapabilityGap`, the engine records a ``capability_gap`` decision naming
what is missing — never a fabricated action. The LLM is confined to an optional ``narrator`` seam that
only rewrites the human ``why`` prose and always falls back to the deterministic text (CC-D1).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import (
    ACTION_CAPABILITY_GAP,
    ACTION_HOLD,
    ACTION_RECOMMEND,
    CONFIDENCE_LOW,
    Decision,
    DecisionRequest,
    ScoredOption,
    derive_confidence,
)
from atlas.decision.rules import (
    CapabilityGap,
    DecisionRule,
    DecisionRuleRegistry,
    apply_policy_influence,
)


class DecisionEngine:
    name = "decision"
    VERSION = "1.0.0"

    def __init__(
        self,
        repo: Any,
        *,
        rules: DecisionRuleRegistry | None = None,
        policy: Any = None,
        engineering: Any = None,
        research: Any = None,
        personal: Any = None,
        knowledge: Any = None,
        versions_provider: Callable[[], dict[str, Any]] | None = None,
        narrator: Any = None,
        approvals: Any = None,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._rules = rules or DecisionRuleRegistry()
        # Duck-typed PolicyService (``retrieval_influence``/``advice_influence``); None → no arbitration.
        self._policy = policy
        # The three intelligences the engine composes (DD2/§D.2); any may be None → a rule that needs
        # it gets an honest capability_gap (P15). Resolved via capabilities at wiring time (CC-D2, D.5).
        self._engineering = engineering
        self._research = research
        self._personal = personal
        self._knowledge = knowledge
        # Supplies real component versions from the Capability Registry (P2/CC-D3); None → {}.
        self._versions_provider = versions_provider
        # Optional LLM seam that only rewrites the ``why`` prose (CC-D1); never picks the action.
        self._narrator = narrator
        # Optional ApprovalService (§D.3, P14). When present, a side-effecting decision automatically
        # opens the human gate (proposes an approval); non-side-effecting decisions never enter it.
        self._approvals = approvals
        self._events = events
        self._logger = logger or logging.getLogger("atlas.decision")

    # --- registry passthrough ------------------------------------------
    def register_rule(self, rule: DecisionRule) -> None:
        self._rules.register(rule)

    def known_types(self) -> list[str]:
        return self._rules.known_types()

    # --- journal reads (the P9 "explain this" surface, D.5) -------------
    def list_decisions(
        self,
        *,
        mission_id: Any = None,
        mission_type: str | None = None,
        action_kind: str | None = None,
        requires_approval: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._repo.list(
            mission_id=mission_id, mission_type=mission_type, action_kind=action_kind,
            requires_approval=requires_approval, limit=limit,
        )

    def get_decision(self, decision_id: Any) -> dict[str, Any] | None:
        """The full P9 record for one decision — the 'Explain this' payload."""
        return self._repo.get(decision_id)

    def list_gaps(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """The capability-gap backlog (P15): what Atlas honestly couldn't do."""
        return self._repo.list_gaps(limit=limit)

    # --- the one public API --------------------------------------------
    def decide(self, request: DecisionRequest) -> Decision:
        """Deterministically choose the next action for a mission and journal the P9 record."""
        rule = self._rules.get(request.mission_type)
        if rule is None:
            return self._capability_gap(
                request,
                capability=f"decision_rule:{request.mission_type}",
                detail=f"no decision rule registered for mission type '{request.mission_type}'",
            )

        context = self._intelligence_context()
        try:
            options = list(rule.score(request, context) or [])
        except CapabilityGap as gap:
            return self._capability_gap(request, capability=gap.capability, detail=gap.detail,
                                        rule=rule)

        influences = self._influences(request)
        apply_policy_influence(options, influences)

        if not options:
            # The rule ran but found nothing worth doing this tick — an explicit, honest hold.
            return self._hold(request, rule)

        options.sort(key=lambda o: o.final_score, reverse=True)
        chosen = options[0]
        rejected = options[1:]
        label, score = derive_confidence([o.final_score for o in options])

        decision = Decision(
            mission_id=request.mission_id,
            mission_type=request.mission_type,
            action_kind=ACTION_RECOMMEND,
            action={"kind": ACTION_RECOMMEND, "key": chosen.key, "payload": chosen.payload},
            decision_rule=getattr(rule, "mission_type", request.mission_type),
            rule_version=str(getattr(rule, "VERSION", "")),
            config_id=request.config_id,
            config_version=request.config_version,
            evidence_refs=list(chosen.evidence_refs),
            knowledge_refs=list(chosen.knowledge_refs),
            experience_refs=list(chosen.experience_refs),
            model_versions=self._model_versions(),
            policy_ids=list(chosen.policy_ids),
            confidence=label,
            confidence_score=score,
            alternatives_rejected=[o.to_summary() for o in rejected],
            requires_approval=bool(chosen.side_effecting),
        )
        decision.why = self._why(decision, chosen, rejected)
        return self._persist(decision, event="DecisionMade")

    # --- outcomes -------------------------------------------------------
    def _hold(self, request: DecisionRequest, rule: DecisionRule) -> Decision:
        decision = Decision(
            mission_id=request.mission_id,
            mission_type=request.mission_type,
            action_kind=ACTION_HOLD,
            action={"kind": ACTION_HOLD},
            decision_rule=getattr(rule, "mission_type", request.mission_type),
            rule_version=str(getattr(rule, "VERSION", "")),
            config_id=request.config_id,
            config_version=request.config_version,
            model_versions=self._model_versions(),
            confidence=CONFIDENCE_LOW,
            confidence_score=0.0,
            why="No candidate action scored above threshold this cycle; holding.",
        )
        return self._persist(decision, event="DecisionHold")

    def _capability_gap(
        self,
        request: DecisionRequest,
        *,
        capability: str,
        detail: str = "",
        rule: DecisionRule | None = None,
    ) -> Decision:
        """Record an honest 'I can't do this — here's what's missing' decision (P15)."""
        why = f"Cannot decide: missing capability '{capability}'."
        if detail:
            why += f" {detail}"
        why += " Recorded as a capability gap for the operator to resolve."
        decision = Decision(
            mission_id=request.mission_id,
            mission_type=request.mission_type,
            action_kind=ACTION_CAPABILITY_GAP,
            action={"kind": ACTION_CAPABILITY_GAP, "capability": capability, "detail": detail},
            decision_rule=(getattr(rule, "mission_type", None) if rule else None),
            rule_version=(str(getattr(rule, "VERSION", "")) if rule else None),
            config_id=request.config_id,
            config_version=request.config_version,
            model_versions=self._model_versions(),
            confidence=CONFIDENCE_LOW,
            confidence_score=0.0,
            why=why,
        )
        self._logger.info("capability gap for mission_type=%s: %s", request.mission_type, capability)
        return self._persist(decision, event="DecisionCapabilityGap")

    # --- internals ------------------------------------------------------
    def _intelligence_context(self) -> IntelligenceContext:
        """The lazy composed view of the intelligences a rule scores against (§D.2)."""
        return IntelligenceContext(
            engineering=self._engineering,
            research=self._research,
            personal=self._personal,
            knowledge=self._knowledge,
            logger=self._logger,
        )

    def _influences(self, request: DecisionRequest) -> list[dict[str, Any]]:
        if self._policy is None:
            return []
        scope = f"mission:{request.mission_id}" if request.mission_id else None
        try:
            return self._policy.advice_influence(scope=scope)
        except Exception as exc:  # noqa: BLE001 - policy is advisory; never block a decision
            self._logger.warning("policy influence failed: %s", exc)
            return []

    def _model_versions(self) -> dict[str, Any]:
        base = {"decision_engine": self.VERSION}
        if self._versions_provider is None:
            return base
        try:
            extra = self._versions_provider() or {}
            base.update(extra)
        except Exception as exc:  # noqa: BLE001 - version stamping must never break a decision
            self._logger.warning("versions_provider failed: %s", exc)
        return base

    def _why(self, decision: Decision, chosen: ScoredOption, rejected: list[ScoredOption]) -> str:
        deterministic = self._deterministic_why(decision, chosen, rejected)
        if self._narrator is None:
            return deterministic
        try:
            narrated = self._narrator.narrate(decision.to_dict(), fallback=deterministic)
            return str(narrated).strip() or deterministic
        except Exception as exc:  # noqa: BLE001 - narration is cosmetic; deterministic text wins
            self._logger.warning("decision narration failed: %s", exc)
            return deterministic

    @staticmethod
    def _deterministic_why(
        decision: Decision, chosen: ScoredOption, rejected: list[ScoredOption]
    ) -> str:
        parts = [
            f"Chose '{chosen.key}' (score {chosen.final_score:.4f}, "
            f"{decision.confidence} confidence)."
        ]
        if chosen.rationale:
            parts.append(chosen.rationale)
        if chosen.policy_ids:
            parts.append(f"Influenced by policy {', '.join(chosen.policy_ids)}.")
        if rejected:
            runner = rejected[0]
            parts.append(f"Preferred over '{runner.key}' ({runner.final_score:.4f}).")
        return " ".join(parts)

    def _persist(self, decision: Decision, *, event: str) -> Decision:
        row = self._repo.record(decision)
        if row:
            decision.id = row.get("id")
            decision.created_at = row.get("created_at")
        self._emit(event, decision)
        # P14 human gate: a side-effecting decision opens an approval; the operator decides before it acts.
        if decision.requires_approval and self._approvals is not None:
            try:
                self._approvals.propose(decision)
            except Exception:  # noqa: BLE001 - a failed proposal must not void the recorded decision
                self._logger.exception("failed to propose approval for decision %s", decision.id)
        return decision

    def _emit(self, event_type: str, decision: Decision) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(
                event_type,
                {
                    "decision_id": str(decision.id) if decision.id else None,
                    "mission_id": str(decision.mission_id) if decision.mission_id else None,
                    "mission_type": decision.mission_type,
                    "action_kind": decision.action_kind,
                    "confidence": decision.confidence,
                    "requires_approval": decision.requires_approval,
                },
                source=self.name,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break a decision
            self._logger.exception("failed to emit %s", event_type)
