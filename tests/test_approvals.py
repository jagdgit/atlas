"""Hermetic tests for the human-approval gate (Phase D · §D.3, P14).

Covers the full lifecycle (propose → approve → apply → revert), the reject branch, the DD3 bypass for
non-side-effecting decisions, illegal transitions, the P15 "approved but no applier" boundary, and the
engine's automatic propose-on-``requires_approval`` wiring. No DB — a fake repo models the single-row
state machine and a fake applier records apply/revert with before/after snapshots.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from atlas.decision import (
    ACTION_RECOMMEND,
    ApplierRegistry,
    ApprovalError,
    ApprovalService,
    Decision,
    DecisionEngine,
    DecisionRequest,
    DecisionRuleRegistry,
    ScoredOption,
)


class _FakeApprovalRepo:
    """In-memory stand-in for ApprovalRepository: one mutable row per approval."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def create(self, *, decision_id, mission_id, mission_type, action, requested_by=None, note=None):
        rid = uuid.uuid4()
        row = {
            "id": rid,
            "decision_id": decision_id,
            "mission_id": mission_id,
            "mission_type": mission_type,
            "action": action,
            "status": "proposed",
            "note": note,
            "requested_by": requested_by,
            "requested_at": datetime.now(timezone.utc),
            "decided_by": None,
            "decided_at": None,
            "applied_at": None,
            "before": None,
            "after": None,
            "updated_at": datetime.now(timezone.utc),
        }
        self.rows[str(rid)] = row
        return dict(row)

    def get(self, approval_id):
        row = self.rows.get(str(approval_id))
        return dict(row) if row else None

    def list(self, *, status=None, mission_id=None, mission_type=None, limit=100):
        out = [
            dict(r)
            for r in self.rows.values()
            if (status is None or r["status"] == status)
            and (mission_id is None or str(r["mission_id"]) == str(mission_id))
            and (mission_type is None or r["mission_type"] == mission_type)
        ]
        return out[:limit]

    def transition(self, approval_id, status, *, actor=None, note=None, before=None, after=None):
        row = self.rows[str(approval_id)]
        row["status"] = status
        if actor is not None:
            row["decided_by"] = actor
        if note is not None:
            row["note"] = note
        if status in ("approved", "rejected"):
            row["decided_at"] = datetime.now(timezone.utc)
        if status == "applied":
            row["applied_at"] = datetime.now(timezone.utc)
        if before is not None:
            row["before"] = before
        if after is not None:
            row["after"] = after
        return dict(row)


class _FakeApplier:
    mission_type = "demo"
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self.applied: list[dict] = []
        self.reverted: list[dict] = []
        self.state = {"position": 0}

    def apply(self, action, *, decision_id, mission_id):
        before = dict(self.state)
        self.state["position"] += int(action.get("payload", {}).get("qty", 1))
        after = dict(self.state)
        self.applied.append({"action": action, "before": before, "after": after})
        return {"before": before, "after": after}

    def revert(self, action, *, before, after):
        self.reverted.append({"action": action, "before": before, "after": after})
        self.state = dict(before)


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


def _decision(*, requires_approval=True, action=None):
    return Decision(
        id=uuid.uuid4(),
        mission_id="m1",
        mission_type="demo",
        action_kind=ACTION_RECOMMEND,
        action=action or {"kind": ACTION_RECOMMEND, "key": "buy", "payload": {"qty": 3}},
        why="strong signal",
        requires_approval=requires_approval,
    )


def _service(*, with_applier=True):
    repo = _FakeApprovalRepo()
    events = _FakeEvents()
    appliers = ApplierRegistry()
    applier = _FakeApplier() if with_applier else None
    if applier is not None:
        appliers.register(applier)
    svc = ApprovalService(repo, appliers=appliers, events=events)
    return svc, repo, events, applier


def test_non_side_effecting_decision_bypasses_gate():
    svc, repo, events, _ = _service()
    assert svc.propose(_decision(requires_approval=False)) is None
    assert repo.rows == {}
    assert events.emitted == []


def test_full_lifecycle_propose_approve_apply_revert():
    svc, repo, events, applier = _service()
    d = _decision()

    proposed = svc.propose(d)
    assert proposed["status"] == "proposed"
    assert proposed["action"]["key"] == "buy"
    assert str(proposed["decision_id"]) == str(d.id)
    aid = proposed["id"]

    approved = svc.approve(aid, actor="operator")
    assert approved["status"] == "approved" and approved["decided_by"] == "operator"
    assert not applier.applied  # nothing executed on approve alone

    applied = svc.apply(aid, actor="operator")
    assert applied["status"] == "applied"
    assert applier.applied and applier.state["position"] == 3
    assert applied["before"] == {"position": 0} and applied["after"] == {"position": 3}

    reverted = svc.revert(aid, actor="operator")
    assert reverted["status"] == "reverted"
    assert applier.reverted and applier.state == {"position": 0}  # world restored

    kinds = [e[0] for e in events.emitted]
    assert kinds == [
        "ApprovalProposed",
        "ApprovalApproved",
        "ApprovalApplied",
        "ApprovalReverted",
    ]


def test_reject_blocks_apply():
    svc, _, _, _ = _service()
    aid = svc.propose(_decision())["id"]
    rejected = svc.reject(aid, actor="operator", note="too risky")
    assert rejected["status"] == "rejected" and rejected["note"] == "too risky"
    with pytest.raises(ApprovalError):
        svc.apply(aid)


def test_apply_requires_prior_approval():
    svc, _, _, applier = _service()
    aid = svc.propose(_decision())["id"]
    with pytest.raises(ApprovalError):
        svc.apply(aid)  # still 'proposed'
    assert not applier.applied


def test_revert_requires_applied():
    svc, _, _, _ = _service()
    aid = svc.propose(_decision())["id"]
    svc.approve(aid)
    with pytest.raises(ApprovalError):
        svc.revert(aid)  # still 'approved'


def test_double_approve_is_rejected():
    svc, _, _, _ = _service()
    aid = svc.propose(_decision())["id"]
    svc.approve(aid)
    with pytest.raises(ApprovalError):
        svc.approve(aid)


def test_apply_without_registered_applier_is_honest_error():
    svc, _, _, _ = _service(with_applier=False)  # P15 boundary
    aid = svc.propose(_decision())["id"]
    svc.approve(aid)
    with pytest.raises(ApprovalError, match="no ActionApplier registered"):
        svc.apply(aid)


def test_list_pending_returns_only_proposed():
    svc, _, _, _ = _service()
    a = svc.propose(_decision())["id"]
    b = svc.propose(_decision())["id"]
    svc.approve(b)
    pending = svc.list_pending()
    ids = {str(r["id"]) for r in pending}
    assert str(a) in ids and str(b) not in ids


def test_engine_auto_proposes_only_for_side_effecting_decisions():
    class _SideEffectRule:
        mission_type = "demo"
        VERSION = "1.0.0"

        def score(self, request, context):
            return [ScoredOption(key="buy", score=0.9, side_effecting=True, payload={"qty": 2})]

    class _ReadOnlyRule:
        mission_type = "demo"
        VERSION = "1.0.0"

        def score(self, request, context):
            return [ScoredOption(key="report", score=0.9, side_effecting=False)]

    class _EngRepo:
        def record(self, decision):
            return {"id": uuid.uuid4(), "created_at": datetime.now(timezone.utc)}

    def _run(rule):
        reg = DecisionRuleRegistry()
        reg.register(rule)
        approvals, appr_repo, _, _ = _service()
        engine = DecisionEngine(_EngRepo(), rules=reg, approvals=approvals)
        engine.decide(DecisionRequest(mission_id="m1", mission_type="demo"))
        return appr_repo

    side_repo = _run(_SideEffectRule())
    assert len(side_repo.rows) == 1
    assert next(iter(side_repo.rows.values()))["action"]["key"] == "buy"

    read_repo = _run(_ReadOnlyRule())
    assert read_repo.rows == {}  # DD3: read/advice never enters the gate
