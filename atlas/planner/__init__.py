"""Planner layer (Sprint 10, D2).

Turns a message/objective into an ordered ``Plan`` of ``PlanStep``s, each naming a
capability + args. v0 is a **deterministic rule-based router** (D2a): predictable,
testable, no LLM latency; the LLM is used only to compose the answer, never to
route. Open-ended requests fall through to the ReAct execution strategy so we
never dead-end. LLM decomposition for research jobs arrives at S12 (D2c).

Mode-agnostic (D1): a chat turn runs the plan inline; a job (S12) persists the same
Plan/PlanStep to ``job.steps`` and runs them via the scheduler. Same objects.
"""

from __future__ import annotations

from atlas.planner.planner import Intent, Plan, Planner, PlanStep

__all__ = ["Planner", "Plan", "PlanStep", "Intent"]
