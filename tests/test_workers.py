"""Worker Manager + Persistent Worker tests (Phase A · §A.4).

Hermetic: fake worker repo, an in-memory checkpoint store, and fake schedule/config/mission
repos stand in for the DB so we cover the tick loop (checkpoint resume, input draining, config
pickup), the version-upgrade path (B8), the crash-backoff → pause policy (B4), lifecycle
(pause/resume/stop + schedule toggling), and mission-archive worker-stop — all without a
database. Reboot-resume durability is covered by the live-DB smoke.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from atlas.models.worker import (
    HEALTH_BLOCKED,
    HEALTH_RECOVERING,
    WORKER_PAUSED,
    WORKER_RECOVERING,
    WORKER_RUNNING,
    WORKER_STOPPED,
    Worker,
    WorkerInput,
    backoff_for,
)
from atlas.core.resources.arbiter import MissionDemand
from atlas.workers.base import PersistentWorker, TickContext, TickResult
from atlas.workers.hello import HelloWatcher
from atlas.workers.manager import WorkerError, WorkerManager


# --- fakes ---------------------------------------------------------------


class FakeCheckpoints:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str, str], dict[str, Any]] = {}

    def save(self, owner_type, owner_id, state, *, label="default"):
        self.store[(owner_type, owner_id, label)] = dict(state)
        return {}

    def load(self, owner_type, owner_id, *, label="default"):
        got = self.store.get((owner_type, owner_id, label))
        return dict(got) if got is not None else None

    def clear(self, owner_type, owner_id, *, label=None):
        return 0


class FakeWorkerRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.inputs: list[dict[str, Any]] = []

    def create(self, *, mission_id, type, worker_version, schedule_id=None,
               config_version=None, status="running", health="healthy", metadata=None):
        wid = str(uuid4())
        row = {
            "id": wid, "mission_id": mission_id, "type": type,
            "worker_version": worker_version, "status": status, "health": health,
            "schedule_id": schedule_id, "config_version": config_version,
            "restart_count": 0, "next_retry_at": None, "last_tick_at": None,
            "metadata": metadata or {}, "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.rows[wid] = row
        return Worker.from_row(row)

    def get(self, wid):
        row = self.rows.get(str(wid))
        return Worker.from_row(row) if row else None

    def list(self, *, mission_id=None, status=None, limit=200):
        out = []
        for row in self.rows.values():
            if mission_id is not None and row["mission_id"] != mission_id:
                continue
            if status is not None and row["status"] != status:
                continue
            out.append(Worker.from_row(row))
        return out[:limit]

    def set_schedule(self, wid, schedule_id):
        self.rows[str(wid)]["schedule_id"] = schedule_id
        return True

    def set_status(self, wid, status, *, health=None):
        row = self.rows[str(wid)]
        row["status"] = status
        if health is not None:
            row["health"] = health
        return True

    def record_success(self, wid, *, config_version=None):
        row = self.rows[str(wid)]
        row.update(status=WORKER_RUNNING, health="healthy", restart_count=0, next_retry_at=None)
        if config_version is not None:
            row["config_version"] = config_version
        return True

    def record_failure(self, wid, *, status, health, backoff_seconds):
        row = self.rows[str(wid)]
        row["restart_count"] += 1
        row["status"] = status
        row["health"] = health
        row["next_retry_at"] = (
            None if backoff_seconds is None
            else datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        )
        return row["restart_count"]

    def set_version(self, wid, worker_version):
        self.rows[str(wid)]["worker_version"] = worker_version
        return True

    def count_by_status(self):
        out: dict[str, int] = {}
        for row in self.rows.values():
            out[row["status"]] = out.get(row["status"], 0) + 1
        return out

    def stop_active_for_mission(self, mission_id):
        n = 0
        for row in self.rows.values():
            if row["mission_id"] == str(mission_id) and row["status"] in ("running", "recovering"):
                row["status"] = WORKER_STOPPED
                n += 1
        return n

    def enqueue_input(self, worker_id, payload):
        row = {"id": str(uuid4()), "worker_id": str(worker_id), "payload": payload,
               "status": "pending", "created_at": datetime.now(timezone.utc), "consumed_at": None}
        self.inputs.append(row)
        return WorkerInput.from_row(row)

    def drain_inputs(self, worker_id):
        pending = [r for r in self.inputs if r["worker_id"] == str(worker_id) and r["status"] == "pending"]
        pending.sort(key=lambda r: r["created_at"])
        for r in pending:
            r["status"] = "consumed"
        return WorkerInput.from_rows(pending)


class FakeSchedules:
    def __init__(self) -> None:
        self.enabled: dict[str, bool] = {}

    def register_schedule(self, task_type, interval_seconds, *, payload=None,
                          mission_id=None, worker_id=None, first_run_delay=0.0):
        sid = str(uuid4())
        self.enabled[sid] = True
        return type("S", (), {"id": sid})()

    def enable(self, sid):
        self.enabled[sid] = True
        return True

    def disable(self, sid):
        self.enabled[sid] = False
        return True


class FakeConfigRepo:
    def __init__(self, version=None, document=None) -> None:
        self._v = version
        self._doc = document or {}

    def set(self, version, document):
        self._v, self._doc = version, document

    def get_active(self, mission_id):
        if self._v is None:
            return None
        return type("C", (), {"version": self._v, "document": dict(self._doc)})()


class FakeMissionRepo:
    def __init__(self, budgets: dict[str, int] | None = None) -> None:
        self.journal: list[dict[str, Any]] = []
        self.budgets = budgets or {}

    def add_journal(self, mission_id, action, reason="", refs=None):
        self.journal.append({"mission_id": mission_id, "action": action, "reason": reason, "refs": refs or {}})

    def get(self, mission_id):
        """Return a Mission carrying the configured budget (or None = unlimited)."""
        from atlas.models.mission import Mission

        cap = self.budgets.get(str(mission_id))
        if cap is None:
            return None
        return Mission(id=str(mission_id), title="m", budget={"max_concurrent_tasks": cap})


# a worker whose behaviour we can steer for failure/upgrade tests
class FlakyWorker(PersistentWorker):
    type = "flaky"
    VERSION = 1

    def __init__(self, fail=False) -> None:
        self.fail = fail

    def do_tick(self, ctx: TickContext) -> TickResult:
        if self.fail:
            raise RuntimeError("boom")
        n = int(ctx.state.get("n", 0)) + 1
        return TickResult(state={"n": n}, note=f"n={n}")


@pytest.fixture()
def mgr():
    repo = FakeWorkerRepo()
    cps = FakeCheckpoints()
    scheds = FakeSchedules()
    cfg = FakeConfigRepo(version=1, document={"greeting": "hi", "tick_limit": 0})
    missions = FakeMissionRepo()
    m = WorkerManager(
        repo, cps, schedule_service=scheds, config_repo=cfg,
        mission_repo=missions, clock=None,
    )
    m.register_worker_type(HelloWatcher())
    return m, repo, cps, scheds, cfg, missions


# --- creation + registry -------------------------------------------------


def test_create_worker_registers_schedule_and_journals(mgr):
    m, repo, _, scheds, _, missions = mgr
    w = m.create_worker("mission-1", "hello_watcher", interval_seconds=30)
    assert w.type == "hello_watcher"
    assert w.schedule_id is not None
    assert scheds.enabled[w.schedule_id] is True
    assert any(e["action"] == "worker_created" for e in missions.journal)


def test_create_unknown_type_raises(mgr):
    m, *_ = mgr
    with pytest.raises(WorkerError):
        m.create_worker("mission-1", "nope")


# --- the tick ------------------------------------------------------------


def test_tick_increments_checkpoint_across_ticks(mgr):
    m, repo, cps, _, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    m.worker_tick({"worker_id": w.id})
    m.worker_tick({"worker_id": w.id})
    state = cps.load("worker", w.id)
    assert state["count"] == 2  # resumed from checkpoint, not restarted


def test_tick_resumes_from_existing_checkpoint(mgr):
    m, repo, cps, _, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    cps.save("worker", w.id, {"count": 41})  # simulate pre-reboot progress
    m.worker_tick({"worker_id": w.id})
    assert cps.load("worker", w.id)["count"] == 42


def test_tick_consumes_operator_input(mgr):
    m, repo, cps, _, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    m.enqueue_input(w.id, {"greeting": "namaste"})
    m.worker_tick({"worker_id": w.id})
    assert cps.load("worker", w.id)["greeting"] == "namaste"


def test_tick_done_stops_worker(mgr):
    m, repo, cps, scheds, cfg, _ = mgr
    cfg.set(2, {"greeting": "hi", "tick_limit": 1})  # limit reached after one tick
    w = m.create_worker("mission-1", "hello_watcher")
    out = m.worker_tick({"worker_id": w.id})
    assert out["done"] is True
    assert repo.get(w.id).status == WORKER_STOPPED
    assert scheds.enabled[w.schedule_id] is False


def test_tick_skips_paused_worker(mgr):
    m, repo, cps, _, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    m.pause(w.id)
    out = m.worker_tick({"worker_id": w.id})
    assert out == {"skipped": WORKER_PAUSED}
    assert cps.load("worker", w.id) is None  # never ticked


def test_tick_picks_up_new_config_version(mgr):
    m, repo, cps, _, cfg, missions = mgr
    w = m.create_worker("mission-1", "hello_watcher")  # created at config v1
    cfg.set(3, {"greeting": "hola", "tick_limit": 0})
    m.worker_tick({"worker_id": w.id})
    assert repo.get(w.id).config_version == 3
    assert any(e["action"] == "config_picked_up" for e in missions.journal)


# --- version upgrade (B8) ------------------------------------------------


def test_version_upgrade_journaled_on_tick(mgr):
    m, repo, cps, _, _, missions = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    # simulate the running code being upgraded to v2 while the row is still v1
    upgraded = HelloWatcher()
    upgraded.VERSION = 2
    m.register_worker_type(upgraded)
    m.worker_tick({"worker_id": w.id})
    assert repo.get(w.id).worker_version == 2
    assert any(e["action"] == "worker_upgraded" for e in missions.journal)


# --- crash policy (B4) ---------------------------------------------------


def test_crash_backoff_then_pause(mgr):
    m, repo, cps, scheds, _, missions = mgr
    m.register_worker_type(FlakyWorker(fail=True))
    w = m.create_worker("mission-1", "flaky")
    sid = w.schedule_id
    # Failures 1..4 → recovering with backoff; clear next_retry_at each time to allow re-tick.
    for expected in range(1, 5):
        out = m.worker_tick({"worker_id": w.id})
        row = repo.get(w.id)
        assert out["failed"] is True
        assert row.status == WORKER_RECOVERING
        assert row.health == HEALTH_RECOVERING
        assert row.restart_count == expected
        repo.rows[w.id]["next_retry_at"] = None  # skip the wait for the test
    # 5th failure → paused (crash loop), schedule disabled
    m.worker_tick({"worker_id": w.id})
    row = repo.get(w.id)
    assert row.status == WORKER_PAUSED
    assert row.health == HEALTH_BLOCKED
    assert scheds.enabled[sid] is False
    assert any(e["action"] == "worker_paused" for e in missions.journal)


def test_recovering_worker_skips_during_backoff(mgr):
    m, repo, cps, _, _, _ = mgr
    m.register_worker_type(FlakyWorker(fail=True))
    w = m.create_worker("mission-1", "flaky")
    m.worker_tick({"worker_id": w.id})  # fail → recovering, next_retry_at in the future
    out = m.worker_tick({"worker_id": w.id})
    assert out["skipped"] == "backoff"


def test_backoff_schedule_values():
    assert backoff_for(1) == 10
    assert backoff_for(2) == 30
    assert backoff_for(3) == 60
    assert backoff_for(4) == 300


# --- lifecycle -----------------------------------------------------------


def test_pause_resume_toggles_schedule(mgr):
    m, repo, _, scheds, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    m.pause(w.id)
    assert scheds.enabled[w.schedule_id] is False
    assert repo.get(w.id).status == WORKER_PAUSED
    m.resume(w.id)
    assert scheds.enabled[w.schedule_id] is True
    assert repo.get(w.id).status == WORKER_RUNNING


def test_stop_worker(mgr):
    m, repo, _, scheds, _, _ = mgr
    w = m.create_worker("mission-1", "hello_watcher")
    m.stop_worker(w.id, "operator done")
    assert repo.get(w.id).status == WORKER_STOPPED
    assert scheds.enabled[w.schedule_id] is False


def test_health_check_counts(mgr):
    m, repo, *_ = mgr
    m.create_worker("mission-1", "hello_watcher")
    status = m.health_check()
    assert status.healthy
    assert status.data["counts"].get("running") == 1


def test_unknown_worker_tick_is_noop(mgr):
    m, *_ = mgr
    assert m.worker_tick({"worker_id": str(uuid4())}) == {"skipped": "unknown worker"}
    assert m.worker_tick({}) == {"skipped": "no worker_id"}


# --- budget admission (B1/A.6) ------------------------------------------


def test_tick_throttled_when_mission_at_budget_cap():
    repo = FakeWorkerRepo()
    cps = FakeCheckpoints()
    missions = FakeMissionRepo(budgets={"mission-1": 1})  # cap of 1 concurrent tick
    m = WorkerManager(repo, cps, config_repo=FakeConfigRepo(), mission_repo=missions)
    m.register_worker_type(HelloWatcher())
    w = m.create_worker("mission-1", "hello_watcher", autostart=False)
    # simulate one tick already in flight for this mission (mission is at its cap of 1)
    m._arbiter.try_admit(MissionDemand(mission_id="mission-1", max_concurrent_tasks=1))
    out = m.worker_tick({"worker_id": w.id})
    assert out == {"skipped": "budget", "worker_id": w.id}
    assert cps.load("worker", w.id) is None  # never ran


def test_tick_proceeds_within_budget_and_releases_slot():
    repo = FakeWorkerRepo()
    cps = FakeCheckpoints()
    missions = FakeMissionRepo(budgets={"mission-1": 2})
    m = WorkerManager(repo, cps, config_repo=FakeConfigRepo(), mission_repo=missions)
    m.register_worker_type(HelloWatcher())
    w = m.create_worker("mission-1", "hello_watcher", autostart=False)
    out = m.worker_tick({"worker_id": w.id})
    assert out["ticked"] is True
    assert m._arbiter.inflight_for("mission-1") == 0  # slot released after the tick
