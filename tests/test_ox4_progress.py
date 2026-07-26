"""OX.4 — Goal / learner progress narratives."""

from __future__ import annotations

from atlas.goals import GoalService, build_progress_report, format_progress_answer
from atlas.investment import portfolios as vp
from atlas.investment.watchlists import clear as clear_wl
from atlas.investment.watchlists import publish
from atlas.planner.planner import Intent, Planner
from atlas.repositories.goal_repo import InMemoryGoalRepository
from atlas.services.assistant_service import AssistantService


def test_build_progress_cold_start_honest():
    goal = {
        "id": "g1",
        "title": "Become profitable",
        "status": "active",
        "objective": {"text": "Become profitable"},
        "program_id": "market_intelligence",
        "portfolio_key": "india_equity_learner",
        "success_criteria": {"text": "Positive expectancy"},
    }
    report = build_progress_report(
        goal,
        book={
            "portfolio_key": "india_equity_learner",
            "persona": {
                "objective": "Wealth",
                "risk": "medium",
                "time_horizon": "1y",
                "capital": 10000,
            },
        },
        watchlist={
            "extra": {"phase": "learning", "confidence": "very_low"},
            "ranked": [
                {
                    "symbol": "RELIANCE.NS",
                    "rank": 1,
                    "score": 0.5,
                    "reason": "· Learning — insufficient market history yet",
                    "phase": "learning",
                    "confidence": "very_low",
                }
            ],
        },
    )
    assert report["progress"]["phase"] == "learning"
    assert "Learning" in report["narrative"] or "learning" in report["narrative"].lower()
    assert any("Cold start" in b or "Learning" in b for b in report["bullets"])
    answer = format_progress_answer(report)
    assert answer.startswith(report["narrative"])
    assert "- " in answer


def test_goal_service_progress_persists():
    clear_wl()
    vp.clear()
    svc = GoalService(InMemoryGoalRepository())
    goal = svc.create(
        "Beat NIFTY over 12 months",
        program_id="market_intelligence",
        portfolio_key="long_term",
    )
    vp.register(
        label="Long Term",
        portfolio_key="long_term",
        persona={"objective": "Wealth", "risk": "low", "capital": 25000},
    )
    publish(
        program_id="market_intelligence",
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS"}],
        ranked=[
            {
                "symbol": "TCS.NS",
                "rank": 1,
                "score": 0.84,
                "reason": "+ Strong momentum",
                "phase": "active",
                "confidence": "high",
            }
        ],
        extra={"phase": "active", "confidence": "high"},
    )
    report = svc.progress(goal["id"], persist=True)
    assert report["ok"] is True
    assert "TCS.NS" in report["answer"]
    refreshed = svc.get(goal["id"])
    assert refreshed["progress"].get("narrative")
    assert refreshed["progress"].get("phase") == "active"


def test_planner_learner_status_routes_progress():
    plan = Planner().plan("learner status")
    assert plan.intent == Intent.MANAGE_GOAL
    assert plan.steps[0].args["action"] == "progress"


def test_assistant_progress_uses_narrative():
    svc = GoalService(InMemoryGoalRepository())
    svc.ensure_for_learner(objective_text="start India learner", capital=10000)
    asst = AssistantService.__new__(AssistantService)
    asst._goals = svc
    asst._logger = __import__("logging").getLogger("test")
    tool_calls: list = []
    out = asst._do_manage_goal(
        {"action": "progress", "query": "india learner", "title": "india learner"},
        context=None,
        tool_calls=tool_calls,
    )
    assert tool_calls[0]["action"] == "progress"
    assert out.answer
    assert "Goal" in out.answer or "Toward" in out.answer or "Learning" in out.answer
