"""IL.9 — India learner operator happy path."""

from __future__ import annotations

from atlas.goals import GoalService
from atlas.investment.happy_path import happy_path_guide, happy_path_status
from atlas.investment.watchlists import clear as clear_wl
from atlas.investment.watchlists import publish
from atlas.missions.programs import india_equity_learner_overrides
from atlas.planning.service import PlanningService
from atlas.repositories.goal_repo import InMemoryGoalRepository


def test_happy_path_guide_has_start_surfaces():
    guide = happy_path_guide()
    assert guide["preset"] == "india_equity_learner"
    assert "start India learner" in guide["start"]["beginner_chat"]
    assert guide["defaults"]["instruments"].startswith("empty")
    assert any(c["id"] == "p10" for c in guide["checklist"])
    ov = india_equity_learner_overrides()
    assert ov["decision_simulation"]["instruments"] == []
    assert ov["decision_simulation"]["broker_profile"] == "zerodha"


def test_happy_path_status_next_actions():
    status = happy_path_status(goal=None, watchlist=None)
    assert status["ready"] is False
    assert any("start india learner" in a.lower() for a in status["next_actions"])


def test_happy_path_ready_when_core_present():
    clear_wl()
    from atlas.investment.watchlists import latest

    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "INFY.NS"}],
        ranked=[{"symbol": "INFY.NS", "rank": 1, "phase": "active", "confidence": "medium"}],
        extra={
            "phase": "active",
            "confidence": "medium",
            "daily_plan": {
                "summary": "Today: 1 candidate(s)",
                "candidates": [{"symbol": "INFY.NS"}],
            },
        },
    )
    status = happy_path_status(
        goal={"id": "g1", "portfolio_key": "india_equity_learner"},
        book={"portfolio_key": "india_equity_learner"},
        watchlist=latest(),
        snapshot={"equity": 10000},
        screener_count=0,
    )
    assert status["ready"] is True
    assert any(c["id"] == "daily_plan" and c["ok"] for c in status["checks"])


def test_learner_status_includes_happy_path():
    clear_wl()
    svc = GoalService(InMemoryGoalRepository())
    svc.create(
        "Become a profitable investor",
        program_id="market_intelligence",
        portfolio_key="india_equity_learner",
    )
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS"}],
        ranked=[{"symbol": "TCS.NS", "rank": 1, "phase": "learning", "confidence": "very_low"}],
        extra={"phase": "learning", "confidence": "very_low"},
    )
    report = svc.learner_status(query="india learner")
    assert "happy_path" in report
    assert report["happy_path"]["version"] == "il.9"


def test_plan_program_start_defaults_zerodha_for_india():
    plan = PlanningService().plan_program_start(preset="india_equity_learner")
    assert plan["broker_profile"] == "zerodha"
