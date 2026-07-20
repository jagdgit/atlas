"""Self-improvement mission building blocks (Phase D · §D.10).

Runs the Stage-3B hermetic eval harness, turns regressions into Decision-Engine
recommendations (gated when side-effecting), and surfaces a board for the
Operations Dashboard. Atlas recommends; the operator decides (P14).
"""

from atlas.improvement.analyze import analyze_baseline, flatten_metrics
from atlas.improvement.board import ImprovementBoard
from atlas.improvement.decision_rule import (
    MISSION_TYPE_SELF_IMPROVEMENT,
    SelfImprovementDecisionRule,
)

__all__ = [
    "ImprovementBoard",
    "SelfImprovementDecisionRule",
    "MISSION_TYPE_SELF_IMPROVEMENT",
    "analyze_baseline",
    "flatten_metrics",
]
