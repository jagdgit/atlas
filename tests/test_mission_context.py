"""Mission Context API (MCA.1)."""

from __future__ import annotations

from atlas.missions.context import MissionContextService
from atlas.missions.programs import ProgramService
from atlas.trading.strategy import StrategyDecisionRule
from atlas.decision.contracts import DecisionRequest
from atlas.decision.context import IntelligenceContext
from atlas.world_models import default_world_model_registry


def test_gather_includes_world_and_experience():
    class _Learning:
        def advice_for(self, query, *, limit=3):
            return {"advice": "Lesson: re-check risk before buys", "count": 1}

    class _Knowledge:
        def retrieve(self, *a, **k):
            return []

        def list_findings(self, *, limit=50, domain=None, include_archive=False):
            return [
                {
                    "id": "f1",
                    "statement": "NSE equity session closes at 15:30",
                    "claim_type": "fact",
                    "domain": "markets",
                    "quality": {"trust": "medium"},
                }
            ]

    svc = MissionContextService(
        knowledge=_Knowledge(),
        world_models=default_world_model_registry(),
        learning=_Learning(),
    )
    out = svc.gather("NSE settlement", program_id="market", limit=12)
    assert out["version"] == "mca.1.1"
    assert "world_models" in out["sources"] or any(
        i.get("item_kind") == "world_fact" for i in out["items"]
    )
    assert any(i.get("item_kind") == "experience_advice" for i in out["items"])
    assert out["citations"]
    assert out["summary"]


def test_program_service_delegates():
    class _Ctx:
        def gather(self, topic, *, program_id=None, limit=12):
            return {"topic": topic, "version": "mca.1", "items": [], "delegated": True}

    svc = ProgramService(mission_context=_Ctx())
    out = svc.context("x", program_id="market")
    assert out.get("delegated") is True


def test_strategy_cites_mission_context():
    rule = StrategyDecisionRule()
    ctx = IntelligenceContext()
    base = {
        "symbol": "DEMO",
        "price": 100.0,
        "position_qty": 0,
        "equity": 10_000,
        "cash": 10_000,
        "trade_fraction": 0.1,
        "indicators": {
            "sma_fast": 110.0,
            "sma_slow": 100.0,
            "rsi": 40.0,
            "params": {"sma_fast": 10, "sma_slow": 30},
            "bars": 40,
        },
        "mission_context_summary": "context[world_models]: WM NSE",
        "mission_context_citations": ["wm:ex.nse"],
    }
    opts = rule.score(
        DecisionRequest(mission_id="m", mission_type="paper_trading", context=base),
        ctx,
    )
    buy = next(o for o in opts if o.key.startswith("buy:"))
    assert "ctx" in buy.rationale
    assert "wm:ex.nse" in (buy.knowledge_refs or [])
