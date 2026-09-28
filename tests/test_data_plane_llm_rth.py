"""DP-LLM1 RTH reserve + DP-LLM2 scientist daily cap."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.core.resources.manager import ResourceManager
from atlas.investment.llm_lanes import (
    LLMLaneBusy,
    admit_llm_lane,
    rth_reserved_slots,
)
from atlas.investment.incumbent_scientist import (
    drain_pending_scientist_notes,
    record_scientist_llm_attempt,
    scientist_llm_attempts_today,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_rth_reserve_blocks_second_research_slot(monkeypatch):
    day = datetime(2026, 8, 24, 11, 0, tzinfo=_IST)
    monkeypatch.setattr(
        "atlas.investment.llm_lanes.in_nse_rth", lambda now=None: True
    )
    assert rth_reserved_slots(2, now=day) == 1
    # One research already in use → no second low-lane slot during RTH
    denied = admit_llm_lane(
        "research", in_use=1, limit=2, now=day, low_lane_in_use=1
    )
    assert denied["allowed"] is False
    assert denied["reason"] == "rth_reserve_for_live"
    # Chat still allowed (may wait)
    chat = admit_llm_lane("chat", in_use=1, limit=2, now=day, low_lane_in_use=1)
    assert chat["allowed"] is True


def test_off_hours_research_can_use_both_slots(monkeypatch):
    night = datetime(2026, 8, 24, 20, 0, tzinfo=_IST)
    monkeypatch.setattr(
        "atlas.investment.llm_lanes.in_nse_rth", lambda now=None: False
    )
    assert rth_reserved_slots(2, now=night) == 0
    ok = admit_llm_lane(
        "research", in_use=1, limit=2, now=night, low_lane_in_use=1
    )
    assert ok["allowed"] is True
    assert ok["reason"] == "capacity_available"


def test_resource_manager_rth_reserve(monkeypatch):
    monkeypatch.setattr(
        "atlas.investment.llm_lanes.in_nse_rth", lambda now=None: True
    )
    rm = ResourceManager(llm_max_concurrency=2)
    with rm.llm_lane(kind="researcher"):
        with pytest.raises(LLMLaneBusy):
            with rm.llm_lane(kind="scientist"):
                pass
        # Protected lane may still acquire (waits / uses reserved)
        with rm.llm_lane(kind="chat"):
            assert rm.llm_capacity["in_use"] == 2


def test_scientist_daily_cap(tmp_path):
    lab = "india_equity_learner"
    for _ in range(12):
        record_scientist_llm_attempt(tmp_path, laboratory_id=lab)
    assert scientist_llm_attempts_today(tmp_path, laboratory_id=lab) == 12
    out = drain_pending_scientist_notes(
        tmp_path,
        laboratory_id=lab,
        llm=None,
        cfg={"icr5_daily_llm_cap": 12},
    )
    assert out.get("reason") == "daily_llm_cap"
    assert out.get("done") == 0
