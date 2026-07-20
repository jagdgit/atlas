"""Autonomous multi-round research orchestration (Stage 2, S21).

The capstone that wires the Stage-2 pieces into a live loop: **gather → verify → decide**.
Given an objective, ``ResearchService`` repeatedly gathers evidence from the research
tools (scholar, then web), folds each source into a single ``EvidenceGraph`` claim,
re-runs the ``VerificationEngine`` to recompute calculated confidence + numeric
convergence, and consults the ``EvidenceBudget`` to decide whether to **stop** (criteria
met / convergence reached / iteration cap) or **continue** with the next query — the
stopping rule is convergence, not a fixed source count (§5a.4). When it stops it emits a
verified scientific-review **report**.

Honest and resilient (R2/R3): providers are resolved lazily and a missing scholar/search
capability degrades to an ``unavailable`` outcome; the loop never raises into the caller.
"""

from __future__ import annotations

from atlas.research.service import (
    RESEARCH_EMPTY,
    RESEARCH_ERROR,
    RESEARCH_OK,
    RESEARCH_UNAVAILABLE,
    ResearchService,
    extract_value,
    query_plan,
)
from atlas.research.decision_rule import MISSION_TYPE_RESEARCH, ResearchDecisionRule
from atlas.research.learn import promote_research

__all__ = [
    "ResearchService",
    "ResearchDecisionRule",
    "MISSION_TYPE_RESEARCH",
    "promote_research",
    "query_plan",
    "extract_value",
    "RESEARCH_OK",
    "RESEARCH_EMPTY",
    "RESEARCH_UNAVAILABLE",
    "RESEARCH_ERROR",
]
