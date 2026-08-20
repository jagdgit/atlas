"""ARMF Phase B — Ops cleanup toolkit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from atlas.ops.cleanup import (
    OpsCleanupService,
    is_protected_worker,
    select_cleanup_candidates,
    select_duplicate_workers,
)


def _w(**kwargs):
    now = datetime.now(timezone.utc)
    base = {
        "id": "w1",
        "mission_id": "m1",
        "type": "hello_watcher",
        "status": "running",
        "metadata": {},
        "last_tick_at": now - timedelta(days=8),
        "created_at": now - timedelta(days=9),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_hello_watcher_is_candidate():
    out = select_cleanup_candidates([_w()])
    assert out["counts"]["candidates"] == 1
    assert out["candidates"][0]["reason"].startswith("zombie_type:")


def test_protected_market_long_noprogress_skipped_without_checkbox():
    now = datetime.now(timezone.utc)
    w = _w(
        id="w2",
        type="investment_universe",
        mission_id="m2",
        last_tick_at=now - timedelta(days=2),
        metadata={"program_id": "market_intelligence"},
    )
    out = select_cleanup_candidates([w], include_protected=False)
    assert out["counts"]["candidates"] == 0
    assert out["counts"]["protected_skipped"] >= 1


def test_protected_included_with_checkbox():
    now = datetime.now(timezone.utc)
    w = _w(
        id="w2",
        type="investment_universe",
        mission_id="m2",
        last_tick_at=now - timedelta(days=2),
        metadata={"program_id": "market_intelligence"},
    )
    out = select_cleanup_candidates([w], include_protected=True)
    assert out["counts"]["candidates"] == 1
    assert out["candidates"][0]["protected"] is True


def test_archive_worker_is_protected():
    row = {
        "type": "owner_knowledge",
        "owner": {},
        "service_class": "archive",
    }
    assert is_protected_worker(row) is True


def test_career_observer_type_is_protected():
    assert is_protected_worker({"type": "career_observer", "owner": {}}) is True
    assert is_protected_worker({"type": "career_research", "owner": {}}) is True
    assert is_protected_worker({"type": "job_watcher", "owner": {}}) is True


def test_fresh_worker_not_candidate():
    now = datetime.now(timezone.utc)
    w = _w(
        type="personal_observer",
        last_tick_at=now - timedelta(minutes=5),
        metadata={},
    )
    out = select_cleanup_candidates([w])
    assert out["counts"]["candidates"] == 0


def test_dry_run_does_not_archive():
    now = datetime.now(timezone.utc)
    archived = []

    class FakeWorkers:
        def list_workers(self, limit=500):
            return [_w(last_tick_at=now - timedelta(days=8))]

        def stop_worker(self, wid, reason=""):
            raise AssertionError("should not stop on dry-run")

    class FakeMissions:
        def archive(self, mid, reason=""):
            archived.append(mid)
            return SimpleNamespace(id=mid, status="archived")

        def get(self, mid):
            return SimpleNamespace(id=mid, title="Hello zombie")

    svc = OpsCleanupService(workers=FakeWorkers(), missions=FakeMissions())
    out = svc.run(dry_run=True)
    assert out["dry_run"] is True
    assert out["counts"]["candidates"] == 1
    assert archived == []
    assert out["candidates"][0].get("mission_title") == "Hello zombie"


def test_apply_already_archived_is_idempotent():
    now = datetime.now(timezone.utc)
    stopped = []

    class FakeWorkers:
        def list_workers(self, limit=500):
            return [_w(id="z1", mission_id="m-old", last_tick_at=now - timedelta(days=8))]

        def stop_worker(self, wid, reason=""):
            stopped.append((wid, reason))

    class FakeMissions:
        def archive(self, mid, reason=""):
            raise RuntimeError("illegal transition archived → archived")

        def get(self, mid):
            return SimpleNamespace(id=mid, title="Old zombie", status="archived")

    svc = OpsCleanupService(workers=FakeWorkers(), missions=FakeMissions())
    out = svc.run(dry_run=False, reason="retry cleanup")
    assert out["ok"] is True
    assert out["counts"]["errors"] == 0
    assert any(a["action"] == "already_archived" for a in out["applied"])
    assert stopped and stopped[0][0] == "z1"


def test_select_duplicate_decision_meta_keeps_oldest():
    now = datetime.now(timezone.utc)
    a = _w(
        id="old",
        mission_id="m-old",
        type="decision_meta_learning",
        created_at=now - timedelta(days=10),
        last_tick_at=now - timedelta(hours=1),
        metadata={"program_id": "market_intelligence"},
    )
    b = _w(
        id="new",
        mission_id="m-new",
        type="decision_meta_learning",
        created_at=now - timedelta(days=1),
        last_tick_at=now - timedelta(hours=1),
        metadata={"program_id": "market_intelligence"},
    )
    out = select_duplicate_workers([a, b], keep="oldest", include_protected=True)
    assert out["counts"]["candidates"] == 1
    assert out["candidates"][0]["worker_id"] == "new"
    assert out["kept"][0]["worker_id"] == "old"


def test_cleanup_include_duplicates_merges_candidates():
    now = datetime.now(timezone.utc)

    class FakeWorkers:
        def list_workers(self, limit=500):
            return [
                _w(
                    id="d1",
                    mission_id="md1",
                    type="decision_meta_learning",
                    created_at=now - timedelta(days=5),
                    last_tick_at=now - timedelta(minutes=30),
                ),
                _w(
                    id="d2",
                    mission_id="md2",
                    type="decision_meta_learning",
                    created_at=now - timedelta(days=1),
                    last_tick_at=now - timedelta(minutes=30),
                ),
            ]

    class FakeMissions:
        def get(self, mid):
            return SimpleNamespace(id=mid, title=mid, status="active")

        def archive(self, mid, reason=""):
            raise AssertionError("dry-run")

    svc = OpsCleanupService(workers=FakeWorkers(), missions=FakeMissions())
    out = svc.run(dry_run=True, include_duplicates=True, zombie_types=[])
    assert out["counts"].get("duplicate_candidates", 0) >= 1
    assert any(c.get("reason", "").startswith("duplicate_type:") for c in out["candidates"])
