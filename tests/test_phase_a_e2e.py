"""Phase-A end-to-end acceptance — the Phase-A gate (PHASE_A_PLAN §A.8).

Exercises the **full Hello Watcher lifecycle** against a live PostgreSQL, wiring the real
Mission / Configuration / Schedule / Worker / Template stack exactly as ``bootstrap`` does
(minus the running scheduler, so ticks are driven deterministically):

    instantiate from template → tick + checkpoint → survive a process restart (resume mid-count)
    → pause / resume → edited config bumps a version (picked up next tick) → live operator input
    consumed → priority influences scheduling under contention → completion → non-destructive
    archive — with **every action journaled** (P9 explainability).

Requires a live DB; the whole module is skipped if PostgreSQL is unreachable (matching
``test_repositories``), so the suite stays green without DB access.
"""

from __future__ import annotations

import pytest

from atlas.configuration import ConfigRepository, ConfigurationService
from atlas.database.connection import DatabaseManager
from atlas.missions import MissionRepository, MissionService
from atlas.missions.templates import TemplateService
from atlas.recovery import CheckpointStore
from atlas.repositories.recovery_repo import CheckpointRepository
from atlas.repositories.schedule_repo import ScheduleRepository
from atlas.repositories.task_repo import TaskRepository
from atlas.repositories.template_repo import TemplateRepository
from atlas.repositories.worker_repo import WorkerRepository
from atlas.scheduler.schedules import ScheduleService
from atlas.workers import HelloWatcher, WorkerManager


class _Stack:
    """The Phase-A service graph, plus a factory for a *fresh* Worker Manager (restart sim)."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.checkpoints = CheckpointStore(CheckpointRepository(db))
        self.mission_repo = MissionRepository(db)
        self.schedule_repo = ScheduleRepository(db)
        self.worker_repo = WorkerRepository(db)
        self.config_repo = ConfigRepository(db)
        self.task_repo = TaskRepository(db)

        self.missions = MissionService(
            self.mission_repo,
            schedule_repo=self.schedule_repo,
            worker_repo=self.worker_repo,
        )
        self.configuration = ConfigurationService(self.config_repo, self.mission_repo)
        self.schedules = ScheduleService(
            self.schedule_repo, self.task_repo, mission_repo=self.mission_repo
        )
        self.workers = self.new_worker_manager()
        self.templates = TemplateService(
            TemplateRepository(db), self.missions, self.configuration, self.workers
        )
        self.templates.seed_builtins()

    def new_worker_manager(self) -> WorkerManager:
        """A brand-new manager over the same DB — simulates a process restart (fresh RAM)."""
        mgr = WorkerManager(
            self.worker_repo,
            self.checkpoints,
            schedule_service=self.schedules,
            config_repo=self.config_repo,
            mission_repo=self.mission_repo,
        )
        mgr.register_worker_type(HelloWatcher())
        return mgr


@pytest.fixture(scope="module")
def stack():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield _Stack(manager)
    manager.close()


def _actions(stack: _Stack, mission_id: str) -> list[str]:
    return [e.action for e in stack.missions.journal_entries(mission_id, limit=200)]


def test_hello_watcher_full_lifecycle(stack: _Stack):
    # 1. Instantiate from a template → mission + config v1 + a running worker (unlimited ticks).
    result = stack.templates.instantiate(
        "hello_watcher",
        title="A.8 lifecycle",
        config_overrides={"greeting": "hello", "tick_limit": 0},
    )
    mission_id = result["mission"].id
    worker = result["workers"][0]
    wid = worker.id

    assert result["mission"].status == "active"
    assert stack.configuration.get_active(mission_id).version == 1
    view = stack.missions.get_mission(mission_id)
    assert len(view["workers"]) == 1 and view["workers"][0]["status"] == "running"
    seeded = _actions(stack, mission_id)
    assert {"created", "config_created", "activated", "worker_created"} <= set(seeded)

    # 2. First tick checkpoints its progress (count → 1).
    out = stack.workers.worker_tick({"worker_id": wid})
    assert out["ticked"] is True
    assert stack.checkpoints.load("worker", wid)["count"] == 1

    # 3. Survive a process restart: a *fresh* Worker Manager resumes mid-count (2, not 1).
    restarted = stack.new_worker_manager()
    restarted.worker_tick({"worker_id": wid})
    assert stack.checkpoints.load("worker", wid)["count"] == 2

    # 4. Pause → not tickable; Resume → ticks again (count advances to 3).
    stack.workers.pause(wid, "operator pause")
    assert stack.workers.worker_tick({"worker_id": wid})["skipped"] == "paused"
    assert stack.workers.get_worker(wid).status == "paused"
    stack.workers.resume(wid, "operator resume")
    stack.workers.worker_tick({"worker_id": wid})
    assert stack.checkpoints.load("worker", wid)["count"] == 3

    # 5. Edit config → new version; worker picks it up next tick and greets differently.
    v2 = stack.configuration.update_config(
        mission_id, {"greeting": "namaste", "tick_limit": 0}, change_note="new greeting", activate=True
    )
    assert v2.version == 2
    stack.workers.worker_tick({"worker_id": wid})
    assert "config_picked_up" in _actions(stack, mission_id)
    assert stack.checkpoints.load("worker", wid)["greeting"] == "namaste"

    # 6. Live operator input overrides the greeting on the very next tick (Q4).
    stack.workers.enqueue_input(wid, {"greeting": "yo"})
    stack.workers.worker_tick({"worker_id": wid})
    assert stack.checkpoints.load("worker", wid)["greeting"] == "yo"

    # 7. Completion: bump tick_limit to the next count so the worker reports done + stops.
    count = stack.checkpoints.load("worker", wid)["count"]
    stack.configuration.update_config(
        mission_id, {"greeting": "yo", "tick_limit": count + 1}, activate=True
    )
    done = stack.workers.worker_tick({"worker_id": wid})
    assert done["done"] is True
    assert stack.workers.get_worker(wid).status == "stopped"
    assert "worker_done" in _actions(stack, mission_id)

    # 8. Non-destructive archive: mission archived, journal + config + checkpoint all preserved.
    stack.missions.archive(mission_id, "A.8 cleanup")
    assert stack.missions.get_mission(mission_id)["mission"]["status"] == "archived"
    assert stack.checkpoints.load("worker", wid) is not None       # produced state kept (B5/B9)
    assert stack.configuration.get_version(mission_id, 1) is not None

    # 9. Everything is explainable (P9): the journal is a full, ordered account of the run.
    actions = _actions(stack, mission_id)
    for expected in (
        "created", "config_created", "activated", "worker_created",
        "worker_paused", "worker_resumed", "config_picked_up", "config_updated",
        "worker_done", "archived",
    ):
        assert expected in actions, f"missing journal action: {expected}"


def test_priority_influences_scheduling_under_contention(stack: _Stack):
    # Two missions with a clear priority gap; no autostart so we control the schedules.
    hi = stack.templates.instantiate(
        "hello_watcher", title="A.8 hi", scheduling_policy="realtime",
        priority=20, criticality="critical", autostart=False,
    )
    lo = stack.templates.instantiate(
        "hello_watcher", title="A.8 lo", scheduling_policy="idle",
        priority=0, criticality="low", autostart=False,
    )
    hi_wid = hi["workers"][0].id
    lo_wid = lo["workers"][0].id
    assert hi["mission"].effective_priority > lo["mission"].effective_priority

    # Register a worker_tick schedule per mission and enqueue each at its mission's priority.
    hi_sched = stack.schedules.register_schedule(
        "worker_tick", 60, mission_id=hi["mission"].id, worker_id=hi_wid
    )
    lo_sched = stack.schedules.register_schedule(
        "worker_tick", 60, mission_id=lo["mission"].id, worker_id=lo_wid
    )
    stack.schedules._enqueue_for(lo_sched)  # enqueue LOW first…
    stack.schedules._enqueue_for(hi_sched)  # …then HIGH — ordering must still favour HIGH

    # Claim tasks; the high-priority mission's worker_tick must be claimed before the low one.
    seen: list[str] = []
    for _ in range(200):
        row = stack.task_repo.claim_next("e2e-priority")
        if row is None:
            break
        wid = (row.get("payload") or {}).get("worker_id")
        if wid in (hi_wid, lo_wid):
            seen.append(wid)
        if hi_wid in seen and lo_wid in seen:
            break
    assert hi_wid in seen and lo_wid in seen
    assert seen.index(hi_wid) < seen.index(lo_wid)

    stack.missions.archive(hi["mission"].id, "cleanup")
    stack.missions.archive(lo["mission"].id, "cleanup")
