"""IR-RO5 — Candidate Selector + REALTIME tick reserve."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand
from atlas.core.resources.scheduler import CandidateSelector, ResourceScheduler
from atlas.core.resources.work_profile import SERVICE_BATCH, SERVICE_REALTIME


def _d(mid, *, prio=0, service_class=None, deadline=None, cap=None, inflight=0):
    return MissionDemand(
        mission_id=mid,
        effective_priority=prio,
        service_class=service_class,
        deadline=deadline,
        max_concurrent_tasks=cap,
        inflight=inflight,
    )


def test_candidate_selector_prefers_realtime_over_batch():
    arb = MissionArbiter(global_max_concurrent=2)
    sel = CandidateSelector(arb)
    ranked = sel.rank(
        [
            _d("archive", prio=90, service_class=SERVICE_BATCH),
            _d("market", prio=10, service_class=SERVICE_REALTIME),
        ]
    )
    assert [d.mission_id for d in ranked] == ["market", "archive"]


def test_deadline_beats_priority_within_class():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    arb = MissionArbiter(global_max_concurrent=2)
    sel = CandidateSelector(arb)
    ranked = sel.rank(
        [
            _d("later", prio=80, service_class=SERVICE_REALTIME, deadline=now + timedelta(hours=2)),
            _d("soon", prio=10, service_class=SERVICE_REALTIME, deadline=now + timedelta(seconds=30)),
        ],
        now=now,
    )
    assert ranked[0].mission_id == "soon"


def test_realtime_reserve_blocks_second_batch_slot():
    arb = MissionArbiter(global_max_concurrent=2)  # reserve 1
    # Fill one slot with BATCH
    v1 = arb.try_admit(_d("batch1", service_class=SERVICE_BATCH))
    assert v1.admitted
    # Second BATCH should hit realtime_reserve (only 1 non-rt slot)
    v2 = arb.try_admit(_d("batch2", service_class=SERVICE_BATCH))
    assert not v2.admitted
    assert "realtime_reserve" in v2.reason
    # REALTIME still gets the reserved slot
    v3 = arb.try_admit(_d("market", service_class=SERVICE_REALTIME))
    assert v3.admitted
    snap = arb.snapshot()
    assert snap["total_inflight"] == 2
    assert snap["realtime_inflight"] == 1
    assert snap["realtime_reserve_slots"] == 1


def test_realtime_can_use_both_slots():
    arb = MissionArbiter(global_max_concurrent=2)
    assert arb.try_admit(_d("m1", service_class=SERVICE_REALTIME)).admitted
    assert arb.try_admit(_d("m2", service_class=SERVICE_REALTIME)).admitted
    assert arb.snapshot()["realtime_inflight"] == 2


def test_release_clears_realtime_inflight():
    arb = MissionArbiter(global_max_concurrent=2)
    arb.try_admit(_d("m1", service_class=SERVICE_REALTIME))
    arb.release("m1")
    assert arb.snapshot()["realtime_inflight"] == 0
    assert arb.snapshot()["total_inflight"] == 0


def test_select_honours_realtime_reserve():
    arb = MissionArbiter(global_max_concurrent=2)
    verdicts = arb.select(
        [
            _d("b1", prio=50, service_class=SERVICE_BATCH),
            _d("b2", prio=40, service_class=SERVICE_BATCH),
            _d("rt", prio=1, service_class=SERVICE_REALTIME),
        ],
        slots=2,
    )
    admitted = {v.mission_id for v in verdicts if v.admitted}
    assert "rt" in admitted
    assert len(admitted) == 2
    # Only one BATCH may join REALTIME under reserve
    assert len(admitted & {"b1", "b2"}) == 1


def test_resource_scheduler_snapshot():
    arb = MissionArbiter(global_max_concurrent=2)
    sched = ResourceScheduler(arb)
    snap = sched.snapshot()
    assert snap["scheduler_version"].startswith("ro5")
    assert snap["realtime_reserve_slots"] == 1
