"""Scheduler hierarchy Program→Mission→Worker (SCHED.1)."""

from __future__ import annotations

from atlas.scheduler.hierarchy import (
    PROGRAM_DEFAULT_INTERVAL,
    SchedulerHierarchyService,
    cadence_to_seconds,
)


def test_cadence_to_seconds():
    assert cadence_to_seconds("hourly") == 3600
    assert cadence_to_seconds("weekly") == 604800
    assert cadence_to_seconds("continuous") == 300
    assert cadence_to_seconds("on trigger") == 3600
    assert cadence_to_seconds("900") == 900


def test_resolve_cascade_worker_wins():
    svc = SchedulerHierarchyService()
    out = svc.resolve_interval(
        program_id="market",
        template="news_intelligence",
        cadence="hourly",
        worker_interval=120,
    )
    assert out["interval_seconds"] == 120
    assert out["source"] == "worker"
    assert out["version"] == "sched.1"


def test_resolve_mission_cadence():
    svc = SchedulerHierarchyService()
    out = svc.resolve_interval(
        program_id="market_intelligence",
        template="news_intelligence",
    )
    assert out["interval_seconds"] == 3600
    assert out["source"] == "mission"


def test_view_market_program():
    svc = SchedulerHierarchyService()
    view = svc.view("market")  # alias
    assert view["programs"]
    prog = view["programs"][0]
    assert prog["id"] == "market_intelligence"
    templates = {m["template"] for m in prog["members"]}
    assert "market_observer" in templates
    assert "investment_mentor" in templates
    assert prog["default_interval_seconds"] == PROGRAM_DEFAULT_INTERVAL


def test_suggest_for_template():
    svc = SchedulerHierarchyService()
    sug = svc.suggest_for_template("investment_mentor")
    assert sug["interval_seconds"] == 604800  # weekly
