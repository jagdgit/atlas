"""Hermetic tests for SelfImprovementWatcher + board + gated applier (Phase D · §D.10)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.eval.baseline import BaselineReport
from atlas.improvement.applier import SelfImprovementApplier
from atlas.improvement.board import ImprovementBoard
from atlas.improvement.decision_rule import SelfImprovementDecisionRule
from atlas.workers.base import TickContext
from atlas.workers.self_improvement import SelfImprovementWatcher


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def record(self, decision):
        self.rows.append(decision)
        return {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc)}


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


class _FakeApprovals:
    def __init__(self) -> None:
        self.proposed: list[Any] = []

    def propose(self, decision, *, requested_by=None):
        self.proposed.append(decision)
        return {"id": "appr-1", "status": "proposed"}


def _engine(approvals=None) -> DecisionEngine:
    reg = DecisionRuleRegistry()
    reg.register(SelfImprovementDecisionRule())
    return DecisionEngine(_FakeDecisionRepo(), rules=reg, approvals=approvals)


def _report(*, precision: float = 0.9) -> BaselineReport:
    return BaselineReport(
        milestone="3B.0",
        version="test",
        captured_at="2026-01-01T00:00:00Z",
        sections={
            "retrieval_hermetic": {
                "precision_at_k": precision,
                "recall_at_k": 0.9,
                "n_cases": 3,
            },
            "notes": {},
        },
    )


def _ctx(config=None, state=None, *, version=1, inputs=None):
    return TickContext(
        worker_id="w1",
        mission_id=str(uuid.uuid4()),
        config=config or {"gate_fixes": True, "regression_drop": 0.05},
        config_version=version,
        state=state or {},
        inputs=inputs or [],
    )


def test_tick_detects_regression_and_gates_fix(tmp_path):
    events = _FakeEvents()
    approvals = _FakeApprovals()
    engine = _engine(approvals=approvals)
    board = ImprovementBoard(tmp_path)
    worker = SelfImprovementWatcher(
        decision_engine=engine, board=board, events=events
    )

    # Establish a healthy baseline in state, then regress.
    state = {
        "last_metrics": {
            "retrieval_hermetic.precision_at_k": 0.95,
            "retrieval_hermetic.recall_at_k": 0.9,
        }
    }
    with patch(
        "atlas.workers.self_improvement.run_baseline_suite",
        return_value=_report(precision=0.4),
    ):
        result = worker.do_tick(_ctx(state=state))

    assert result.state["last_finding_count"] >= 1
    assert engine._repo.rows
    decision = engine._repo.rows[-1]
    assert decision.requires_approval is True  # propose_fix is gated
    assert approvals.proposed  # engine auto-proposed
    assert any(t == "SelfImprovementFinding" for t, _ in events.emitted)
    snap = board.snapshot()
    assert snap["finding_count"] >= 1
    assert snap["last_run"] is not None


def test_fingerprint_skip(tmp_path):
    engine = _engine()
    board = ImprovementBoard(tmp_path)
    worker = SelfImprovementWatcher(decision_engine=engine, board=board)
    with patch(
        "atlas.workers.self_improvement.run_baseline_suite",
        return_value=_report(precision=0.9),
    ):
        r1 = worker.do_tick(_ctx())
        n = len(engine._repo.rows)
        r2 = worker.do_tick(_ctx(state=r1.state))
    assert len(engine._repo.rows) == n
    assert r2.note == "" or "no change" in r2.note


def test_applier_records_and_reverts(tmp_path):
    board = ImprovementBoard(tmp_path)
    applier = SelfImprovementApplier(board)
    snap = applier.apply(
        {"kind": "recommend", "payload": {"kind": "propose_fix", "finding_id": "f1"}},
        decision_id="d1",
        mission_id="m1",
    )
    assert board.snapshot()["approved"]
    applier.revert({}, before=snap["before"], after=snap["after"])
    assert board.snapshot()["approved"] == []


def test_config_version_pickup(tmp_path):
    engine = _engine()
    worker = SelfImprovementWatcher(
        decision_engine=engine, board=ImprovementBoard(tmp_path)
    )
    with patch(
        "atlas.workers.self_improvement.run_baseline_suite",
        return_value=_report(),
    ):
        result = worker.do_tick(_ctx(version=5))
    assert result.state["config_version"] == 5
    assert "config v5 picked up" in result.note
