"""Technology / Security watch building blocks (Phase D · §D.9) — recommend-only.

Two thin mission templates (``technology_watch``, ``security_monitoring``) share one worker
pattern and one scoring rule family. Atlas ranks advisories and notifies; it never patches
or remediates (P14).
"""

from atlas.watch.decision_rule import (
    MISSION_TYPE_SECURITY,
    MISSION_TYPE_TECHNOLOGY,
    AdvisoryDecisionRule,
)

__all__ = [
    "AdvisoryDecisionRule",
    "MISSION_TYPE_TECHNOLOGY",
    "MISSION_TYPE_SECURITY",
]
