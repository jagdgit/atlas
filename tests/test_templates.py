"""Mission template tests (Phase A · §A.5, B7).

Hermetic: a fake template repo plus the real Mission/Configuration/Worker services over their
in-memory fakes, so we cover seeding, instantiation (mission + config v1 + workers), config
overrides at instantiation, template_version stamping, that a built-in bump never mutates an
existing mission, and unknown-template errors — all without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from atlas.configuration.service import ConfigurationService
from atlas.missions.service import MissionService
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.templates.service import TemplateError, TemplateService
from atlas.models.template import MissionTemplate
from atlas.workers import HelloWatcher, WorkerManager

# Reuse the fakes from the sibling suites.
from tests.test_configuration import FakeConfigRepo as _FakeCfgRepo
from tests.test_workers import FakeCheckpoints, FakeSchedules, FakeWorkerRepo


# --- fakes ---------------------------------------------------------------


class FakeMissionRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.active: dict[str, str] = {}
        self.journal: list[dict[str, Any]] = []

    def create(self, **kw: Any):
        from atlas.models.mission import Mission

        mid = str(uuid4())
        now = datetime.now(timezone.utc)
        row = {
            "id": mid, "title": kw["title"], "objective": kw.get("objective", ""),
            "status": kw.get("status", "draft"),
            "success_criteria": kw.get("success_criteria") or {},
            "knowledge_domains": list(kw.get("knowledge_domains") or []),
            "active_config_id": None, "scheduling_policy": kw["scheduling_policy"],
            "priority": kw["priority"], "criticality": kw["criticality"],
            "budget": kw.get("budget") or {}, "deadline": kw.get("deadline"),
            "importance": kw.get("importance"), "labels": list(kw.get("labels") or []),
            "metadata": kw.get("metadata") or {}, "template_id": kw.get("template_id"),
            "template_version": kw.get("template_version"), "created_at": now, "updated_at": now,
        }
        self.rows[mid] = row
        return Mission.from_row(row)

    def get(self, mission_id):
        from atlas.models.mission import Mission

        row = self.rows.get(str(mission_id))
        return Mission.from_row(row) if row else None

    def list(self, *, status=None, label=None, limit=100):
        return []

    def set_status(self, mission_id, status):
        self.rows[str(mission_id)]["status"] = status
        return True

    def set_active_config(self, mission_id, config_id):
        self.active[str(mission_id)] = str(config_id)
        return True

    def add_journal(self, mission_id, action, reason="", refs=None):
        self.journal.append({"mission_id": str(mission_id), "action": action, "reason": reason})
        return None

    def list_journal(self, mission_id, *, limit=100):
        return []

    def list_job_ids(self, mission_id):
        return []


class FakeCfgRepoWithActive:
    """Config repo that also resolves get_active against a mission repo's active pointer."""

    def __init__(self, missions: FakeMissionRepo) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._missions = missions

    def next_version(self, mission_id):
        vs = [r["version"] for r in self.rows.values() if r["mission_id"] == str(mission_id)]
        return max(vs) + 1 if vs else 1

    def create_version(self, *, mission_id, version, schema_type, schema_version, document, change_note=""):
        from atlas.models.config import MissionConfig

        cid = str(uuid4())
        row = {
            "id": cid, "mission_id": str(mission_id), "version": version,
            "schema_type": schema_type, "schema_version": schema_version,
            "document": document, "change_note": change_note,
            "created_at": datetime.now(timezone.utc),
        }
        self.rows[cid] = row
        return MissionConfig.from_row(row)

    def get_by_id(self, cid):
        from atlas.models.config import MissionConfig

        row = self.rows.get(str(cid))
        return MissionConfig.from_row(row) if row else None

    def get_version(self, mission_id, version):
        from atlas.models.config import MissionConfig

        for r in self.rows.values():
            if r["mission_id"] == str(mission_id) and r["version"] == version:
                return MissionConfig.from_row(r)
        return None

    def get_active(self, mission_id):
        return self.get_by_id(self._missions.active.get(str(mission_id)))

    def list_versions(self, mission_id):
        from atlas.models.config import MissionConfig

        rows = [r for r in self.rows.values() if r["mission_id"] == str(mission_id)]
        rows.sort(key=lambda r: r["version"], reverse=True)
        return MissionConfig.from_rows(rows)


class FakeTemplateRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def upsert_by_name(self, *, name, template_version, config_schema_type,
                       config_schema_version=1, description="", worker_specs=None,
                       default_config=None, knowledge_domains=None, success_criteria=None):
        existing = self.rows.get(name)
        tid = existing["id"] if existing else str(uuid4())
        row = {
            "id": tid, "name": name, "template_version": template_version,
            "description": description, "worker_specs": worker_specs or [],
            "config_schema_type": config_schema_type,
            "config_schema_version": config_schema_version,
            "default_config": default_config or {},
            "knowledge_domains": knowledge_domains or [],
            "success_criteria": success_criteria or {},
            "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        }
        self.rows[name] = row
        return MissionTemplate.from_row(row)

    def get_by_name(self, name):
        row = self.rows.get(name)
        return MissionTemplate.from_row(row) if row else None

    def get(self, tid):
        for row in self.rows.values():
            if row["id"] == str(tid):
                return MissionTemplate.from_row(row)
        return None

    def list(self):
        return MissionTemplate.from_rows(sorted(self.rows.values(), key=lambda r: r["name"]))


@pytest.fixture()
def svc():
    missions_repo = FakeMissionRepo()
    cfg_repo = FakeCfgRepoWithActive(missions_repo)
    tmpl_repo = FakeTemplateRepo()
    mission_service = MissionService(missions_repo)
    config_service = ConfigurationService(cfg_repo, missions_repo)
    worker_repo = FakeWorkerRepo()
    worker_manager = WorkerManager(
        worker_repo, FakeCheckpoints(), schedule_service=FakeSchedules(),
        config_repo=cfg_repo, mission_repo=missions_repo,
    )
    worker_manager.register_worker_type(HelloWatcher())
    service = TemplateService(tmpl_repo, mission_service, config_service, worker_manager)
    service.seed_builtins()
    return service, tmpl_repo, missions_repo, cfg_repo, worker_repo


# --- seeding -------------------------------------------------------------


def test_seed_creates_all_builtins(svc):
    service, tmpl_repo, *_ = svc
    names = {t.name for t in service.list_templates()}
    assert {b["name"] for b in BUILTIN_TEMPLATES} == names
    assert "hello_watcher" in names


def test_seed_is_idempotent_and_upserts(svc):
    service, tmpl_repo, *_ = svc
    before = service.get_template("hello_watcher").id
    service.seed_builtins()  # second boot
    after = service.get_template("hello_watcher").id
    assert before == after  # upsert by name keeps identity
    assert len(service.list_templates()) == len(BUILTIN_TEMPLATES)


# --- instantiation -------------------------------------------------------


def test_instantiate_hello_watcher_full(svc):
    service, _, missions_repo, cfg_repo, worker_repo = svc
    out = service.instantiate("hello_watcher", title="My Heartbeat")
    mission = out["mission"]
    assert mission.title == "My Heartbeat"
    assert missions_repo.rows[mission.id]["status"] == "active"  # activated
    assert mission.template_version == 1
    assert mission.template_id is not None
    # config v1 exists and is the hello_watcher schema
    assert out["config"].version == 1
    assert out["config"].schema_type == "hello_watcher"
    # one running worker created
    assert len(out["workers"]) == 1
    assert out["workers"][0].type == "hello_watcher"
    assert worker_repo.get(out["workers"][0].id).status == "running"


def test_instantiate_applies_config_overrides(svc):
    service, *_ = svc
    out = service.instantiate("hello_watcher", config_overrides={"greeting": "bonjour", "tick_limit": 3})
    assert out["config"].document["greeting"] == "bonjour"
    assert out["config"].document["tick_limit"] == 3


def test_instantiate_stub_creates_mission_and_config_no_workers(svc):
    service, *_ = svc
    out = service.instantiate("paper_trading")
    assert out["mission"].template_version == 1
    assert out["config"].schema_type == "generic"
    assert out["workers"] == []  # stub: no workers until Phase D


def test_instantiate_unknown_template_raises(svc):
    service, *_ = svc
    with pytest.raises(TemplateError):
        service.instantiate("nonexistent")


def test_builtin_bump_does_not_mutate_existing_mission(svc):
    service, tmpl_repo, missions_repo, *_ = svc
    out = service.instantiate("hello_watcher")
    stamped = out["mission"].template_version
    # simulate editing + bumping the built-in and re-seeding on a later boot
    tmpl_repo.upsert_by_name(
        name="hello_watcher", template_version=5, config_schema_type="hello_watcher",
        default_config={"greeting": "hi", "tick_limit": 0, "tick_interval_seconds": 60},
        worker_specs=[{"type": "hello_watcher", "interval_seconds": 60}],
    )
    assert service.get_template("hello_watcher").template_version == 5  # template moved
    # the already-instantiated mission keeps its original stamp (B7)
    assert missions_repo.rows[out["mission"].id]["template_version"] == stamped == 1


def test_health_reports_template_count(svc):
    service, *_ = svc
    status = service.health_check()
    assert status.healthy
    assert status.data["templates"] == len(BUILTIN_TEMPLATES)
