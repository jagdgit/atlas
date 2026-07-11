"""Integration tests for the repositories layer.

These require a live PostgreSQL. If the database is unreachable, the whole
module is skipped so the suite stays green in environments without DB access.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.repositories import (
    EventRepository,
    SettingsRepository,
    TaskRepository,
)


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


def test_settings_roundtrip(db):
    repo = SettingsRepository(db)
    key = f"test.key.{uuid.uuid4()}"
    repo.set(key, {"enabled": True, "count": 3}, description="test setting")
    assert repo.get(key) == {"enabled": True, "count": 3}
    assert key in repo.all()
    assert repo.delete(key) is True
    assert repo.get(key) is None


def test_task_lifecycle(db):
    repo = TaskRepository(db)
    task = repo.create("embed_document", {"document_id": "abc"}, priority=5)
    task_id = task["id"]
    assert task["status"] == "pending"
    assert task["task_type"] == "embed_document"

    assert repo.set_status(task_id, "claimed") is True
    assert repo.get(task_id)["status"] == "claimed"

    assert repo.increment_retry(task_id) == 1
    assert repo.set_status(task_id, "failed", error="boom") is True

    reloaded = repo.get(task_id)
    assert reloaded["status"] == "failed"
    assert reloaded["last_error"] == "boom"
    assert reloaded["completed_at"] is not None

    assert repo.delete(task_id) is True


def test_task_invalid_status(db):
    repo = TaskRepository(db)
    with pytest.raises(ValueError):
        repo.list_by_status("bogus")


def test_event_lifecycle(db):
    repo = EventRepository(db)
    event = repo.record("DocumentImported", {"path": "/tmp/x"}, source="test")
    event_id = event["id"]
    assert event["status"] == "pending"

    pending_ids = {e["id"] for e in repo.list_pending()}
    assert event_id in pending_ids

    assert repo.mark(event_id, "processed") is True
    assert repo.get(event_id)["status"] == "processed"
    assert repo.get(event_id)["processed_at"] is not None

    repo.execute("DELETE FROM audit.events WHERE id = %s", (str(event_id),))
