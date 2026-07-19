"""Live-DB tests for the finding lineage / evidence graph (Phase C · §C.3, CC12 / P9).

Lineage is append-only and answers "what evidence created/changed this finding?". Skipped when
PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.repositories.lineage_repo import (
    EDGE_CONTRADICTED_BY,
    EDGE_CREATED_BY,
    EDGE_SUPPORTED_BY,
    LineageRepository,
)


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


def test_lineage_records_and_reads_back_by_finding_and_canonical(db):
    repo = LineageRepository(db)
    finding_id = str(uuid.uuid4())
    canonical = f"F-{uuid.uuid4().hex[:8]}"

    repo.record(
        finding_id, EDGE_CREATED_BY, canonical_id=canonical, revision=1,
        evidence_ref={"asset_id": "a-1", "asset_version": 1, "source": "document"},
    )
    repo.record(
        finding_id, EDGE_SUPPORTED_BY, canonical_id=canonical, revision=1,
        evidence_ref={"asset_id": "a-2", "asset_version": 1, "source": "repo"},
        detail={"confidence_delta": 0.1},
    )

    edges = repo.list_for_finding(finding_id)
    assert [e["edge_type"] for e in edges] == [EDGE_CREATED_BY, EDGE_SUPPORTED_BY]
    assert repo.count_for_finding(finding_id) == 2
    # Grouped by the stable canonical id across revisions.
    assert len(repo.list_for_canonical(canonical)) == 2
    assert edges[1]["detail"]["confidence_delta"] == 0.1


def test_lineage_edge_type_is_validated(db):
    repo = LineageRepository(db)
    with pytest.raises(ValueError):
        repo.record(str(uuid.uuid4()), "invented_edge")


def test_lineage_query_by_edge_type(db):
    repo = LineageRepository(db)
    fid = str(uuid.uuid4())
    repo.record(fid, EDGE_CONTRADICTED_BY, evidence_ref={"source": "chat"})
    recent = repo.list_by_edge_type(EDGE_CONTRADICTED_BY, limit=500)
    assert fid in {str(e["finding_id"]) for e in recent}
