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

__all__ = [
    "VerificationEngine",
    "EvidenceBudget",
    "BudgetDecision",
    "VerificationService",
]
