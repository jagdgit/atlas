"""Cross-mission arbiter tests (Phase D · §D.4, A7).

Hermetic unit tests over the pure ranking/selection and the stateful admission gate — priority order,
bounded deadline urgency, importance tiebreak, hard per-mission + global caps, and anti-starvation
aging — plus a **live-DB integration** test that drives the arbitration through a real WorkerManager
(skipped if PostgreSQL is unreachable).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atlas.core.resources.arbiter import (
    MissionArbiter,
    MissionDemand,
    demand_from_mission,
)


def _d(mid, *, prio=0, deadline=None, importance=None, cap=None, inflight=0):
    return MissionDemand(
        mission_id=mid, effective_priority=prio, deadline=deadline,
        importance=importance, max_concurrent_tasks=cap, inflight=inflight,
    )


# --- pure ranking --------------------------------------------------------

def test_rank_orders_by_effective_priority_desc():
    arb = MissionArbiter()
    ranked = arb.rank([_d("lo", prio=10), _d("hi", prio=80), _d("mid", prio=40)])
    assert [d.mission_id for d in ranked] == ["hi", "mid", "lo"]


def test_deadline_urgency_lifts_equal_priority_mission():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    arb = MissionArbiter(deadline_horizon_seconds=3600, deadline_boost_max=15)
    soon = _d("soon", prio=20, deadline=now + timedelta(minutes=5))   # near → boosted
    later = _d("later", prio=20, deadline=now + timedelta(hours=5))   # beyond horizon → no boost
    ranked = arb.rank([later, soon], now=now)
    assert [d.mission_id for d in ranked] == ["soon", "later"]
    assert arb.score(soon, now=now) > arb.score(later, now=now)


def test_overdue_deadline_gets_full_boost():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    arb = MissionArbiter(deadline_boost_max=15)
    overdue = _d("od", prio=0, deadline=now - timedelta(hours=1))
    assert arb.score(overdue, now=now) == pytest.approx(15.0)


def test_importance_breaks_ties_then_mission_id():
    arb = MissionArbiter()
    a = _d("aaa", prio=20, importance="normal")
    b = _d("bbb", prio=20, importance="critical")
    c = _d("ccc", prio=20, importance="normal")
    ranked = arb.rank([a, c, b])
    # critical wins the tie; the two normals fall back to mission_id asc.
    assert [d.mission_id for d in ranked] == ["bbb", "aaa", "ccc"]


# --- pure selection ------------------------------------------------------

def test_select_fills_slots_in_ranked_order_then_defers():
    arb = MissionArbiter()
    verdicts = arb.select([_d("lo", prio=1), _d("hi", prio=9), _d("mid", prio=5)], slots=2)
    admitted = [v.mission_id for v in verdicts if v.admitted]
    deferred = [v for v in verdicts if not v.admitted]
    assert admitted == ["hi", "mid"]
    assert deferred[0].mission_id == "lo" and "global capacity" in deferred[0].reason


def test_select_skips_mission_over_hard_cap_and_gives_slot_to_next():
    arb = MissionArbiter()
    # "hi" outranks but is already at its own cap → deferred; its slot goes to the next admissible.
    verdicts = arb.select(
        [_d("hi", prio=9, cap=1, inflight=1), _d("mid", prio=5), _d("lo", prio=1)], slots=1
    )
    by_id = {v.mission_id: v for v in verdicts}
    assert by_id["hi"].admitted is False and "mission budget cap" in by_id["hi"].reason
    assert by_id["mid"].admitted is True
    assert by_id["lo"].admitted is False


# --- stateful admission gate --------------------------------------------

def test_try_admit_enforces_per_mission_hard_cap():
    arb = MissionArbiter()
    assert arb.try_admit(_d("m", cap=1)).admitted is True
    denied = arb.try_admit(_d("m", cap=1))
    assert denied.admitted is False and "mission budget cap" in denied.reason
    arb.release("m")
    assert arb.try_admit(_d("m", cap=1)).admitted is True


def test_try_admit_enforces_global_cap_across_missions():
    arb = MissionArbiter(global_max_concurrent=1)
    assert arb.try_admit(_d("a")).admitted is True
    blocked = arb.try_admit(_d("b"))  # different mission, but the single global slot is taken
    assert blocked.admitted is False and "global capacity" in blocked.reason
    arb.release("a")
    assert arb.try_admit(_d("b")).admitted is True


def test_deferred_mission_is_aged_and_not_starved():
    arb = MissionArbiter(global_max_concurrent=1, starvation_boost_per_defer=2.0)
    arb.try_admit(_d("holder"))  # occupies the only slot
    victim = _d("victim", prio=10)
    base = arb.score(victim)
    for _ in range(3):
        assert arb.try_admit(victim).admitted is False
    aged = arb.score(victim)
    assert aged > base                      # repeated deferral raised its standing
    assert arb.deferrals_for("victim") == 3
    arb.release("holder")
    assert arb.try_admit(victim).admitted is True
    assert arb.deferrals_for("victim") == 0  # admission resets the aging


def test_demand_from_mission_projects_arbitration_fields():
    from atlas.models.mission import Mission

    m = Mission(
        id="m1", title="t", scheduling_policy="realtime", priority=10, criticality="high",
        budget={"max_concurrent_tasks": 2}, importance="critical",
    )
    demand = demand_from_mission(m)
    assert demand.mission_id == "m1"
    assert demand.effective_priority == m.effective_priority
    assert demand.max_concurrent_tasks == 2
    assert demand.importance == "critical"


# --- live-DB integration through the WorkerManager -----------------------

@pytest.fixture(scope="module")
def stack():
    from atlas.database.connection import DatabaseManager
    from atlas.missions import MissionRepository, MissionService
    from atlas.recovery import CheckpointStore
    from atlas.repositories.recovery_repo import CheckpointRepository
    from atlas.repositories.worker_repo import WorkerRepository
    from atlas.workers import HelloWatcher, WorkerManager

    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")

    mission_repo = MissionRepository(db)
    missions = MissionService(mission_repo)
    arbiter = MissionArbiter(global_max_concurrent=1)  # a single shared slot forces contention
    workers = WorkerManager(
        WorkerRepository(db),
        CheckpointStore(CheckpointRepository(db)),
        mission_repo=mission_repo,
        arbiter=arbiter,
    )
    workers.register_worker_type(HelloWatcher())
    yield {"missions": missions, "workers": workers, "arbiter": arbiter}
    db.close()


def test_global_contention_defers_lower_mission_through_worker_manager(stack):
    missions, workers, arbiter = stack["missions"], stack["workers"], stack["arbiter"]

    hi = missions.create_mission("D.4 hi", scheduling_policy="realtime", priority=20, criticality="critical")
    lo = missions.create_mission("D.4 lo", scheduling_policy="idle", priority=0, criticality="low")
    hi_worker = workers.create_worker(hi.id, "hello_watcher", autostart=False)
    lo_worker = workers.create_worker(lo.id, "hello_watcher", autostart=False)

    # Occupy the single global slot with the HIGH mission; the LOW mission's tick must be deferred.
    held = arbiter.try_admit(demand_from_mission(hi))
    assert held.admitted is True
    out = workers.worker_tick({"worker_id": lo_worker.id})
    assert out == {"skipped": "budget", "worker_id": lo_worker.id}

    # Free the slot → the deferred worker now ticks (not starved).
    arbiter.release(hi.id)
    out2 = workers.worker_tick({"worker_id": lo_worker.id})
    assert out2["ticked"] is True
    assert arbiter.inflight_for(lo.id) == 0  # released after the tick

    missions.archive(hi.id, "cleanup")
    missions.archive(lo.id, "cleanup")
