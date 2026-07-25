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
from atlas.decision.approvals import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_REVERTED,
    ActionApplier,
    ApplierRegistry,
    ApprovalError,
    ApprovalService,
)
from atlas.decision.context import IntelligenceContext
from atlas.decision.engine import DecisionEngine
from atlas.decision.knowledge import (
    bias_recommendations,
    decision_knowledge_tags,
    experience_id_from_result,
    link_metadata,
    outcome_label,
    should_enable_decision_bias,
)
from atlas.decision.feedback import (
    build_feedback_journal,
    collect_outcome_feedback,
    difference_label,
    feedback_metadata,
    feedback_tags,
    record_feedback_loop,
    should_enable_feedback_bias,
)
from atlas.decision.rules import (
    CapabilityGap,
    DecisionRule,
    DecisionRuleRegistry,
    apply_policy_influence,
)

__all__ = [
    "DecisionEngine",
    "bias_recommendations",
    "build_feedback_journal",
    "collect_outcome_feedback",
    "decision_knowledge_tags",
    "difference_label",
    "experience_id_from_result",
    "feedback_metadata",
    "feedback_tags",
    "link_metadata",
    "outcome_label",
    "record_feedback_loop",
    "should_enable_decision_bias",
    "should_enable_feedback_bias",
    "DecisionRequest",
    "Decision",
    "ScoredOption",
    "derive_confidence",
    "DecisionRule",
    "DecisionRuleRegistry",
    "IntelligenceContext",
    "CapabilityGap",
    "apply_policy_influence",
    "ApprovalService",
    "ApplierRegistry",
    "ActionApplier",
    "ApprovalError",
    "STATUS_PROPOSED",
    "STATUS_APPROVED",
    "STATUS_REJECTED",
    "STATUS_APPLIED",
    "STATUS_REVERTED",
    "ACTION_RECOMMEND",
    "ACTION_HOLD",
    "ACTION_CAPABILITY_GAP",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
]
