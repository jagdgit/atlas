"""Live-DB smoke for the Decision journal repository (Phase D · §D.1).

Exercises ``decision.decisions`` end-to-end against a real PostgreSQL (skipped if unreachable):
persist a full P9 record, read it back, filter by mission/type, and enumerate the capability-gap
backlog (P15). Requires migration 0039.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.decision import ACTION_CAPABILITY_GAP, ACTION_RECOMMEND, Decision
from atlas.repositories.decision_repo import DecisionRepository


@pytest.fixture(scope="module")
def repo():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield DecisionRepository(db)
    db.close()


def test_record_and_read_back_full_record(repo: DecisionRepository):
    mission_id = uuid.uuid4()
    d = Decision(
        mission_id=str(mission_id),
        mission_type="demo",
        action_kind=ACTION_RECOMMEND,
        action={"kind": ACTION_RECOMMEND, "key": "alpha", "payload": {"n": 1}},
        why="chose alpha",
        decision_rule="demo",
        rule_version="1.0.0",
        config_version=3,
        knowledge_refs=["k1", "k2"],
        model_versions={"decision_engine": "1.0.0"},
        policy_ids=["P-1"],
        confidence="high",
        confidence_score=0.87,
        alternatives_rejected=[{"key": "beta", "score": 0.2}],
        requires_approval=True,
    )
    row = repo.record(d)
    assert row["id"] is not None

    got = repo.get(row["id"])
    assert got is not None
    assert got["mission_type"] == "demo"
    assert got["action"]["key"] == "alpha"
    assert got["knowledge_refs"] == ["k1", "k2"]
    assert got["confidence"] == "high"
    assert got["requires_approval"] is True

    mine = repo.list(mission_id=mission_id)
    assert any(str(r["id"]) == str(row["id"]) for r in mine)


def test_capability_gap_backlog(repo: DecisionRepository):
    mission_id = uuid.uuid4()
    gap = Decision(
        mission_id=str(mission_id),
        mission_type="demo",
        action_kind=ACTION_CAPABILITY_GAP,
        action={"kind": ACTION_CAPABILITY_GAP, "capability": "market_data:NASDAQ"},
        why="missing data source",
    )
    row = repo.record(gap)
    gaps = repo.list_gaps(limit=200)
    assert any(str(g["id"]) == str(row["id"]) for g in gaps)
    assert all(g["action_kind"] == "capability_gap" for g in gaps)
