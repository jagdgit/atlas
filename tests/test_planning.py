"""Planning OS (PA.1 / OI-PA-PLAN)."""

from __future__ import annotations

from atlas.planning import PlanningService
from atlas.missions.context import MissionContextService
from atlas.world_models import default_world_model_registry


def test_plan_market_buy_recommends_simulate():
    svc = PlanningService(
        mission_context=MissionContextService(
            world_models=default_world_model_registry()
        )
    )
    out = svc.plan("Should I buy RELIANCE.NS on NSE?", program_id="market")
    assert out["version"] == "pa.1"
    assert out["gaps"]
    assert out["alternatives"]
    assert any(a["id"] == "simulate" for a in out["alternatives"])
    assert out["decision"]["side_effecting"] is False
    assert "P10" in out["decision"]["p10"] or "simulat" in out["decision"]["action"]


def test_plan_empty_goal():
    svc = PlanningService()
    out = svc.plan("")
    assert out["decision"]["action"] == "hold"


def test_plan_uses_context_citations():
    class _Ctx:
        def gather(self, topic, *, program_id=None, limit=12):
            return {
                "items": [
                    {
                        "item_kind": "world_fact",
                        "id": "ex.nse",
                        "label": "NSE",
                        "kind": "exchange",
                    }
                ],
                "summary": "context[world_models]: WM NSE",
                "citations": ["wm:ex.nse"],
                "sources": ["world_models"],
            }

    svc = PlanningService(mission_context=_Ctx())
    out = svc.plan("NSE session hours", program_id="market")
    assert "wm:ex.nse" in out["context_citations"]
    assert out["context_summary"]


def test_event_research_attaches_planning():
    from atlas.trading.interesting_events import InterestingEvent
    from atlas.workers.event_research import EventResearchWorker

    created: list[str] = []
    emitted: list[dict] = []

    class _Jobs:
        def create_job(self, objective):
            created.append(objective)
            return {"job": {"id": "j1"}}

    class _Events:
        def emit(self, name, payload, source=None):
            emitted.append({"name": name, **payload})

    class _Planning:
        def plan(self, goal, *, program_id=None, limit=12):
            return {"decision": {"action": "research_event", "why": "fill gaps"}}

    worker = EventResearchWorker(
        jobs=_Jobs(), events=_Events(), planning=_Planning()
    )
    ev = InterestingEvent(
        symbol="DEMO",
        kind="move",
        score=0.9,
        detail="big move",
    )
    assert worker._spawn(ev, mission_id="m")
    assert created
    assert emitted[0].get("planning_action") == "research_event"
