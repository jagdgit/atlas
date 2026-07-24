"""Verification Engine (Stage 2, S15, D8/§5a) — the differentiator.

Between *Research* and *Report*, the Verification Engine turns gathered evidence into
**defensible conclusions**: it measures numeric **convergence** (agreement, not count),
assigns a **calculated confidence** from evidence quality + convergence + contradictions,
and enforces a per-job **Evidence Budget** — telling the planner *continue vs finalize*.
"""

from __future__ import annotations

from atlas.verification.engine import (
    BudgetDecision,
    EvidenceBudget,
    VerificationEngine,
)
from atlas.verification.service import VerificationService
from atlas.verification.adapt import finding_row_to_claim, claim_verification_writeback
from atlas.verification.queue import KnowledgeVerificationService
from atlas.verification.contradiction import (
    ContradictionHit,
    attach_contradictions,
    contradiction_reason,
    find_contradictions,
)
from atlas.verification.trust import (
    DEFAULT_TRUST_WEIGHTS,
    build_trust_profile,
    overall_trust_from_finding,
)

__all__ = [
    "VerificationEngine",
    "EvidenceBudget",
    "BudgetDecision",
    "VerificationService",
    "KnowledgeVerificationService",
    "finding_row_to_claim",
    "claim_verification_writeback",
    "ContradictionHit",
    "find_contradictions",
    "attach_contradictions",
    "contradiction_reason",
    "DEFAULT_TRUST_WEIGHTS",
    "build_trust_profile",
    "overall_trust_from_finding",
]
