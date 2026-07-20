"""SelfImprovementApplier — records operator-approved improvement intents (Phase D · §D.10, P14).

Applying a gated ``propose_fix`` does **not** mutate production behaviour automatically —
it records the approved intent on the ImprovementBoard (and is reversible). That is the
honest P14 gate: Atlas may only act on itself after the operator approves, and today the
approved act is "track this remediation intent" (P15: deeper auto-remediation is a future
capability, not silently faked).
"""

from __future__ import annotations

from typing import Any


class SelfImprovementApplier:
    mission_type = "self_improvement"
    VERSION = "1.0.0"

    def __init__(self, board: Any) -> None:
        self._board = board

    def apply(self, action: dict[str, Any], *, decision_id: Any, mission_id: Any) -> dict[str, Any]:
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else action
        before = {"approved_count": len((self._board.snapshot().get("approved") or []))}
        row = self._board.record_approved(payload or action, decision_id=decision_id)
        after = {
            "approved_count": len((self._board.snapshot().get("approved") or [])),
            "recorded": row,
        }
        return {"before": before, "after": after}

    def revert(self, action: dict[str, Any], *, before: Any, after: Any) -> None:
        decision_id = None
        if isinstance(after, dict):
            recorded = after.get("recorded") or {}
            decision_id = recorded.get("decision_id")
        if decision_id:
            self._board.revert_approved(decision_id)
