"""Policy layer (Phase C · §C.5, CC8) — durable operator rules that *influence* retrieval/advice.

Policy is one of the five things Atlas holds (Knowledge, Experience, **Policy**, Configuration,
Mission State). Rules nudge ranking/inclusion; they never act on the world or arbitrate decisions
(that is the Phase-D Decision Engine). Every edit is journaled + reversible.
"""

from __future__ import annotations

from atlas.policy.service import POLICY_INFLUENCE_MAX, PolicyService

__all__ = ["PolicyService", "POLICY_INFLUENCE_MAX"]
