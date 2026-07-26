"""Phase 5 — IR-M1/M2/M3/RO9 unit coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand, demand_from_mission
from atlas.core.resources.mission_dag import (
    ROLE_EXTRACT,
    all_deps_terminal,
    dag_block,
    read_dag,
)
from atlas.core.resources.power import PowerSnapshot, probe_power, read_thermal_zones
from atlas.missions.service import MissionService
from atlas.models.mission import MISSION_WAITING
from tests.test_missions import FakeEvents, FakeMissionRepo


def test_dag_block_and_read_roundtrip():
    block = dag_block(parent_id="p1", role=ROLE_EXTRACT, children=["c1"], pipeline=["extract"])
    assert block["parent_id"] == "p1"
    assert block["role"] == "extract"
    assert read_dag({"dag": block})["children"] == ["c1"]


def test_all_deps_terminal():
    assert all_deps_terminal(["a", "b"], {"a": "completed", "b": "archived"})
    assert not all_deps_terminal(["a", "b"], {"a": "completed", "b": "active"})
    assert all_deps_terminal([], {})


def test_spawn_child_waits_and_unblocks_on_complete():
    repo = FakeMissionRepo()
    svc = MissionService(repo, events=FakeEvents())
    parent = svc.create_mission("Parent pipeline")
    svc.activate(parent.id)
    child = svc.spawn_child(parent.id, "Extract step", role="extract", wait_on_child=True)
    parent_view = svc.get_mission(parent.id)["mission"]
    assert parent_view["status"] == MISSION_WAITING
    assert str(child.id) in (parent_view.get("metadata") or {}).get("queue", {}).get(
        "depends_on", []
    )
    dag = svc.get_dag(parent_view["id"])
    assert str(child.id) in dag["dag"]["children"]

    svc.complete(child.id, "done")
    parent2 = svc.get_mission(parent_view["id"])["mission"]
    assert parent2["status"] != MISSION_WAITING
    q = (parent2.get("metadata") or {}).get("queue") or {}
    assert q.get("state") == "READY"


def test_wait_aging_boosts_long_waiting_mission():
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    arb = MissionArbiter(
        wait_aging_boost_per_minute=1.0,
        wait_aging_boost_max=30.0,
        starvation_boost_per_defer=0.0,
    )
    fresh = MissionDemand(mission_id="fresh", effective_priority=10, wait_since=now)
    aged = MissionDemand(
        mission_id="aged",
        effective_priority=10,
        wait_since=now - timedelta(minutes=20),
    )
    assert arb.score(aged, now=now) > arb.score(fresh, now=now)
    ranked = arb.rank([fresh, aged], now=now)
    assert ranked[0].mission_id == "aged"


def test_low_confidence_gets_scheduler_boost():
    arb = MissionArbiter(confidence_boost_max=8.0, confidence_low_threshold=0.55)
    hi = MissionDemand(mission_id="hi", effective_priority=10, confidence_score=0.9)
    lo = MissionDemand(mission_id="lo", effective_priority=10, confidence_score=0.2)
    assert arb.score(lo) > arb.score(hi)


def test_demand_from_mission_reads_queue_and_research():
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mission = SimpleNamespace(
        id="m1",
        effective_priority=5,
        deadline=None,
        importance="normal",
        max_concurrent_tasks=1,
        llm_units_per_window=None,
        llm_window_seconds=300,
        ram_mb=None,
        success_criteria={},
        metadata={
            "service_class": "NORMAL",
            "queue": {"state": "READY", "since": since.isoformat()},
            "research": {"confidence_score": 0.3},
        },
    )
    d = demand_from_mission(mission)
    assert d.wait_since is not None
    assert d.confidence_score == 0.3
    assert d.service_class == "NORMAL"


def test_set_research_confidence():
    repo = FakeMissionRepo()
    svc = MissionService(repo, events=FakeEvents())
    m = svc.create_mission("Research")
    m = svc.set_research_confidence(m.id, confidence_score=0.25, confidence="low")
    assert (m.metadata or {}).get("research", {}).get("confidence_score") == 0.25


def test_probe_power_returns_snapshot():
    snap = probe_power()
    assert isinstance(snap, PowerSnapshot)
    d = snap.as_dict()
    assert "monitored" in d
    assert "note" in d
    if not snap.monitored:
        assert snap.present is False


def test_read_thermal_zones_tolerates_missing():
    zones = read_thermal_zones(root=Path("/nonexistent/thermal"))
    assert zones == []
