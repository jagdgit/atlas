"""ARMF Phase A — program health + capacity idle signal."""

from __future__ import annotations

from atlas.ops.program_health import (
    STATUS_AT_RISK,
    STATUS_CONGESTED,
    STATUS_HEALTHY,
    STATUS_IDLE,
    capacity_idle_signal,
    summarize_program_health,
)
from atlas.ops.worker_states import STATE_STARVED, STATE_WAITING_HOST


def test_capacity_idle_when_waiting_and_no_ticks():
    sig = capacity_idle_signal(
        tick_inflight=0,
        waiting_host_missions=3,
        waiting_host_workers=1,
        host_deferring=True,
    )
    assert sig["active"] is True
    assert "not off" in sig["message"].lower()


def test_capacity_idle_inactive_when_ticking():
    sig = capacity_idle_signal(tick_inflight=1, waiting_host_missions=5)
    assert sig["active"] is False
    assert sig["message"] == ""


def test_program_health_at_risk_on_starved():
    rows = [
        {
            "type": "investment_universe",
            "ops_state": STATE_STARVED,
            "owner": {"program": "market_intelligence"},
            "service_class": "background",
        },
        {
            "type": "hello_watcher",
            "ops_state": STATE_STARVED,
            "owner": {},
            "service_class": "background",
        },
    ]
    out = summarize_program_health(rows, [], hide_types=frozenset({"hello_watcher"}))
    market = next(p for p in out["programs"] if p["program"] == "market_intelligence")
    assert market["status"] == STATUS_AT_RISK
    assert market["starved"] == 1
    # hello_watcher excluded from unassigned pressure
    unassigned = [p for p in out["programs"] if p["program"] == "unassigned"]
    assert not unassigned or unassigned[0]["starved"] == 0


def test_program_health_archive_congested():
    items = [
        {
            "state": "WAITING_HOST",
            "reason": "archive_slots",
            "owner": {"program": "market_intelligence"},
            "service_class": "archive",
        }
    ]
    out = summarize_program_health(
        [],
        items,
        host_guard={"archive_workers_running": 1, "max_archive_workers": 1},
    )
    archive = next(p for p in out["programs"] if p["program"] == "archive")
    assert archive["status"] == STATUS_CONGESTED


def test_program_health_core_programs_always_present():
    out = summarize_program_health([], [])
    ids = {p["program"] for p in out["programs"]}
    assert "market_intelligence" in ids
    assert "engineering_intelligence" in ids
    assert "personal_intelligence" in ids
    assert "archive" in ids
    market = next(p for p in out["programs"] if p["program"] == "market_intelligence")
    assert market["status"] in {STATUS_IDLE, STATUS_HEALTHY, "quiet"}


def test_waiting_host_workers_count():
    rows = [
        {
            "type": "research",
            "ops_state": STATE_WAITING_HOST,
            "owner": {"program": "engineering_intelligence"},
        }
    ]
    out = summarize_program_health(rows, [])
    eng = next(p for p in out["programs"] if p["program"] == "engineering_intelligence")
    assert eng["waiting_host"] == 1
