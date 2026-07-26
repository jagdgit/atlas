"""IR-RO4 / IR-RO8 / IR-RO10 — dynamic budgets, machine profile, should-run-now."""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand
from atlas.core.resources.dynamic_budgets import DynamicBudgetController
from atlas.core.resources.machine_profile import detect_machine_profile
from atlas.core.resources.profiles import get_profile
from atlas.core.resources.work_admission import WorkAdmissionPolicy
from atlas.core.resources.work_profile import SERVICE_BATCH, SERVICE_NORMAL, SERVICE_REALTIME


class _FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def test_profiles_declare_preferred_tick_slots():
    assert get_profile("conservative").preferred_tick_slots == 2
    assert get_profile("balanced").preferred_tick_slots == 3
    assert get_profile("maximum").preferred_tick_slots == 4


def test_dynamic_budget_shrinks_under_pressure_and_respects_hard():
    pressure = {"on": False}

    def probe():
        return pressure["on"], "synthetic"

    ctrl = DynamicBudgetController(
        hard_tick_ceiling=4,
        profile="maximum",
        pressure_fn=probe,
        release_after_seconds=10_000,
    )
    assert ctrl.preferred_ticks() == 4
    assert ctrl.effective_tick_slots() == 4

    pressure["on"] = True
    assert ctrl.effective_tick_slots() == 2  # half of preferred, floor 1

    # Hard ceiling always wins over preferred.
    ctrl2 = DynamicBudgetController(
        hard_tick_ceiling=2,
        profile="maximum",
        pressure_fn=lambda: (False, ""),
    )
    assert ctrl2.preferred_ticks() == 2
    assert ctrl2.effective_tick_slots() == 2


def test_arbiter_uses_effective_capacity_from_budget_controller():
    pressure = {"on": True}
    ctrl = DynamicBudgetController(
        hard_tick_ceiling=2,
        profile="conservative",
        pressure_fn=lambda: (pressure["on"], "hot"),
        release_after_seconds=10_000,
    )
    arb = MissionArbiter(global_max_concurrent=2, budget_controller=ctrl)
    # Under pressure preferred=2 → effective=1 (REALTIME reserve yields so the slot is usable)
    assert arb.try_admit(MissionDemand(mission_id="a", effective_priority=1)).admitted
    v2 = arb.try_admit(MissionDemand(mission_id="b", effective_priority=1))
    assert not v2.admitted
    assert "effective capacity" in v2.reason or "global capacity" in v2.reason
    snap = arb.snapshot()
    assert snap["global_max"] == 2
    assert snap["effective_global_max"] == 1


def test_realtime_reserve_yields_when_effective_slots_is_one():
    ctrl = DynamicBudgetController(
        hard_tick_ceiling=2,
        profile="conservative",
        pressure_fn=lambda: (True, "hot"),
        release_after_seconds=10_000,
    )
    arb = MissionArbiter(global_max_concurrent=2, budget_controller=ctrl)
    assert arb._effective_realtime_reserve() == 0  # noqa: SLF001


def test_machine_profile_16gb_suggests_conservative():
    # 16 GiB in KB
    sug = detect_machine_profile(
        hard_tick_ceiling=2,
        mem_total_kb=16 * 1024 * 1024,
        cpu_count=20,
    )
    assert sug.suggested_profile == "conservative"
    assert sug.preferred_tick_slots == 2


def test_work_admission_batch_window_opt_in():
    # 14:00 UTC — outside 22→06 window
    clock = _FixedClock(datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc))
    off = WorkAdmissionPolicy(enforce_batch_window=False, clock=clock)
    assert off.should_run_now(service_class=SERVICE_BATCH).allowed

    on = WorkAdmissionPolicy(enforce_batch_window=True, clock=clock)
    denied = on.should_run_now(service_class=SERVICE_BATCH)
    assert not denied.allowed
    assert "batch_outside" in denied.reason
    assert denied.run_at_hint

    # REALTIME / NORMAL always allowed
    assert on.should_run_now(service_class=SERVICE_REALTIME).allowed
    assert on.should_run_now(service_class=SERVICE_NORMAL).allowed

    night = WorkAdmissionPolicy(
        enforce_batch_window=True,
        clock=_FixedClock(datetime(2026, 7, 22, 23, 0, tzinfo=timezone.utc)),
    )
    assert night.should_run_now(service_class=SERVICE_BATCH).allowed
