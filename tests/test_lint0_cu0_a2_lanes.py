"""OI-CU0 A2 — lane priority / bounded concurrency (no blind concurrency raise)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.core.resources.manager import ResourceManager
from atlas.investment.llm_lanes import (
    LLMLaneBusy,
    admit_llm_lane,
    in_overnight_window,
    lane_acquire_blocking,
    lane_priority,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_priority_order():
    assert lane_priority("chat") > lane_priority("market") > lane_priority("research")
    assert lane_priority("research") > lane_priority("background")
    assert lane_priority("planner") == lane_priority("chat")


def test_daytime_low_lanes_fail_fast():
    day = datetime(2026, 8, 20, 11, 0, tzinfo=_IST)
    assert lane_acquire_blocking("chat", now=day) is True
    assert lane_acquire_blocking("market", now=day) is True
    assert lane_acquire_blocking("research", now=day) is False
    assert lane_acquire_blocking("background", now=day) is False
    assert lane_acquire_blocking("researcher", now=day) is False


def test_overnight_low_lanes_still_fail_fast_when_saturated():
    """Overnight densify may *run when free*; it must not queue ahead of chat."""
    night = datetime(2026, 8, 20, 22, 0, tzinfo=_IST)
    assert in_overnight_window(night) is True
    assert lane_acquire_blocking("research", now=night) is False
    assert lane_acquire_blocking("background", now=night) is False
    dawn = datetime(2026, 8, 21, 6, 0, tzinfo=_IST)
    assert in_overnight_window(dawn) is True
    assert admit_llm_lane("research", in_use=1, limit=1, now=night)["allowed"] is False


def test_admit_when_saturated():
    day = datetime(2026, 8, 20, 12, 0, tzinfo=_IST)
    chat = admit_llm_lane("chat", in_use=1, limit=1, now=day)
    assert chat["allowed"] is True
    assert chat["reason"] == "protected_may_wait"
    res = admit_llm_lane("research", in_use=1, limit=1, now=day)
    assert res["allowed"] is False
    assert res["reason"] == "saturated_defer_low_lane"


def test_resource_manager_defers_daytime_research():
    rm = ResourceManager(llm_max_concurrency=1)
    with rm.llm_lane(kind="chat"):
        with pytest.raises(LLMLaneBusy):
            with rm.llm_lane(kind="researcher"):
                pass
    cap = rm.llm_capacity
    assert cap["limit"] == 1
    assert "Bounded concurrency" in str(cap.get("honesty") or "")


def test_resource_manager_chat_waits_after_research_releases():
    rm = ResourceManager(llm_max_concurrency=1)
    # Free path: research may acquire when empty
    with rm.llm_lane(kind="researcher"):
        assert rm.llm_capacity["in_use"] == 1
        assert rm.llm_capacity["holders"].get("research") == 1
    with rm.llm_lane(kind="chat"):
        assert rm.llm_capacity["holders"].get("chat") == 1
