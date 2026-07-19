"""Live-DB tests for the extraction coverage map (Phase C · §C.4, A10/CC15).

Coverage rows record *what was read and how it went*, keyed on the Derived-Artifact 4-tuple
(asset_id, asset_version, reader, reader_version). Skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.repositories.coverage_repo import CoverageRepository


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


def test_record_is_idempotent_upsert(db):
    repo = CoverageRepository(db)
    asset = str(uuid.uuid4())

    first = repo.record(
        asset, 1, "document", "1.0.0",
        status="done", domain="external", source="document", findings_count=3, chunks_count=7,
    )
    assert first["status"] == "done"
    assert first["findings_count"] == 3
    assert first["extracted_at"] is not None

    # Same key → update in place, not a second row.
    second = repo.record(
        asset, 1, "document", "1.0.0",
        status="done", domain="external", source="document", findings_count=5, chunks_count=9,
    )
    assert str(second["id"]) == str(first["id"])
    assert second["findings_count"] == 5

    got = repo.get(asset, 1, "document", "1.0.0")
    assert got is not None and got["chunks_count"] == 9


def test_failed_status_has_no_extracted_at(db):
    repo = CoverageRepository(db)
    asset = str(uuid.uuid4())
    row = repo.record(
        asset, 1, "document", "1.0.0",
        status="unsupported", domain="external", reason="binary blob",
    )
    assert row["status"] == "unsupported"
    assert row["extracted_at"] is None
    assert row["reason"] == "binary blob"


def test_new_reader_version_mints_a_new_row(db):
    repo = CoverageRepository(db)
    asset = str(uuid.uuid4())
    old = repo.record(asset, 1, "code", "1.0.0", status="done", domain="code",
                      extractor_version="1.0.0", findings_count=2)
    new = repo.record(asset, 1, "code", "1.1.0", status="done", domain="code",
                      extractor_version="1.0.0", findings_count=4)
    assert str(old["id"]) != str(new["id"])  # old read preserved for the reader-improved delta


def test_stale_enumerates_only_older_versions(db):
    repo = CoverageRepository(db)
    reader = f"code-{uuid.uuid4().hex[:8]}"  # isolate this reader from other test rows
    a_old, a_new = str(uuid.uuid4()), str(uuid.uuid4())

    repo.record(a_old, 1, reader, "1.0.0", status="done", domain="code", extractor_version="1.0.0")
    repo.record(a_new, 1, reader, "1.1.0", status="done", domain="code", extractor_version="1.0.0")

    stale = repo.stale(reader, reader_version="1.1.0")
    stale_assets = {str(r["asset_id"]) for r in stale}
    assert a_old in stale_assets
    assert a_new not in stale_assets

    # Bumping only the extractor also flags the older extractor rows.
    stale_by_extractor = repo.stale(reader, extractor_version="2.0.0")
    assert {a_old, a_new} <= {str(r["asset_id"]) for r in stale_by_extractor}


def test_summary_rolls_up_by_domain(db):
    repo = CoverageRepository(db)
    domain = f"probe-{uuid.uuid4().hex[:8]}"
    repo.record(str(uuid.uuid4()), 1, "document", "1.0.0", status="done", domain=domain)
    repo.record(str(uuid.uuid4()), 1, "document", "1.0.0", status="done", domain=domain)
    repo.record(str(uuid.uuid4()), 1, "document", "1.0.0", status="failed", domain=domain)

    rows = {r["group_key"]: r for r in repo.summary(by="domain")}
    assert domain in rows
    grp = rows[domain]
    assert grp["total"] == 3
    assert grp["done"] == 2
    assert grp["failed"] == 1


def test_mark_pending_flags_for_reextraction(db):
    repo = CoverageRepository(db)
    asset = str(uuid.uuid4())
    row = repo.record(asset, 1, "document", "1.0.0", status="done", domain="external")
    flagged = repo.mark_pending(row["id"])
    assert flagged["status"] == "pending"
