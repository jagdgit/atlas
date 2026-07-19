"""Live-DB tests for the Policy store repository (Phase C · §C.5, CC8).

Operator rules + an append-only before/after journal. Skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.repositories.policy_repo import PolicyRepository


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


def test_create_get_and_natural_key_upsert(db):
    repo = PolicyRepository(db)
    subject = f"momentum-{uuid.uuid4().hex[:8]}"

    row = repo.create("global", subject, "prefer", strength=0.8, created_by="op")
    assert row["rule"] == "prefer" and row["strength"] == 0.8
    assert row["enabled"] is True

    # Same (scope, subject, rule) upserts in place, not a new row.
    again = repo.create("global", subject, "prefer", strength=0.5)
    assert str(again["id"]) == str(row["id"])
    assert again["strength"] == 0.5
    assert again["created_by"] == "op"  # preserved on upsert

    assert str(repo.get(row["id"])["id"]) == str(row["id"])
    assert str(repo.get_by_natural("global", subject, "prefer")["id"]) == str(row["id"])


def test_invalid_rule_kind_rejected(db):
    repo = PolicyRepository(db)
    with pytest.raises(ValueError):
        repo.create("global", "x", "obliterate")


def test_list_filters_by_enabled_and_rule(db):
    repo = PolicyRepository(db)
    scope = f"probe-{uuid.uuid4().hex[:8]}"
    repo.create(scope, "a", "prefer")
    repo.create(scope, "b", "avoid", enabled=False)

    enabled = repo.list(scope=scope, enabled=True)
    assert {r["subject"] for r in enabled} == {"a"}
    avoids = repo.list(scope=scope, rule="avoid")
    assert {r["subject"] for r in avoids} == {"b"}


def test_update_and_set_enabled(db):
    repo = PolicyRepository(db)
    subject = f"redis-{uuid.uuid4().hex[:8]}"
    row = repo.create("global", subject, "trust", strength=1.0)

    updated = repo.update(row["id"], strength=0.3)
    assert updated["strength"] == 0.3
    disabled = repo.set_enabled(row["id"], False)
    assert disabled["enabled"] is False


def test_delete_and_restore_from_snapshot(db):
    repo = PolicyRepository(db)
    subject = f"crypto-{uuid.uuid4().hex[:8]}"
    row = repo.create("global", subject, "avoid", strength=0.9)

    assert repo.delete(row["id"]) is True
    assert repo.get(row["id"]) is None

    restored = repo.restore(row)  # same id, from journal snapshot
    assert str(restored["id"]) == str(row["id"])
    assert restored["subject"] == subject and restored["strength"] == 0.9


def test_journal_records_before_after(db):
    repo = PolicyRepository(db)
    subject = f"topic-{uuid.uuid4().hex[:8]}"
    row = repo.create("global", subject, "prefer")

    ev = repo.record_event(row["id"], "created", before=None, after=row, actor="op")
    assert ev["action"] == "created"
    assert ev["before"] is None and ev["after"]["subject"] == subject

    fetched = repo.get_event(ev["id"])
    assert str(fetched["id"]) == str(ev["id"])
    events = repo.list_events(rule_id=row["id"])
    assert any(e["action"] == "created" for e in events)


def test_invalid_event_action_rejected(db):
    repo = PolicyRepository(db)
    with pytest.raises(ValueError):
        repo.record_event(None, "exploded")
