"""Tests for the finding maturity axis (Phase C · §C.3, CC13, migration 0032).

Hermetic tests cover the derivation policy; a live-DB test covers persistence + in-place maturity/
evidence updates (no new revision). DB tests skip when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.knowledge.lifecycle import (
    MATURITY_CANDIDATE,
    MATURITY_ESTABLISHED,
    MATURITY_VERIFIED,
    derive_maturity,
    independent_source_count,
)


# --- hermetic ------------------------------------------------------------
def test_derive_maturity_thresholds():
    # A single uncorroborated, low-confidence observation → candidate.
    assert derive_maturity(supporting_count=1, confidence="UNVERIFIED") == MATURITY_CANDIDATE
    assert derive_maturity(supporting_count=0, confidence=None) == MATURITY_CANDIDATE
    # Decent confidence OR 2 sources → verified.
    assert derive_maturity(supporting_count=1, confidence="MEDIUM") == MATURITY_VERIFIED
    assert derive_maturity(supporting_count=2, confidence="UNVERIFIED") == MATURITY_VERIFIED
    # 3+ independent sources AND decent confidence → established.
    assert derive_maturity(supporting_count=3, confidence="HIGH") == MATURITY_ESTABLISHED
    assert derive_maturity(supporting_count=5, confidence="MEDIUM") == MATURITY_ESTABLISHED
    # 3 sources but weak confidence stays verified (not established).
    assert derive_maturity(supporting_count=3, confidence="UNVERIFIED") == MATURITY_VERIFIED


def test_independent_source_count_dedups_by_source_id():
    supporting = [
        {"source_id": "s1"}, {"source_id": "s1"},  # same source twice
        {"source_id": "s2"}, {"source": "s3"},
        "s4",
    ]
    assert independent_source_count(supporting) == 4
    assert independent_source_count([]) == 0
    assert independent_source_count(None) == 0


# --- live DB -------------------------------------------------------------
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


def test_finding_persists_and_merges_maturity_in_place(db):
    from atlas.repositories.finding_repo import FindingRepository

    repo = FindingRepository(db)
    token = uuid.uuid4().hex
    created = repo.create(
        f"Atlas uses content-addressed assets {token}",
        domain="external",
        confidence="UNVERIFIED",
        supporting=[{"source_id": "s1"}],
        maturity=MATURITY_CANDIDATE,
        identity_key=["prose", "external", f"stmt-{token}"],
    )
    try:
        assert created["maturity"] == MATURITY_CANDIDATE
        assert created["revision"] == 1

        # A second independent source strengthens the finding IN PLACE (no new revision).
        merged = repo.update_evidence(
            str(created["id"]),
            supporting=[{"source_id": "s1"}, {"source_id": "s2"}],
            confidence="MEDIUM",
            confidence_score=0.6,
            maturity=derive_maturity(supporting_count=2, confidence="MEDIUM"),
        )
        assert merged["maturity"] == MATURITY_VERIFIED
        assert merged["revision"] == 1  # merge-in-place: same revision
        assert len(merged["supporting"]) == 2

        bumped = repo.set_maturity(str(created["id"]), MATURITY_ESTABLISHED)
        assert bumped["maturity"] == MATURITY_ESTABLISHED
        assert bumped["revision"] == 1
    finally:
        repo.set_status(str(created["id"]), "archived")
