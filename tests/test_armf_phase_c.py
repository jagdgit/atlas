"""ARMF Phase C — program capacity shares + arbiter floors."""

from __future__ import annotations

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand
from atlas.core.resources.capacity_shares import (
    ProgramCapacityPolicy,
    policy_from_config,
)


def test_market_floor_at_least_one_on_eff_4():
    pol = ProgramCapacityPolicy()
    assert pol.floor_slots("market_intelligence", 4) >= 1
    assert pol.floor_slots("engineering_intelligence", 4) >= 1


def test_nse_rth_raises_market_floor_for_paper_labs():
    pol = ProgramCapacityPolicy()
    assert pol.floor_slots("market_intelligence", 4) == 1
    assert pol.floor_slots("market_intelligence", 4, nse_rth=True) == 3
    # Claiming own RTH floor is never blocked (equity + intraday + FNO).
    assert (
        pol.blocks_admit(
            admit_program="market_intelligence",
            effective_slots=4,
            total_inflight=2,
            program_inflight={"market_intelligence": 2},
            programs_with_demand={
                "market_intelligence",
                "engineering_intelligence",
                "personal_intelligence",
            },
            nse_rth=True,
        )
        is None
    )


def test_idle_eng_share_is_borrowable():
    pol = ProgramCapacityPolicy()
    reserved = pol.reserved_for_others(
        admit_program="market_intelligence",
        effective_slots=4,
        program_inflight={},
        programs_with_demand={"market_intelligence"},
    )
    assert reserved == 0


def test_blocks_when_would_steal_market_floor():
    pol = ProgramCapacityPolicy()
    # Eng already at its floor; last free slot must stay for Market demand.
    reason = pol.blocks_admit(
        admit_program="engineering_intelligence",
        effective_slots=2,
        total_inflight=1,
        program_inflight={"engineering_intelligence": 1},
        programs_with_demand={"market_intelligence", "engineering_intelligence"},
    )
    assert reason is not None
    assert "program_floor" in reason


def test_market_claiming_own_floor_never_blocked_by_policy():
    pol = ProgramCapacityPolicy()
    reason = pol.blocks_admit(
        admit_program="market_intelligence",
        effective_slots=2,
        total_inflight=1,
        program_inflight={},
        programs_with_demand={"market_intelligence", "engineering_intelligence"},
    )
    assert reason is None


def test_arbiter_reserves_market_floor():
    pol = ProgramCapacityPolicy()
    arb = MissionArbiter(
        global_max_concurrent=2,
        capacity_policy=pol,
        llm_max_slots=1,
        realtime_reserve_slots=0,
    )
    eng = MissionDemand(
        mission_id="eng1",
        effective_priority=50,
        program_id="engineering_intelligence",
        max_concurrent_tasks=1,
    )
    assert arb.try_admit(eng).admitted is True
    market_probe = MissionDemand(
        mission_id="mkt1",
        effective_priority=10,
        program_id="market_intelligence",
        max_concurrent_tasks=1,
        service_class="REALTIME",
    )
    assert arb.try_admit(market_probe).admitted is True
    arb.release(market_probe.mission_id, program_id="market_intelligence")
    eng2 = MissionDemand(
        mission_id="eng2",
        effective_priority=90,
        program_id="engineering_intelligence",
        max_concurrent_tasks=1,
    )
    v2 = arb.try_admit(eng2)
    assert v2.admitted is False
    assert "program_floor" in v2.reason


def test_llm_slot_blocks_heavy_not_non_llm():
    arb = MissionArbiter(global_max_concurrent=4, llm_max_slots=1, realtime_reserve_slots=0)
    heavy = MissionDemand(
        mission_id="llm1",
        program_id="market_intelligence",
        uses_llm=True,
        llm_weight=1,
        max_concurrent_tasks=1,
    )
    light = MissionDemand(
        mission_id="obs1",
        program_id="market_intelligence",
        uses_llm=False,
        llm_weight=0,
        service_class="REALTIME",
        max_concurrent_tasks=1,
    )
    assert arb.try_admit(heavy).admitted is True
    assert arb.try_admit(
        MissionDemand(
            mission_id="llm2",
            program_id="engineering_intelligence",
            uses_llm=True,
            llm_weight=1,
            max_concurrent_tasks=1,
        )
    ).admitted is False
    assert arb.try_admit(light).admitted is True


def test_policy_from_config_disabled():
    pol = policy_from_config({"enabled": False})
    assert pol.enabled is False
    assert (
        pol.blocks_admit(
            admit_program="engineering_intelligence",
            effective_slots=2,
            total_inflight=1,
            program_inflight={},
            programs_with_demand={"market_intelligence"},
        )
        is None
    )
