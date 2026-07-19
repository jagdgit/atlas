"""Schedule service tests (Phase A · §A.3).

Hermetic: fake schedule + task repositories stand in for ``scheduler.schedules`` /
``scheduler.tasks`` so we cover the tick (enqueue due schedules + advance + re-enqueue self),
per-schedule error isolation, self-healing re-enqueue when claiming fails, enable/disable,
mission-scoped disable, seeding, and health — all without a database. Cadence/`kill -9`
durability of `next_run_at` is covered by the live-DB smoke.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from atlas.models.schedule import Schedule
from atlas.scheduler.schedules import TICK_TASK_TYPE, ScheduleService


# --- fakes ---------------------------------------------------------------


class FakeScheduleRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.raise_on_claim = False

    def create(
        self, *, task_type, interval_seconds, payload=None, mission_id=None,
        worker_id=None, enabled=True, first_run_delay=0.0,
    ) -> Schedule:
        sid = str(uuid4())
        row = {
            "id": sid,
            "task_type": task_type,
            "interval_seconds": interval_seconds,
            "payload": payload or {},
            "next_run_at": datetime.now(timezone.utc),
            "last_run_at": None,
            "enabled": enabled,
            "mission_id": mission_id,
            "worker_id": worker_id,
        }
        self.rows[sid] = row
        return Schedule.from_row(row)

    def get(self, sid) -> Schedule | None:
        row = self.rows.get(str(sid))
        return Schedule.from_row(row) if row else None

    def list(self, *, enabled=None, mission_id=None, limit=200) -> list[Schedule]:
        out = []
        for row in self.rows.values():
            if enabled is not None and row["enabled"] != enabled:
                continue
            if mission_id is not None and row["mission_id"] != mission_id:
                continue
            out.append(Schedule.from_row(row))
        return out[:limit]

    def claim_due(self, *, limit=100) -> list[Schedule]:
        if self.raise_on_claim:
            raise RuntimeError("db down")
        due = [r for r in self.rows.values() if r["enabled"]]
        for r in due:
            r["last_run_at"] = datetime.now(timezone.utc)
        return [Schedule.from_row(r) for r in due[:limit]]

    def set_enabled(self, sid, enabled) -> bool:
        row = self.rows.get(str(sid))
        if not row:
            return False
        row["enabled"] = enabled
        return True

    def set_interval(self, sid, interval_seconds) -> bool:
        row = self.rows.get(str(sid))
        if not row:
            return False
        row["interval_seconds"] = interval_seconds
        return True

    def disable_for_mission(self, mission_id) -> int:
        n = 0
        for r in self.rows.values():
            if r["mission_id"] == str(mission_id) and r["enabled"]:
                r["enabled"] = False
                n += 1
        return n

    def count_enabled(self) -> int:
        return sum(1 for r in self.rows.values() if r["enabled"])

    def delete(self, sid) -> bool:
        return self.rows.pop(str(sid), None) is not None


class FakeTaskRepo:
    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []

    def create(self, task_type, payload=None, *, priority=0, max_retries=3, delay_seconds=0.0):
        row = {
            "id": str(uuid4()),
            "task_type": task_type,
            "payload": payload or {},
            "priority": priority,
            "max_retries": max_retries,
            "delay_seconds": delay_seconds,
            "status": "pending",
        }
        self.tasks.append(row)
        return row

    def count_pending_of_type(self, task_type) -> int:
        return sum(1 for t in self.tasks if t["task_type"] == task_type and t["status"] == "pending")


@pytest.fixture()
def svc():
    srepo = FakeScheduleRepo()
    trepo = FakeTaskRepo()
    return ScheduleService(srepo, trepo, tick_interval=5.0), srepo, trepo


def _ticks(trepo: FakeTaskRepo) -> list[dict[str, Any]]:
    return [t for t in trepo.tasks if t["task_type"] == TICK_TASK_TYPE]


def _non_ticks(trepo: FakeTaskRepo) -> list[dict[str, Any]]:
    return [t for t in trepo.tasks if t["task_type"] != TICK_TASK_TYPE]


# --- registration --------------------------------------------------------


def test_register_schedule(svc):
    service, srepo, _ = svc
    s = service.register_schedule("worker_tick", 60, payload={"k": 1}, mission_id="m1")
    assert s.task_type == "worker_tick"
    assert s.interval_seconds == 60
    assert srepo.get(s.id) is not None


# --- the tick ------------------------------------------------------------


def test_tick_enqueues_due_and_reenqueues_self(svc):
    service, _, trepo = svc
    service.register_schedule("worker_tick", 60, payload={"k": 1}, mission_id="m1")
    out = service.tick()
    assert out["fired"] == 1
    fired_task = _non_ticks(trepo)[0]
    assert fired_task["task_type"] == "worker_tick"
    # payload is enriched with schedule/mission/worker refs
    assert fired_task["payload"]["k"] == 1
    assert fired_task["payload"]["mission_id"] == "m1"
    assert "schedule_id" in fired_task["payload"]
    # the recurrence chain continues: exactly one schedule_tick re-enqueued
    ticks = _ticks(trepo)
    assert len(ticks) == 1
    assert ticks[0]["delay_seconds"] == 5.0


def test_tick_enqueues_at_mission_priority(svc):
    service, srepo, trepo = svc
    # attach a fake mission repo returning a high effective priority
    from atlas.models.mission import Mission

    class FakeMissions:
        def get(self, mission_id):
            # realtime(60) + priority 10 + critical(+40) = 110
            return Mission(id=str(mission_id), title="m", scheduling_policy="realtime",
                           priority=10, criticality="critical")

    service._missions = FakeMissions()
    service.register_schedule("worker_tick", 60, mission_id="m1")
    service.tick()
    fired = _non_ticks(trepo)[0]
    assert fired["priority"] == 110


def test_tick_non_mission_schedule_priority_zero(svc):
    service, srepo, trepo = svc
    service.register_schedule("job", 60)  # no mission
    service.tick()
    assert _non_ticks(trepo)[0]["priority"] == 0


def test_tick_skips_disabled(svc):
    service, srepo, trepo = svc
    s = service.register_schedule("worker_tick", 60)
    service.disable(s.id)
    out = service.tick()
    assert out["fired"] == 0
    assert _non_ticks(trepo) == []


def test_tick_isolates_one_bad_schedule(svc):
    service, srepo, trepo = svc
    service.register_schedule("good", 60)
    service.register_schedule("bad", 60)

    calls = {"n": 0}
    orig = trepo.create

    def flaky(task_type, payload=None, **kw):
        if task_type == "bad":
            raise RuntimeError("boom")
        return orig(task_type, payload, **kw)

    trepo.create = flaky  # type: ignore[method-assign]
    out = service.tick()
    # one good schedule fired despite the bad one raising; self still re-enqueued
    assert out["fired"] == 1
    assert len(_ticks(trepo)) == 1


def test_tick_reenqueues_self_even_when_claim_fails(svc):
    service, srepo, trepo = svc
    srepo.raise_on_claim = True
    with pytest.raises(RuntimeError):
        service.tick()
    # claim failed → scheduler will retry this task, but we still chained a tick so the
    # loop self-heals rather than dying silently
    assert len(_ticks(trepo)) == 1


# --- lifecycle / control -------------------------------------------------


def test_ensure_running_seeds_once(svc):
    service, _, trepo = svc
    service.ensure_running()
    service.ensure_running()  # idempotent while one is pending
    assert len(_ticks(trepo)) == 1


def test_start_seeds_tick(svc):
    service, _, trepo = svc
    service.start()
    assert len(_ticks(trepo)) == 1


def test_disable_for_mission(svc):
    service, _, _ = svc
    service.register_schedule("a", 60, mission_id="m1")
    service.register_schedule("b", 60, mission_id="m1")
    service.register_schedule("c", 60, mission_id="m2")
    assert service.disable_for_mission("m1") == 2
    assert [s.task_type for s in service.list_schedules(enabled=True)] == ["c"]


def test_set_interval_and_delete(svc):
    service, srepo, _ = svc
    s = service.register_schedule("a", 60)
    assert service.set_interval(s.id, 120)
    assert srepo.get(s.id).interval_seconds == 120
    assert service.delete(s.id)
    assert srepo.get(s.id) is None


def test_health_degraded_without_tick(svc):
    service, _, _ = svc
    service.register_schedule("a", 60)
    assert service.health_check().degraded  # no tick seeded yet
    service.start()
    assert service.health_check().healthy
