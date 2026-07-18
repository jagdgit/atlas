"""The Verification Engine (§5a.3, 5a.4, 5a.6).

Pure, deterministic scoring — no LLM, no I/O — so it is fast, hermetic, and auditable:

- **convergence(values)**: agreement of numeric estimates (largest cluster within a
  relative tolerance), in [0, 1]. Tight cluster → ~1.0; scattered → ~0.
- **verify_claim(claim)**: sets a *calculated* confidence (HIGH/MEDIUM/LOW/INSUFFICIENT)
  from evidence quality (levels), convergence, and contradictions, plus a reasoning
  trace explaining exactly why.
- **decide(claim, budget, iteration)**: enforces the Evidence Budget and returns a
  ``stop``/``continue`` decision with the unmet criteria — the stopping rule is
  *convergence*, never a fixed paper count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import fmean, median
from typing import Any

from atlas.evidence.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    Claim,
    level_name,
)


@dataclass
class EvidenceBudget:
    """Per-job stopping criteria (§5a.4). Config-defaulted, planner-tunable."""

    min_sources: int = 5
    min_peer_reviewed: int = 3   # L4+
    min_government: int = 1      # L3+
    convergence: float = 0.90    # agreement threshold to stop
    max_search_iterations: int = 20

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_sources": self.min_sources,
            "min_peer_reviewed": self.min_peer_reviewed,
            "min_government": self.min_government,
            "convergence": self.convergence,
            "max_search_iterations": self.max_search_iterations,
        }


@dataclass
class BudgetDecision:
    decision: str  # "stop" | "continue"
    convergence: float
    met: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def should_stop(self) -> bool:
        return self.decision == "stop"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "convergence": round(self.convergence, 3),
            "met": self.met,
            "reasons": self.reasons,
        }


class VerificationEngine:
    name = "verification"

    def __init__(self, *, numeric_tolerance: float = 0.15) -> None:
        # A value "agrees" if within tolerance * magnitude of a cluster anchor.
        self._tolerance = numeric_tolerance

    # --- convergence (§5a.3) -------------------------------------------
    def convergence(self, values: list[float]) -> float:
        vals = [float(v) for v in values if v is not None]
        if len(vals) < 2:
            return 0.0  # can't converge on a single point
        magnitude = max(abs(fmean(vals)), 1e-9)
        window = self._tolerance * magnitude
        best = 0
        for anchor in vals:
            cluster = sum(1 for v in vals if abs(v - anchor) <= window)
            best = max(best, cluster)
        return best / len(vals)

    # --- confidence (§5a.3) --------------------------------------------
    def verify_claim(self, claim: Claim) -> Claim:
        supporting = claim.supporting
        contradicting = claim.contradicting
        values = claim.supporting_values()
        conv = self.convergence(values) if len(values) >= 2 else None

        # Count *independent studies*, not document representations: arxiv + ar5iv
        # of one paper must never read as two supporting sources (§5a.3 integrity).
        n = self._independent(supporting)
        n_l4 = self._independent(
            [e for e in supporting if e.evidence_level >= LEVEL_PEER_REVIEWED]
        )
        n_l3 = self._independent(
            [e for e in supporting if e.evidence_level >= LEVEL_GOVERNMENT]
        )
        n_contra = self._independent(contradicting)
        avg_level = fmean([e.evidence_level for e in supporting]) if supporting else 0.0
        quality = avg_level / 5.0

        # Numeric claims: convergence dominates; else fall back to quality alone.
        if conv is not None:
            score = 0.6 * conv + 0.4 * quality
        else:
            score = quality
        # Contradictions erode confidence.
        if n_contra:
            score *= max(0.4, 1.0 - 0.2 * n_contra)

        label = self._label(n, n_l3, conv, quality, n_contra, score)

        claim.convergence = conv
        claim.confidence = label
        claim.confidence_score = round(score, 3)
        claim.last_verified = date.today().isoformat()
        claim.verification_method = self._method(conv, n_l3)
        claim.reasoning_trace = self._trace(
            n, n_l3, n_l4, n_contra, avg_level, conv, score, label
        )
        return claim

    @staticmethod
    def _independent(items: list) -> int:
        """Distinct studies among evidence items (dedup by source identity)."""
        ids = {e.source_id for e in items if getattr(e, "source_id", "")}
        # Evidence without a source_id still counts as one anonymous study each.
        return len(ids) + sum(1 for e in items if not getattr(e, "source_id", ""))

    def _label(
        self, n: int, n_l3: int, conv: float | None, quality: float,
        n_contra: int, score: float,
    ) -> str:
        if n == 0:
            return CONFIDENCE_INSUFFICIENT
        # HIGH: multiple solid (L3+) *independent* sources that converge (§5a.3).
        if n_l3 >= 2 and (conv is not None and conv >= 0.8) and n_contra == 0:
            return CONFIDENCE_HIGH
        if n < 2:
            # A single study can't be HIGH; strong single source → LOW/MEDIUM by quality.
            return CONFIDENCE_MEDIUM if quality >= 0.8 and n_contra == 0 else CONFIDENCE_LOW
        # Fallback HIGH needs breadth too: a couple of low-authority sources that
        # merely agree is not high confidence (source diversity matters, §5a.3).
        if score >= 0.75 and n_contra == 0 and n >= 3:
            return CONFIDENCE_HIGH
        if score >= 0.5:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW

    @staticmethod
    def _method(conv: float | None, n_l3: int) -> str:
        if conv is not None:
            return f"numeric convergence ({conv:.0%}) across {n_l3} L3+ source(s)"
        return "qualitative assessment of evidence levels"

    @staticmethod
    def _trace(
        n: int, n_l3: int, n_l4: int, n_contra: int, avg_level: float,
        conv: float | None, score: float, label: str,
    ) -> list[str]:
        trace = [
            f"{n} independent source(s): {n_l4} peer-reviewed (L4+), {n_l3} L3+ "
            f"(avg level {avg_level:.1f}).",
        ]
        if conv is not None:
            trace.append(f"Numeric convergence = {conv:.0%} (agreement of estimates).")
        else:
            trace.append("No numeric values to converge; judged on evidence quality.")
        if n_contra:
            trace.append(f"{n_contra} contradicting source(s) lowered confidence.")
        # Explain the common "high convergence, low confidence" case so users don't
        # think the engine is broken: agreement is necessary but not sufficient.
        if (
            conv is not None
            and conv >= 0.8
            and label in (CONFIDENCE_LOW, CONFIDENCE_MEDIUM)
        ):
            if n < 2:
                trace.append(
                    "High agreement but only 1 independent study — insufficient "
                    "source diversity to raise confidence."
                )
            elif n_l3 < 2:
                trace.append(
                    f"High agreement across {n} source(s) but only {n_l3} are L3+ "
                    "(government/peer-reviewed) — more authoritative, independent "
                    "sources are needed to raise confidence."
                )
        trace.append(f"Confidence score = {score:.2f} → {label}.")
        return trace

    # --- Evidence Budget (§5a.4) ---------------------------------------
    def decide(self, claim: Claim, budget: EvidenceBudget, *, iteration: int = 0) -> BudgetDecision:
        supporting = claim.supporting
        n = self._independent(supporting)
        n_l4 = self._independent(
            [e for e in supporting if e.evidence_level >= LEVEL_PEER_REVIEWED]
        )
        n_l3 = self._independent(
            [e for e in supporting if e.evidence_level == LEVEL_GOVERNMENT]
        )
        values = claim.supporting_values()
        conv = self.convergence(values) if len(values) >= 2 else 0.0

        met = {
            "sources": n >= budget.min_sources,
            "peer_reviewed": n_l4 >= budget.min_peer_reviewed,
            "government": n_l3 >= budget.min_government,
            "convergence": conv >= budget.convergence,
        }
        reasons: list[str] = []
        if not met["sources"]:
            reasons.append(f"need ≥{budget.min_sources} sources (have {n})")
        if not met["peer_reviewed"]:
            reasons.append(f"need ≥{budget.min_peer_reviewed} peer-reviewed (have {n_l4})")
        if not met["government"]:
            reasons.append(f"need ≥{budget.min_government} government/lab (have {n_l3})")
        if not met["convergence"]:
            reasons.append(
                f"convergence {conv:.0%} < {budget.convergence:.0%} threshold"
            )

        if iteration >= budget.max_search_iterations:
            return BudgetDecision(
                "stop", conv, met,
                reasons=(reasons or []) + [
                    f"max_search_iterations ({budget.max_search_iterations}) reached"
                ],
            )
        if all(met.values()):
            return BudgetDecision("stop", conv, met, reasons=["all budget criteria met"])
        return BudgetDecision("continue", conv, met, reasons=reasons)

    # --- lifecycle (registered as a service) ---------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self):
        from atlas.services.base import HealthStatus

        return HealthStatus.ok(
            f"verification engine ready (tolerance {self._tolerance:.0%})",
            levels=level_name(5),
        )
