"""Live-DB smoke for self-improvement decisions + approval gate (Phase D · §D.10)."""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.decision.approvals import ApprovalService
from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.improvement.applier import SelfImprovementApplier
from atlas.improvement.board import ImprovementBoard
from atlas.improvement.decision_rule import SelfImprovementDecisionRule
from atlas.repositories.approval_repo import ApprovalRepository
from atlas.repositories.decision_repo import DecisionRepository


@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_gated_fix_round_trips_approval(db, tmp_path):
    board = ImprovementBoard(tmp_path)
    approvals = ApprovalService(ApprovalRepository(db))
    approvals.register_applier(SelfImprovementApplier(board))
    reg = DecisionRuleRegistry()
    reg.register(SelfImprovementDecisionRule())
    engine = DecisionEngine(DecisionRepository(db), rules=reg, approvals=approvals)

    finding = {
        "id": "regression:retrieval_hermetic.precision_at_k",
        "metric": "retrieval_hermetic.precision_at_k",
        "kind": "regression",
        "severity": "high",
        "current": 0.2,
        "previous": 0.9,
        "floor": 0.5,
    }
    decision = engine.decide(
        DecisionRequest(
            mission_id=str(uuid.uuid4()),
            mission_type="self_improvement",
            context={"findings": [finding], "gate_fixes": True},
        )
    )
    assert decision.requires_approval is True
    assert decision.action["payload"]["kind"] == "propose_fix"

    pending = approvals.list_pending()
    match = [p for p in pending if str(p.get("decision_id")) == str(decision.id)]
    assert match
    aid = match[0]["id"]
    approvals.approve(aid, actor="tester")
    applied = approvals.apply(aid, actor="tester")
    assert applied["status"] == "applied"
    assert board.snapshot()["approved"]

    approvals.revert(aid, actor="tester")
    assert applied["id"]  # still the same row
    assert board.snapshot()["approved"] == []
