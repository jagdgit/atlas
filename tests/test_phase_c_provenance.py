"""Phase-C · C.1 live-DB tests — finding provenance (P12: knowledge is global).

Verifies the new ``knowledge.findings.mission_id`` / ``job_id`` columns (migration 0027) against a
real PostgreSQL: they are populated from either explicit kwargs or the ``provenance`` JSON, are
queryable via ``list_by_mission`` / ``list_by_job`` (a read-only *discovery* lens), carry across
revisions, and are **soft refs** — a finding stamped with a mission id that exists in no mission
table still persists (provenance, never ownership; archiving a mission never deletes its knowledge).

Requires a live DB; skipped when PostgreSQL is unreachable (matches the other e2e modules).
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.engineering.findings import EngineeringFindingWriter
from atlas.knowledge.domains import DOMAIN_CODE
from atlas.repositories.finding_repo import FindingRepository


@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def _identity(tag: str) -> list[str]:
    """A unique identity_key so these rows never collide with other tests' findings."""
    return ["code", tag, "path", "symbol", "structure", "code"]


def test_provenance_columns_persist_and_scope(db):
    repo = FindingRepository(db)
    mission_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    tag = uuid.uuid4().hex

    # 1. Columns populated from the provenance JSON (the ingest path stamps only the JSON).
    via_prov = repo.create(
        "repo X is a python project",
        claim_type="structure",
        domain=DOMAIN_CODE,
        provenance={"repo_uid": tag, "mission_id": mission_id, "job_id": job_id},
        identity_key=_identity(f"{tag}-a"),
    )
    assert str(via_prov["mission_id"]) == mission_id
    assert str(via_prov["job_id"]) == job_id

    # 2. Columns populated from explicit kwargs (even with empty provenance).
    via_kwargs = repo.create(
        "repo X declares 2 pip dependencies",
        claim_type="dependency",
        domain=DOMAIN_CODE,
        provenance={"repo_uid": tag},
        identity_key=_identity(f"{tag}-b"),
        mission_id=mission_id,
        job_id=job_id,
    )
    assert str(via_kwargs["mission_id"]) == mission_id

    # 3. Round-trips through get().
    fetched = repo.get(str(via_prov["id"]))
    assert fetched is not None and str(fetched["mission_id"]) == mission_id

    # 4. Discovery lens: list_by_mission / list_by_job return exactly these findings.
    by_mission = {str(r["id"]) for r in repo.list_by_mission(mission_id)}
    assert {str(via_prov["id"]), str(via_kwargs["id"])} <= by_mission
    by_job = {str(r["id"]) for r in repo.list_by_job(job_id)}
    assert {str(via_prov["id"]), str(via_kwargs["id"])} <= by_job


def test_mission_id_is_soft_ref_not_ownership(db):
    """P12: a mission id that exists in no mission table still persists (no FK / cascade)."""
    repo = FindingRepository(db)
    orphan_mission = str(uuid.uuid4())  # never inserted into any mission table
    tag = uuid.uuid4().hex
    row = repo.create(
        "orphan-mission finding",
        claim_type="structure",
        domain=DOMAIN_CODE,
        provenance={"repo_uid": tag, "mission_id": orphan_mission},
        identity_key=_identity(f"{tag}-orphan"),
    )
    # The write succeeds and is retrievable: knowledge outlives / is independent of the mission.
    assert str(row["mission_id"]) == orphan_mission
    assert repo.get(str(row["id"])) is not None


def test_provenance_carries_across_supersede(db):
    """A content change supersedes via a new canonical row (the code path); the discovering
    mission carries onto the replacement finding."""
    repo = FindingRepository(db)
    writer = EngineeringFindingWriter(repo)
    mission_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    repo_uid = str(uuid.uuid4())

    def _finding(statement: str) -> dict:
        return {
            "statement": statement,
            "claim_type": "structure",
            "domain": DOMAIN_CODE,
            "confidence": "HIGH",
            "confidence_score": 0.9,
            "value": {"kind": "repo_structure"},
            "provenance": {
                "repo_uid": repo_uid, "path": "", "symbol": "", "reader": "code",
                "mission_id": mission_id, "job_id": job_id, "source": "repo",
            },
        }

    writer.write([_finding("repo Z is a python project (10 symbols)")])
    active1 = repo.list_active_by_repo_uid(repo_uid)
    assert len(active1) == 1 and str(active1[0]["mission_id"]) == mission_id

    # Changed statement → new canonical row (old superseded), still stamped with the mission.
    writer.write([_finding("repo Z is a python project (99 symbols)")])
    active2 = repo.list_active_by_repo_uid(repo_uid)
    assert len(active2) == 1
    assert str(active2[0]["id"]) != str(active1[0]["id"])
    assert str(active2[0]["mission_id"]) == mission_id
    assert str(active2[0]["job_id"]) == job_id
