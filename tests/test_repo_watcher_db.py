"""Live-DB smoke for the Repository-Learning mission + RepoWatcher (Phase B · §B.6).

Wires the *real* Template / Mission / Configuration / Schedule / Worker stack against a live
PostgreSQL (as ``bootstrap`` does) to prove the seam end to end: instantiating the
``repository_learning`` template creates a mission + a **strict** ``repo_watcher`` config v1 + a
RepoWatcher worker; a tick ingests + checkpoints, a "process restart" resumes, an unchanged tree
is a cheap **Detect** no-op, and a config edit bumps a version that is picked up next tick — all
journaled. The ingest call itself is faked here (the full ingest e2e is the B.8 gate). Skipped
when PostgreSQL is unreachable (matches tests/test_phase_a_e2e.py).
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
from atlas.workers import RepoWatcher, WorkerManager
from tests.test_repo_watcher import FakeIntel, _ok, _repo


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


class _Stack:
    def __init__(self, db: DatabaseManager, intel) -> None:
        self.db = db
        self.intel = intel
        self.checkpoints = CheckpointStore(CheckpointRepository(db))
        self.mission_repo = MissionRepository(db)
        self.schedule_repo = ScheduleRepository(db)
        self.worker_repo = WorkerRepository(db)
        self.config_repo = ConfigRepository(db)
        self.task_repo = TaskRepository(db)
        self.missions = MissionService(
            self.mission_repo, schedule_repo=self.schedule_repo, worker_repo=self.worker_repo
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
        mgr = WorkerManager(
            self.worker_repo, self.checkpoints, schedule_service=self.schedules,
            config_repo=self.config_repo, mission_repo=self.mission_repo,
        )
        mgr.register_worker_type(RepoWatcher(self.intel))
        return mgr


def _actions(stack, mission_id):
    return [e.action for e in stack.missions.journal_entries(mission_id, limit=200)]


def test_repository_learning_mission_lifecycle(db, tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([
        _ok(version=1, findings=3, design=0),
        _ok(version=2, diff={"changed": True, "added_modules": ["b.py"]}, findings=4),
    ])
    stack = _Stack(db, intel)

    # 1. Instantiate the real template → mission + strict repo_watcher config v1 + worker.
    result = stack.templates.instantiate(
        "repository_learning",
        title="B.6 repo-learning",
        config_overrides={"repo_path": root},
    )
    mission_id = result["mission"].id
    wid = result["workers"][0].id
    try:
        assert result["mission"].status == "active"
        assert result["workers"][0].type == "repo_watcher"
        active_cfg = stack.configuration.get_active(mission_id)
        assert active_cfg.version == 1 and active_cfg.schema_type == "repo_watcher"
        assert active_cfg.document["repo_path"] == root
        assert {"created", "config_created", "activated", "worker_created"} <= set(
            _actions(stack, mission_id)
        )

        # 2. First tick ingests + checkpoints its progress.
        r1 = stack.workers.worker_tick({"worker_id": wid})
        assert r1["ticked"] is True
        assert len(intel.calls) == 1
        cp = stack.checkpoints.load("worker", wid)
        assert cp["ingests"] == 1 and cp["last_tree_checksum"]

        # 3. "Process restart": a fresh Worker Manager resumes; unchanged tree → Detect no-op.
        restarted = stack.new_worker_manager()
        restarted.worker_tick({"worker_id": wid})
        assert len(intel.calls) == 1  # short-circuited, no re-ingest
        assert stack.checkpoints.load("worker", wid)["last_result"] == "no_change"

        # 4. Change the repo → next tick re-ingests (structural change).
        (tmp_path / "svc" / "b.py").write_text("x = 2\n")
        stack.workers.worker_tick({"worker_id": wid})
        assert len(intel.calls) == 2
        assert stack.checkpoints.load("worker", wid)["ingests"] == 2

        # 5. Edit config (toggle embed) → new version, picked up next tick (journaled).
        v2 = stack.configuration.update_config(
            mission_id,
            {**active_cfg.document, "embed_code": True},
            change_note="enable embeddings", activate=True,
        )
        assert v2.version == 2
        stack.workers.worker_tick({"worker_id": wid})  # unchanged tree now → no-op, but config note
        assert "config_picked_up" in _actions(stack, mission_id)
        assert stack.checkpoints.load("worker", wid)["config_version"] == 2
    finally:
        stack.missions.archive(mission_id, "B.6 cleanup")
