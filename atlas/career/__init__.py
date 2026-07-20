"""Career mission building blocks (Phase D · §D.8) — recommend-only job matching.

The Job Watcher's DecisionRule lives here (parallel to ``atlas.research`` / ``atlas.trading``).
Nothing here applies to a job — Atlas ranks and notifies, the operator decides (P14).
"""

from atlas.career.decision_rule import JobDecisionRule, MISSION_TYPE_JOB_HUNTING

__all__ = ["JobDecisionRule", "MISSION_TYPE_JOB_HUNTING"]
