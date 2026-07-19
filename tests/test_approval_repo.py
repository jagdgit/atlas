"""Live-DB smoke for the approval-gate repository (Phase D · §D.3).

Exercises ``decision.approvals`` end-to-end against a real PostgreSQL (skipped if unreachable): create a
proposed row, walk it through approve → apply (with before/after snapshots) → revert, and confirm the
pending queue only surfaces proposed rows. Requires migration 0040.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.repositories.approval_repo import ApprovalRepository


@pytest.fixture(scope="module")
def repo():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield ApprovalRepository(db)
    db.close()


def test_lifecycle_and_snapshots(repo: ApprovalRepository):
    mission_id = uuid.uuid4()
    row = repo.create(
        decision_id=uuid.uuid4(),
        mission_id=mission_id,
        mission_type="demo",
        action={"kind": "recommend", "key": "buy", "payload": {"qty": 3}},
        requested_by="tester",
    )
    aid = row["id"]
    assert row["status"] == "proposed"
    assert row["action"]["key"] == "buy"

    approved = repo.transition(aid, "approved", actor="operator")
    assert approved["status"] == "approved"
    assert approved["decided_by"] == "operator" and approved["decided_at"] is not None

    applied = repo.transition(
        aid, "applied", before={"position": 0}, after={"position": 3}
    )
    assert applied["status"] == "applied" and applied["applied_at"] is not None
    assert applied["before"] == {"position": 0} and applied["after"] == {"position": 3}

    reverted = repo.transition(aid, "reverted", actor="operator")
    assert reverted["status"] == "reverted"

    got = repo.get(aid)
    assert got["status"] == "reverted"
    assert got["before"] == {"position": 0}  # snapshot preserved across revert


def test_pending_queue_only_proposed(repo: ApprovalRepository):
    mission_id = uuid.uuid4()
    proposed = repo.create(
        decision_id=uuid.uuid4(), mission_id=mission_id, mission_type="demo", action={"k": 1}
    )
    decided = repo.create(
        decision_id=uuid.uuid4(), mission_id=mission_id, mission_type="demo", action={"k": 2}
    )
    repo.transition(decided["id"], "rejected", actor="operator", note="no")

    pending = repo.list(status="proposed", mission_id=mission_id)
    ids = {str(r["id"]) for r in pending}
    assert str(proposed["id"]) in ids and str(decided["id"]) not in ids
