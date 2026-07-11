"""VerificationService — the `verification` capability (S15).

Thin orchestration over the ``VerificationEngine`` + ``EvidenceGraph``: take a graph
(claims + evidence), verify every claim (calculated confidence + reasoning trace), and
attach a per-claim Evidence-Budget decision (continue vs finalize). Serialisable in and
out, so a research job (S17/S18) can persist the graph in its result and re-verify later.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.evidence.models import Claim, EvidenceGraph
from atlas.verification.engine import BudgetDecision, EvidenceBudget, VerificationEngine
from atlas.services.base import HealthStatus


class VerificationService:
    name = "verification"

    def __init__(
        self,
        engine: VerificationEngine | None = None,
        *,
        default_budget: EvidenceBudget | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = engine or VerificationEngine()
        self._budget = default_budget or EvidenceBudget()
        self._logger = logger or logging.getLogger("atlas.verification")

    @property
    def engine(self) -> VerificationEngine:
        return self._engine

    @property
    def default_budget(self) -> EvidenceBudget:
        return self._budget

    def verify_claim(self, claim: Claim) -> Claim:
        """Run the engine on one claim (mutates + returns it)."""
        return self._engine.verify_claim(claim)

    def decide(self, claim: Claim, *, iteration: int = 0, budget: EvidenceBudget | None = None) -> BudgetDecision:
        return self._engine.decide(claim, budget or self._budget, iteration=iteration)

    def verify(
        self, graph: dict[str, Any], budget: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Verify every claim in a serialised graph and attach budget decisions."""
        eg = EvidenceGraph.from_dict(graph)
        eb = self._merge_budget(budget)
        claims_out: list[dict[str, Any]] = []
        for claim in eg.claims.values():
            self._engine.verify_claim(claim)
            decision = self._engine.decide(claim, eb)
            row = claim.as_dict()
            row["budget_decision"] = decision.as_dict()
            claims_out.append(row)
        return {
            "claims": claims_out,
            "sources": [s.as_dict() for s in eg.sources.values()],
            "budget": eb.as_dict(),
        }

    def _merge_budget(self, override: dict[str, Any] | None) -> EvidenceBudget:
        if not override:
            return self._budget
        base = self._budget.as_dict()
        base.update({k: v for k, v in override.items() if k in base})
        return EvidenceBudget(**base)

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(
            "verification engine ready",
            convergence_threshold=self._budget.convergence,
        )
