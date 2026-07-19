"""Live-DB tests for the Knowledge Candidate inbox (Phase C · §C.3, CC11).

Candidates are the transient inbox of the Consolidator: readers emit them, the Consolidator
consumes them, and consumed rows are prunable. Skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.repositories.candidate_repo import CandidateRepository


@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_candidate_create_and_pending_queue(db):
    repo = CandidateRepository(db)
    token = uuid.uuid4().hex
    mission = str(uuid.uuid4())

    row = repo.create(
        f"Atlas prefers content-addressed assets {token}",
        claim_type="prose",
        domain="external",
        evidence_ref={"asset_id": "a-1", "asset_version": 1, "source": "document",
                      "reader": "document", "reader_version": "1.0.0", "mission_id": mission},
        provenance={"source": "document"},
        confidence="MEDIUM",
        confidence_score=0.6,
    )
    assert row["status"] == "pending"
    # Soft provenance columns are backfilled from evidence_ref.
    assert str(row["mission_id"]) == mission
    assert row["reader"] == "document" and row["reader_version"] == "1.0.0"

    pending_ids = {str(c["id"]) for c in repo.list_pending(limit=500)}
    assert str(row["id"]) in pending_ids


def test_candidate_consume_links_finding_and_leaves_queue(db):
    repo = CandidateRepository(db)
    token = uuid.uuid4().hex
    c = repo.create(f"claim {token}", domain="external")
    finding_id = str(uuid.uuid4())

    consumed = repo.mark_consumed(c["id"], finding_id=finding_id)
    assert consumed["status"] == "consumed"
    assert str(consumed["consolidated_finding_id"]) == finding_id
    assert consumed["consumed_at"] is not None

    pending_ids = {str(x["id"]) for x in repo.list_pending(limit=500)}
    assert str(c["id"]) not in pending_ids  # no longer in the work queue


def test_candidate_prune_removes_only_old_consumed(db):
    repo = CandidateRepository(db)
    token = uuid.uuid4().hex

    fresh = repo.create(f"fresh {token}", domain="external")
    repo.mark_consumed(fresh["id"], finding_id=str(uuid.uuid4()))
    still_pending = repo.create(f"pending {token}", domain="external")

    # Nothing consumed within the last 30 days is pruned; pending is never pruned.
    removed = repo.prune_consumed(older_than_days=30)
    assert isinstance(removed, int)
    assert repo.get(fresh["id"]) is not None       # consumed but recent → kept
    assert repo.get(still_pending["id"]) is not None

    # A zero-day window prunes the just-consumed row (age >= 0), but not the pending one.
    repo.prune_consumed(older_than_days=0)
    assert repo.get(fresh["id"]) is None
    assert repo.get(still_pending["id"]) is not None
    repo.mark_discarded(still_pending["id"])
    repo.prune_consumed(older_than_days=0)
    assert repo.get(still_pending["id"]) is None
