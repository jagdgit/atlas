"""Mission Manager subsystem (Phase A · PHASE_A_PLAN §A.1).

The **Mission layer above Jobs** — long-lived, operator-created objectives that own Jobs and
(later) Persistent Workers, run off a versioned Configuration, and journal every important
action for explainability (P9). Everything a user "wants Atlas to do over time" is a Mission,
never a new intelligence (P5/P7).
"""

from __future__ import annotations

from atlas.missions.repository import MissionRepository
from atlas.missions.service import MissionError, MissionService

__all__ = ["MissionService", "MissionRepository", "MissionError"]
