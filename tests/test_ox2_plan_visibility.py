"""OX.2 — Program start plan visibility (preview / now / API)."""

from __future__ import annotations

from atlas.planner.planner import Intent, Planner
from atlas.planning.service import PlanningService
from atlas.services.assistant_service import AssistantService


class _FakePrograms:
    def __init__(self) -> None:
        self.starts: list[dict] = []
        self.previews: list[dict] = []

    def preview_start(self, program_id, **kwargs):
        self.previews.append({"program_id": program_id, **kwargs})
        return {
            "started": [
                {"template": "investment_universe", "role": "Investment Universe", "would_start": True}
            ],
            "skipped": [],
            "dry_run": True,
            "side_effecting": False,
        }

    def start(self, program_id, **kwargs):
        self.starts.append({"program_id": program_id, **kwargs})
        return {
            "started": [
                {"template": "investment_universe", "role": "Investment Universe", "mission_id": "m1"}
            ],
            "skipped": [],
            "dry_run": False,
        }


def test_plan_program_start_has_m0_to_m7():
    plan = PlanningService().plan_program_start(capital=10000, universe="NIFTY50")
    assert plan["kind"] == "program_start_plan"
    assert plan["interaction"] == "preview"
    assert plan["side_effecting"] is False
    templates = [s["template"] for s in plan["steps"]]
    assert templates[0] == "investment_universe"
    assert "decision_simulation" in templates
    assert "investment_mentor" in templates
    assert len(plan["steps"]) == 8


def test_planner_preview_by_default():
    plan = Planner().plan("start India learner with 10000")
    assert plan.intent == Intent.START_INVESTMENT_LEARNER
    args = plan.steps[0].args
    assert args["activate"] is False
    assert args["preview"] is True
    assert args["capital"] == 10000.0


def test_planner_now_activates():
    plan = Planner().plan("start India learner now with 25000")
    args = plan.steps[0].args
    assert args["activate"] is True
    assert args["preview"] is False
    assert args["capital"] == 25000.0


def test_planner_confirm_activates():
    plan = Planner().plan("confirm India learner")
    assert plan.intent == Intent.START_INVESTMENT_LEARNER
    assert plan.steps[0].args["activate"] is True


def test_assistant_preview_does_not_start():
    programs = _FakePrograms()
    # Minimal stub conversation/planner path via direct handler call
    asst = AssistantService.__new__(AssistantService)
    asst._programs = programs
    asst._planning = PlanningService()
    asst._goals = None
    asst._logger = __import__("logging").getLogger("test")

    tool_calls: list = []
    out = asst._do_start_investment_learner(
        {
            "program": "market_intelligence",
            "preset": "india_equity_learner",
            "capital": 10000,
            "universe": "NIFTY50",
            "activate": False,
            "preview": True,
        },
        context=None,
        tool_calls=tool_calls,
    )
    assert programs.starts == []
    assert programs.previews
    assert "Proposed plan" in out.answer
    assert "confirm" in out.answer.lower()
    assert tool_calls[0]["action"] == "preview_program"
    assert out.extras.get("activate") is False


def test_assistant_activate_starts():
    programs = _FakePrograms()
    asst = AssistantService.__new__(AssistantService)
    asst._programs = programs
    asst._planning = PlanningService()
    asst._goals = None
    asst._logger = __import__("logging").getLogger("test")

    tool_calls: list = []
    out = asst._do_start_investment_learner(
        {
            "program": "market_intelligence",
            "preset": "india_equity_learner",
            "capital": 10000,
            "universe": "NIFTY50",
            "activate": True,
            "preview": False,
        },
        context=None,
        tool_calls=tool_calls,
    )
    assert len(programs.starts) == 1
    assert "Started Market Intelligence" in out.answer
    assert tool_calls[0]["action"] == "start_program"
