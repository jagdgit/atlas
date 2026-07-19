"""Live-DB tests for the Personal Intelligence store (C.7a)."""

from __future__ import annotations

import uuid

import pytest

from atlas.repositories.personal_repo import PersonalRepository


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


def _key() -> str:
    return f"skill-{uuid.uuid4().hex[:10]}"


def test_upsert_is_idempotent_on_natural_key(db):
    repo = PersonalRepository(db)
    key = _key()

    first = repo.upsert(
        "skill", key, subject="python", statement="Skilled in X",
        value={"skill": key, "context": "python"}, confidence="LOW",
        confidence_score=0.4, source="experience",
    )
    assert first["state"] == "inferred"
    assert first["category"] == "skill"

    # Same (category, key, subject) → update in place, not a new row.
    second = repo.upsert(
        "skill", key, subject="python", statement="Skilled in X (updated)",
        value={"skill": key, "context": "python"}, confidence="MEDIUM",
        confidence_score=0.6, source="experience",
    )
    assert str(second["id"]) == str(first["id"])
    assert second["confidence"] == "MEDIUM"
    assert second["statement"] == "Skilled in X (updated)"


def test_reinference_never_downgrades_verified(db):
    repo = PersonalRepository(db)
    key = _key()
    fact = repo.upsert("skill", key, subject="python", statement="Original",
                       value={"n": 1}, confidence_score=0.4)
    verified = repo.set_state(fact["id"], "verified")
    assert verified["state"] == "verified"

    # A later inference pass must NOT flip verified back to inferred, and must keep the
    # operator-facing statement/value while still refreshing confidence telemetry.
    again = repo.upsert("skill", key, subject="python", statement="Machine reworded",
                        value={"n": 2}, confidence="HIGH", confidence_score=0.9)
    assert again["state"] == "verified"
    assert again["statement"] == "Original"
    assert again["value"] == {"n": 1}
    assert again["confidence"] == "HIGH"  # telemetry still refreshed


def test_list_filters_by_category_and_state(db):
    repo = PersonalRepository(db)
    k1, k2 = _key(), _key()
    repo.upsert("skill", k1, subject="python", confidence_score=0.5)
    f2 = repo.upsert("professional", k2, statement="Wrote a paper", confidence_score=0.5)
    repo.set_state(f2["id"], "verified")

    skills = repo.list(category="skill", limit=1000)
    assert any(f["key"] == k1 for f in skills)
    assert all(f["category"] == "skill" for f in skills)

    verified = repo.list(state="verified", limit=1000)
    assert any(f["key"] == k2 for f in verified)
    assert all(f["state"] == "verified" for f in verified)


def test_delete_and_restore_roundtrip(db):
    repo = PersonalRepository(db)
    key = _key()
    fact = repo.upsert("identity", key, statement="An engineer", confidence_score=0.7)
    fid = fact["id"]
    assert repo.delete(fid) is True
    assert repo.get(fid) is None

    restored = repo.restore(fact)
    assert str(restored["id"]) == str(fid)
    assert restored["statement"] == "An engineer"


def test_event_journal_records_before_after(db):
    repo = PersonalRepository(db)
    key = _key()
    fact = repo.upsert("skill", key, subject="python", confidence_score=0.4)
    ev = repo.record_event(fact["id"], "confirmed", before=fact, after={**fact, "state": "verified"}, actor="op")
    assert ev["action"] == "confirmed"
    got = repo.get_event(ev["id"])
    assert got["before"]["state"] == "inferred"
    assert got["after"]["state"] == "verified"
    assert any(str(e["id"]) == str(ev["id"]) for e in repo.list_events(fact_id=fact["id"]))

    with pytest.raises(ValueError):
        repo.record_event(fact["id"], "bogus")
