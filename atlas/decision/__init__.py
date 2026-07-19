"""Atlas Decision Engine (Phase D) — the shared Kernel Service that answers "what should I do next?".

Deterministic core (Q7) + per-mission-type rule plugins (DD2), recommend-only with a human gate (P14)
and capability-gap honesty (P15). See ``docs/PHASE_D_PLAN.md`` §D.
"""

from atlas.decision.contracts import (
    ACTION_CAPABILITY_GAP,
    ACTION_HOLD,
    ACTION_RECOMMEND,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Decision,
    DecisionRequest,
    ScoredOption,
    derive_confidence,
)
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import (
    CapabilityGap,
    DecisionRule,
    DecisionRuleRegistry,
    apply_policy_influence,
)

__all__ = [
    "DecisionEngine",
    "DecisionRequest",
    "Decision",
    "ScoredOption",
    "derive_confidence",
    "DecisionRule",
    "DecisionRuleRegistry",
    "CapabilityGap",
    "apply_policy_influence",
    "ACTION_RECOMMEND",
    "ACTION_HOLD",
    "ACTION_CAPABILITY_GAP",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
]
