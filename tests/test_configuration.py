"""Configuration Manager tests (Phase A · §A.2).

Hermetic: fake config + mission repositories stand in for ``config.mission_configs`` /
``mission.missions``, so we cover schema validation (invalid rejected, unknown type rejected),
versioning (immutable prior versions, monotonic numbers), auto-activation of the first config,
explicit ``set_active`` flips, ``schema_version`` stamping (B6), and journaling — all without a
database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from atlas.configuration.schemas import ConfigSchemaError, SchemaRegistry
from atlas.configuration.service import ConfigError, ConfigurationService
from atlas.models.config import MissionConfig


# --- fakes ---------------------------------------------------------------


class FakeConfigRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def next_version(self, mission_id) -> int:
        versions = [r["version"] for r in self.rows.values() if r["mission_id"] == str(mission_id)]
        return max(versions) + 1 if versions else 1

    def create_version(
        self, *, mission_id, version, schema_type, schema_version, document, change_note=""
    ) -> MissionConfig:
        cid = str(uuid4())
        row = {
            "id": cid,
            "mission_id": str(mission_id),
            "version": version,
            "schema_type": schema_type,
            "schema_version": schema_version,
            "document": document,
            "change_note": change_note,
            "created_at": datetime.now(timezone.utc),
        }
        self.rows[cid] = row
        return MissionConfig.from_row(row)

    def get_by_id(self, config_id) -> MissionConfig | None:
        row = self.rows.get(str(config_id))
        return MissionConfig.from_row(row) if row else None

    def get_version(self, mission_id, version) -> MissionConfig | None:
        for row in self.rows.values():
            if row["mission_id"] == str(mission_id) and row["version"] == version:
                return MissionConfig.from_row(row)
        return None

    def get_active(self, mission_id) -> MissionConfig | None:
        # resolved via the fake mission repo's active_config_id
        active_id = _MISSIONS.active.get(str(mission_id))
        return self.get_by_id(active_id) if active_id else None

    def list_versions(self, mission_id) -> list[MissionConfig]:
        rows = [r for r in self.rows.values() if r["mission_id"] == str(mission_id)]
        rows.sort(key=lambda r: r["version"], reverse=True)
        return MissionConfig.from_rows(rows)


class FakeMissionRepo:
    def __init__(self) -> None:
        self.missions: dict[str, bool] = {}
        self.active: dict[str, str] = {}
        self.journal: list[dict[str, Any]] = []

    def add_mission(self) -> str:
        mid = str(uuid4())
        self.missions[mid] = True
        return mid

    def get(self, mission_id):
        return object() if str(mission_id) in self.missions else None

    def set_active_config(self, mission_id, config_id) -> bool:
        self.active[str(mission_id)] = str(config_id)
        return True

    def add_journal(self, mission_id, action, reason="", refs=None):
        self.journal.append(
            {"mission_id": str(mission_id), "action": action, "reason": reason, "refs": refs or {}}
        )
        return None


# Shared handle so FakeConfigRepo.get_active can resolve the active pointer.
_MISSIONS = FakeMissionRepo()


@pytest.fixture()
def svc():
    global _MISSIONS
    _MISSIONS = FakeMissionRepo()
    cfg_repo = FakeConfigRepo()
    mid = _MISSIONS.add_mission()
    service = ConfigurationService(cfg_repo, _MISSIONS)
    return service, cfg_repo, _MISSIONS, mid


# --- schema registry -----------------------------------------------------


def test_validate_normalizes_and_reports_version():
    reg = SchemaRegistry()

    class Demo(BaseModel):
        model_config = ConfigDict(extra="forbid")

        n: int = Field(default=1, ge=0)

    reg.register("demo", Demo, schema_version=3)
    doc, ver = reg.validate("demo", {"n": 5})
    assert doc == {"n": 5}
    assert ver == 3


def test_validate_rejects_unknown_type():
    reg = SchemaRegistry()
    with pytest.raises(ConfigSchemaError):
        reg.validate("nope", {})


def test_owner_knowledge_schema_validates_archive_roots():
    from atlas.configuration.schemas import default_registry

    reg = default_registry()
    doc, ver = reg.validate("owner_knowledge", {
        "archive_roots": [
            {"path": "/data/code", "kind": "code", "domain": "engineering"},
            {"path": "/data/chats", "kind": "conversation"},
        ],
    })
    assert ver == 1
    assert doc["archive_roots"][0]["kind"] == "code"
    assert doc["archive_roots"][1]["domain"] == "personal"  # default
    assert doc["build_profile"] is True  # default


def test_owner_knowledge_schema_rejects_bad_root_kind():
    from atlas.configuration.schemas import default_registry

    with pytest.raises(ConfigSchemaError):
        default_registry().validate(
            "owner_knowledge", {"archive_roots": [{"path": "/x", "kind": "video"}]}
        )


def test_validate_rejects_extra_keys():
    reg = SchemaRegistry()

    class Demo(BaseModel):
        model_config = ConfigDict(extra="forbid")
        n: int = 1

    reg.register("demo", Demo)
    with pytest.raises(ConfigSchemaError):
        reg.validate("demo", {"n": 1, "surprise": True})


# --- create / versioning -------------------------------------------------


def test_create_first_config_auto_activates(svc):
    service, _, missions, mid = svc
    cfg = service.create_config(mid, "hello_watcher", {"greeting": "hi"})
    assert cfg.version == 1
    assert cfg.schema_version == 1
    assert cfg.document["greeting"] == "hi"
    assert missions.active[mid] == cfg.id  # first config auto-activated
    assert any(e["action"] == "config_created" for e in missions.journal)


def test_create_rejects_invalid_document(svc):
    service, _, _, mid = svc
    with pytest.raises(ConfigSchemaError):
        service.create_config(mid, "hello_watcher", {"tick_limit": -1})


def test_create_rejects_unknown_mission(svc):
    service, _, _, _ = svc
    with pytest.raises(ConfigError):
        service.create_config(str(uuid4()), "hello_watcher", {})


def test_update_creates_new_version_keeps_active(svc):
    service, _, missions, mid = svc
    v1 = service.create_config(mid, "hello_watcher", {"greeting": "one"})
    v2 = service.update_config(mid, {"greeting": "two"}, change_note="edit")
    assert v2.version == 2
    # v1 retained + immutable; active still v1 (update does not auto-activate)
    assert service.get_version(mid, 1).document["greeting"] == "one"
    assert missions.active[mid] == v1.id


def test_update_with_activate_flips_active(svc):
    service, _, missions, mid = svc
    service.create_config(mid, "hello_watcher", {"greeting": "one"})
    v2 = service.update_config(mid, {"greeting": "two"}, activate=True)
    assert missions.active[mid] == v2.id


def test_update_without_prior_config_errors(svc):
    service, _, _, mid = svc
    with pytest.raises(ConfigError):
        service.update_config(mid, {"greeting": "x"})


def test_set_active_flips_between_versions(svc):
    service, _, missions, mid = svc
    v1 = service.create_config(mid, "hello_watcher", {"greeting": "one"})
    v2 = service.update_config(mid, {"greeting": "two"})
    service.set_active(mid, 2)
    assert missions.active[mid] == v2.id
    service.set_active(mid, 1)
    assert missions.active[mid] == v1.id


def test_set_active_missing_version_errors(svc):
    service, _, _, mid = svc
    service.create_config(mid, "hello_watcher", {})
    with pytest.raises(ConfigError):
        service.set_active(mid, 99)


def test_get_active_and_list_versions(svc):
    service, _, _, mid = svc
    service.create_config(mid, "hello_watcher", {"greeting": "one"})
    service.update_config(mid, {"greeting": "two"})
    service.update_config(mid, {"greeting": "three"})
    versions = service.list_versions(mid)
    assert [v.version for v in versions] == [3, 2, 1]
    assert service.get_active(mid).version == 1  # only v1 was auto-activated


def test_health_reports_registered_schemas(svc):
    service, _, _, _ = svc
    status = service.health_check()
    assert status.healthy
    assert "hello_watcher" in status.data["schemas"]
