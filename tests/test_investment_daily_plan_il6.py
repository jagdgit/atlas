"""IL.6 — Daily Investment Plan (hermetic)."""

from __future__ import annotations

from atlas.goals.progress import build_progress_report
from atlas.investment.daily_plan import build_daily_plan, plan_from_watchlist
from atlas.investment.watchlists import clear, publish
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.planning.service import PlanningService
from atlas.workers.base import TickContext
from atlas.workers.investment_universe import InvestmentUniverseWorker


def test_build_daily_plan_sizes_and_cold_start():
    ranked = [
        {
            "symbol": "INFY.NS",
            "name": "Infosys",
            "rank": 1,
            "score": 0.9,
            "reason": "+ Momentum; + Positive quality proxy",
            "phase": "learning",
            "confidence": "very_low",
        },
        {
            "symbol": "TCS.NS",
            "name": "TCS",
            "rank": 2,
            "score": 0.8,
            "reason": "+ Momentum",
            "phase": "learning",
            "confidence": "very_low",
        },
        {
            "symbol": "WEAK.NS",
            "name": "Weak",
            "rank": 11,
            "score": 0.2,
            "reason": "− Weak quality proxy",
            "explanations": [{"sign": "-", "text": "Weak quality proxy", "component": "quality"}],
        },
    ]
    plan = build_daily_plan(
        ranked,
        capital=10000,
        max_candidates=2,
        deploy_fraction=0.4,
        portfolio_key="india_equity_learner",
    )
    assert plan["kind"] == "daily_investment_plan"
    assert plan["version"] == "il.6"
    assert plan["phase"] == "learning"
    assert len(plan["candidates"]) == 2
    assert plan["candidates"][0]["symbol"] == "INFY.NS"
    total = sum(c["suggested_notional"] for c in plan["candidates"])
    assert abs(total - 4000.0) < 0.05  # 40% of 10k
    assert any("provisional" in n.lower() or "cold" in n.lower() for n in plan["notes"])
    assert plan["avoids"]
    assert "INFY.NS" in plan["summary"]


def test_plan_from_empty_watchlist():
    plan = plan_from_watchlist(None, capital=5000)
    assert plan["candidates"] == []
    assert "No ranked" in plan["notes"][ -1] or "watchlist" in plan["summary"].lower()


def test_planning_service_plan_daily_investment():
    clear()
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "RELIANCE.NS"}],
        ranked=[
            {
                "symbol": "RELIANCE.NS",
                "rank": 1,
                "score": 0.7,
                "reason": "+ Liquidity",
                "phase": "active",
                "confidence": "medium",
            }
        ],
        extra={"phase": "active", "confidence": "medium"},
    )
    svc = PlanningService()
    plan = svc.plan_daily_investment(capital=10000, portfolio_key="india_equity_learner")
    assert plan["kind"] == "daily_investment_plan"
    assert plan["candidates"][0]["symbol"] == "RELIANCE.NS"
    assert plan["api"]["self"].endswith("daily-investment-plan")


def test_m0_publishes_daily_plan_in_extra():
    clear()
    worker = InvestmentUniverseWorker()
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m0",
            config={"index": "NIFTY50", "max_watchlist": 5, "starting_cash": 10000},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("daily_plan_summary")
    from atlas.investment.watchlists import latest

    snap = latest()
    assert snap and isinstance(snap.get("extra", {}).get("daily_plan"), dict)
    assert snap["extra"]["daily_plan"]["kind"] == "daily_investment_plan"
    assert "plan=" in (result.note or "")


def test_progress_includes_today_plan_bullet():
    report = build_progress_report(
        {
            "title": "Wealth",
            "status": "active",
            "objective": {"text": "Beat NIFTY"},
            "program_id": "market_intelligence",
            "portfolio_key": "india_equity_learner",
        },
        watchlist={
            "ranked": [{"symbol": "INFY.NS", "rank": 1, "reason": "+ Momentum", "phase": "active"}],
            "extra": {
                "phase": "active",
                "confidence": "medium",
                "daily_plan": {
                    "summary": "Today: 1 candidate(s) [INFY.NS] from ₹10,000 book; 0 avoid(s).",
                    "candidates": [{"symbol": "INFY.NS", "suggested_notional": 4000}],
                },
            },
        },
    )
    assert any("Today's plan:" in b for b in report["bullets"])
    assert report["progress"].get("daily_plan")


def test_m0_template_has_morning_cron():
    iu = next(t for t in BUILTIN_TEMPLATES if t["name"] == "investment_universe")
    specs = iu["worker_specs"]
    assert len(specs) >= 2
    crons = [s.get("cron") or s.get("cron_expr") for s in specs]
    assert "15 3 * * 1-5" in crons
