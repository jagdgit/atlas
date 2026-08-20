"""IR-RO3 — template Work Resource Profiles + service classes."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.core.resources.work_profile import (
    SERVICE_BATCH,
    SERVICE_REALTIME,
    service_class_rank,
)
from atlas.missions.philosophy import with_philosophy
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.templates.resources import (
    TEMPLATE_RESOURCES,
    resources_for,
)
from atlas.missions.templates.service import TemplateService


def test_all_builtins_have_resources_block():
    for tmpl in BUILTIN_TEMPLATES:
        sc = tmpl["success_criteria"]
        assert "resources" in sc, tmpl["name"]
        assert sc["resources"]["service_class"] in {
            "REALTIME",
            "INTERACTIVE",
            "NORMAL",
            "BATCH",
        }
        assert tmpl["name"] in TEMPLATE_RESOURCES


def test_market_is_realtime_archive_is_batch():
    assert resources_for("market_observer").service_class == SERVICE_REALTIME
    assert resources_for("decision_simulation").service_class == SERVICE_REALTIME
    assert resources_for("owner_knowledge").service_class == SERVICE_BATCH
    assert resources_for("historical_bars_bootstrap").service_class == SERVICE_BATCH
    assert resources_for("market_observer").deadline_policy == "signal_ttl"
    assert service_class_rank("REALTIME") < service_class_rank("BATCH")


def test_with_philosophy_embeds_resources():
    sc = with_philosophy({}, "market_observer")
    assert sc["philosophy"]["mission_kind"]
    assert sc["resources"]["service_class"] == "REALTIME"


def test_instantiate_applies_service_class_and_policy():
    created = {}

    class FakeRepo:
        def get_by_name(self, name):
            return SimpleNamespace(
                id="t1",
                name=name,
                template_version=1,
                knowledge_domains=[],
                success_criteria=with_philosophy({}, name),
                default_config={"greeting": "hi"},
                config_schema_type="hello_watcher",
                worker_specs=[{"type": "hello_watcher", "interval_seconds": 60}],
            )

        def list(self):
            return []

    class FakeMissions:
        def create_mission(self, title, objective, **kwargs):
            created["mission_kwargs"] = kwargs
            return SimpleNamespace(id="m1", title=title, **kwargs)

        def activate(self, mid, _note):
            return SimpleNamespace(id=mid, status="active")

    class FakeConfigs:
        def create_config(self, mission_id, schema, document, change_note=""):
            return SimpleNamespace(id="c1", document=document)

    class FakeWorkers:
        def __init__(self):
            self.workers = []

        def create_worker(self, mission_id, wtype, **kwargs):
            w = SimpleNamespace(id="w1", type=wtype, metadata=kwargs.get("metadata"))
            self.workers.append(w)
            return w

    workers = FakeWorkers()
    svc = TemplateService(FakeRepo(), FakeMissions(), FakeConfigs(), workers)
    out = svc.instantiate("market_observer", title="Obs")
    assert out["resources"]["service_class"] == "REALTIME"
    mk = created["mission_kwargs"]
    assert mk["scheduling_policy"] == "realtime"
    assert mk["criticality"] == "critical"
    assert mk["metadata"]["service_class"] == "REALTIME"
    assert mk["budget"]["ram_mb"] == 256
    assert workers.workers[0].metadata["service_class"] == "REALTIME"
    assert workers.workers[0].metadata["ops"]["expected_tick_ms"] == 2000


def test_instantiate_owner_knowledge_batch():
    created = {}

    class FakeRepo:
        def get_by_name(self, name):
            return SimpleNamespace(
                id="t1",
                name="owner_knowledge",
                template_version=1,
                knowledge_domains=[],
                success_criteria=with_philosophy({}, "owner_knowledge"),
                default_config={},
                config_schema_type="owner_knowledge",
                worker_specs=[{"type": "owner_knowledge", "interval_seconds": 60}],
            )

        def list(self):
            return []

    class FakeMissions:
        def create_mission(self, *a, **kwargs):
            created["kwargs"] = kwargs
            return SimpleNamespace(id="m1")

        def activate(self, mid, _n):
            return SimpleNamespace(id=mid)

    class FakeConfigs:
        def create_config(self, *a, **k):
            return SimpleNamespace(id="c1")

    class FakeWorkers:
        def create_worker(self, *a, **k):
            return SimpleNamespace(id="w1", metadata=k.get("metadata"))

    svc = TemplateService(FakeRepo(), FakeMissions(), FakeConfigs(), FakeWorkers())
    out = svc.instantiate(
        "owner_knowledge",
        metadata={"program_id": "personal_intelligence", "queued_for_capacity": True},
        autostart=False,
    )
    assert out["resources"]["service_class"] == "BATCH"
    assert created["kwargs"]["scheduling_policy"] == "batch"
    assert created["kwargs"]["criticality"] == "low"
    assert created["kwargs"]["metadata"]["program_id"] == "personal_intelligence"
    assert created["kwargs"]["metadata"]["service_class"] == "BATCH"
