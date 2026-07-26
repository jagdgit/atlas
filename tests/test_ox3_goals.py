"""OX.3 — durable Goals (objectives first)."""

from __future__ import annotations

from atlas.goals import GoalService
from atlas.planner.planner import Intent, Planner
from atlas.repositories.goal_repo import InMemoryGoalRepository
from atlas.services.assistant_service import AssistantService


def test_create_goal_objective_first():
    svc = GoalService(InMemoryGoalRepository())
    goal = svc.create(
        "Beat NIFTY over 12 months",
        success_criteria="Outperform NIFTY50 total return over 12 months",
    )
    assert goal["title"] == "Beat NIFTY over 12 months"
    assert goal["status"] == "active"
    assert goal["program_id"] is None
    assert goal["portfolio_key"] is None
    assert goal["objective"]["text"] == "Beat NIFTY over 12 months"
    assert "NIFTY" in (goal["success_criteria"] or {}).get("text", "")


def test_link_program_and_portfolio_optional():
    svc = GoalService(InMemoryGoalRepository())
    goal = svc.create("Learn Options")
    linked = svc.link(
        goal["id"],
        program_id="market_intelligence",
        portfolio_key="fo_demo",
    )
    assert linked["program_id"] == "market_intelligence"
    assert linked["portfolio_key"] == "fo_demo"
    assert linked["title"] == "Learn Options"


def test_search_resolves_by_objective_not_portfolio_name():
    svc = GoalService(InMemoryGoalRepository())
    svc.create(
        "Beat NIFTY over 12 months",
        portfolio_key="long_term",
    )
    svc.create(
        "Learn Options",
        portfolio_key="fo_demo",
    )
    hit = svc.resolve("how is my beat-NIFTY goal?")
    assert hit is not None
    assert "NIFTY" in hit["title"]
    assert hit["portfolio_key"] == "long_term"


def test_ensure_for_learner_reuses_active():
    svc = GoalService(InMemoryGoalRepository())
    a = svc.ensure_for_learner(objective_text="start India learner", capital=10000)
    b = svc.ensure_for_learner(objective_text="start India learner now", capital=10000)
    assert a["id"] == b["id"]
    assert a["portfolio_key"] == "india_equity_learner"
    assert a["program_id"] == "market_intelligence"


def test_planner_routes_goal_create_and_status():
    plan = Planner().plan("my goal is Beat NIFTY over 12 months")
    assert plan.intent == Intent.MANAGE_GOAL
    assert plan.steps[0].args["action"] == "create"
    assert "NIFTY" in plan.steps[0].args["title"]

    plan2 = Planner().plan("how is my beat nifty goal?")
    assert plan2.intent == Intent.MANAGE_GOAL
    assert plan2.steps[0].args["action"] == "progress"

    plan3 = Planner().plan("list goals")
    assert plan3.intent == Intent.MANAGE_GOAL
    assert plan3.steps[0].args["action"] == "list"


def test_assistant_manage_goal_create_and_status():
    svc = GoalService(InMemoryGoalRepository())
    asst = AssistantService.__new__(AssistantService)
    asst._goals = svc
    asst._logger = __import__("logging").getLogger("test")

    tool_calls: list = []
    out = asst._do_manage_goal(
        {"action": "create", "title": "Become a profitable investor", "query": ""},
        context=None,
        tool_calls=tool_calls,
    )
    assert "Goal recorded" in out.answer
    assert tool_calls[0]["action"] == "create"

    tool_calls.clear()
    out2 = asst._do_manage_goal(
        {"action": "status", "query": "profitable investor", "title": "profitable"},
        context=None,
        tool_calls=tool_calls,
    )
    assert "Become a profitable investor" in out2.answer
    assert "program=" in out2.answer or "Links:" in out2.answer
