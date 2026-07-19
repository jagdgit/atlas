"""ApprovalService — the human gate for side-effecting decisions (Phase D · §D.3, P14).

*Atlas recommends; the operator decides.* A decision that would act on the world is not applied
automatically — the Decision Engine flags it ``requires_approval`` and this service **proposes** an
approval. The operator **approves** or **rejects**; only on approval may the action be **applied**, and
apply runs a registered :class:`ActionApplier` for that mission type which captures before/after state
so the action can be **reverted**. Read/advice/simulation decisions never enter the gate (DD3).

Every transition (propose/approve/reject/apply/revert) is emitted to the durable event bus so the whole
lifecycle is explainable (P9) and reversible. Missing an applier at apply time is an honest, explicit
error (the P15 boundary: Atlas approved something it has no capability to execute — add the applier).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from atlas.exceptions.base import AtlasError

if TYPE_CHECKING:
    from atlas.decision.contracts import Decision

STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"
STATUS_REVERTED = "reverted"


class ApprovalError(AtlasError):
    """An approval operation was invalid (missing row, illegal transition, no applier)."""


@runtime_checkable
class ActionApplier(Protocol):
    """Executes (and reverts) an approved side-effecting action for one mission type.

    ``apply`` returns a dict with ``before``/``after`` snapshots of whatever world state it touched, so
    ``revert`` can undo it. Appliers are the ONLY place the Decision layer acts on the world — and only
    after the human gate (P14).
    """

    mission_type: str
    VERSION: str

    def apply(self, action: dict[str, Any], *, decision_id: Any, mission_id: Any) -> dict[str, Any]:
        ...

    def revert(self, action: dict[str, Any], *, before: Any, after: Any) -> None:
        ...


class ApplierRegistry:
    def __init__(self) -> None:
        self._appliers: dict[str, ActionApplier] = {}

    def register(self, applier: ActionApplier) -> None:
        mtype = getattr(applier, "mission_type", None)
        if not mtype:
            raise ValueError("an ActionApplier must declare a non-empty mission_type")
        self._appliers[mtype] = applier

    def get(self, mission_type: str) -> ActionApplier | None:
        return self._appliers.get(mission_type)


class ApprovalService:
    name = "approvals"
    VERSION = "1.0.0"

    def __init__(
        self,
        repo: Any,
        *,
        appliers: ApplierRegistry | None = None,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._appliers = appliers or ApplierRegistry()
        self._events = events
        self._logger = logger or logging.getLogger("atlas.decision.approvals")

    def register_applier(self, applier: ActionApplier) -> None:
        self._appliers.register(applier)

    # --- gate lifecycle -------------------------------------------------
    def propose(self, decision: "Decision", *, requested_by: str | None = None) -> dict[str, Any] | None:
        """Open the gate for a side-effecting decision. Non-side-effecting decisions bypass it (DD3)."""
        if not getattr(decision, "requires_approval", False):
            return None
        row = self._repo.create(
            decision_id=decision.id,
            mission_id=decision.mission_id,
            mission_type=decision.mission_type,
            action=decision.action,
            requested_by=requested_by,
        )
        self._emit("ApprovalProposed", row)
        return row

    def approve(self, approval_id: str, *, actor: str | None = None) -> dict[str, Any]:
        self._require(approval_id, STATUS_PROPOSED)
        row = self._repo.transition(approval_id, STATUS_APPROVED, actor=actor)
        self._emit("ApprovalApproved", row)
        return row

    def reject(
        self, approval_id: str, *, actor: str | None = None, note: str | None = None
    ) -> dict[str, Any]:
        self._require(approval_id, STATUS_PROPOSED)
        row = self._repo.transition(approval_id, STATUS_REJECTED, actor=actor, note=note)
        self._emit("ApprovalRejected", row)
        return row

    def apply(self, approval_id: str, *, actor: str | None = None) -> dict[str, Any]:
        """Execute an approved action via its ActionApplier, recording before/after for revert (P14)."""
        current = self._require(approval_id, STATUS_APPROVED)
        applier = self._appliers.get(current["mission_type"])
        if applier is None:
            # P15 boundary: approved, but Atlas has no capability to execute it. Honest, explicit.
            raise ApprovalError(
                f"no ActionApplier registered for mission type '{current['mission_type']}'"
            )
        snapshot = applier.apply(
            current["action"], decision_id=current["decision_id"], mission_id=current["mission_id"]
        ) or {}
        row = self._repo.transition(
            approval_id, STATUS_APPLIED, actor=actor,
            before=snapshot.get("before"), after=snapshot.get("after"),
        )
        self._emit("ApprovalApplied", row)
        return row

    def revert(self, approval_id: str, *, actor: str | None = None) -> dict[str, Any]:
        """Undo an applied action from its recorded before/after snapshot (reversible, P14/P9)."""
        current = self._require(approval_id, STATUS_APPLIED)
        applier = self._appliers.get(current["mission_type"])
        if applier is None:
            raise ApprovalError(
                f"no ActionApplier registered for mission type '{current['mission_type']}'"
            )
        applier.revert(current["action"], before=current.get("before"), after=current.get("after"))
        row = self._repo.transition(approval_id, STATUS_REVERTED, actor=actor)
        self._emit("ApprovalReverted", row)
        return row

    # --- reads ----------------------------------------------------------
    def get(self, approval_id: str) -> dict[str, Any] | None:
        return self._repo.get(approval_id)

    def list(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._repo.list(**kwargs)

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._repo.list(status=STATUS_PROPOSED, limit=limit)

    # --- internals ------------------------------------------------------
    def _require(self, approval_id: str, expected: str) -> dict[str, Any]:
        row = self._repo.get(approval_id)
        if row is None:
            raise ApprovalError(f"no approval {approval_id}")
        if row["status"] != expected:
            raise ApprovalError(
                f"approval {approval_id} is '{row['status']}', expected '{expected}'"
            )
        return row

    def _emit(self, event_type: str, row: dict[str, Any] | None) -> None:
        if self._events is None or row is None:
            return
        try:
            self._events.emit(
                event_type,
                {
                    "approval_id": str(row.get("id")),
                    "decision_id": str(row["decision_id"]) if row.get("decision_id") else None,
                    "mission_id": str(row["mission_id"]) if row.get("mission_id") else None,
                    "mission_type": row.get("mission_type"),
                    "status": row.get("status"),
                },
                source=self.name,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break the gate
            self._logger.exception("failed to emit %s", event_type)
