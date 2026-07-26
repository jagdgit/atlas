"""IL.1 / IL.2 / OX.1 — Investment Universe + India learner intent."""

from __future__ import annotations

from atlas.investment.universe import NIFTY50, as_instruments, membership, sectors, symbols
from atlas.investment.watchlists import clear, instruments_for, publish
from atlas.missions.programs import get_program, india_equity_learner_overrides
from atlas.planner.planner import Intent, Planner
from atlas.workers.investment_universe import InvestmentUniverseWorker, auto_instruments
from atlas.workers.base import TickContext


def test_nifty50_has_fifty_constituents():
    assert len(NIFTY50) == 50
    assert all(r["symbol"].endswith(".NS") for r in NIFTY50)
    assert "RELIANCE.NS" in symbols()
    secs = sectors()
    assert "Financial Services" in secs or "Information Technology" in secs


def test_membership_unknown_index_raises():
    try:
        membership("DOW30")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_watchlist_publish_and_instruments_for():
    clear()
    publish(
        program_id="market_intelligence",
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS"}],
        ranked=[
            {"symbol": "TCS.NS", "rank": 1},
            {"symbol": "INFY.NS", "rank": 2},
        ],
    )
    inst = instruments_for("market_intelligence", max_n=1)
    assert inst == [{"symbol": "TCS.NS", "asset": ""}]


def test_auto_instruments_falls_back_to_nifty():
    clear()
    inst = auto_instruments(max_n=5)
    assert len(inst) == 5
    assert inst[0]["symbol"].endswith(".NS")


def test_investment_universe_worker_tick():
    clear()
    events = []

    class Ev:
        def emit(self, typ, payload, source=None):
            events.append((typ, payload))

    worker = InvestmentUniverseWorker(events=Ev())
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={"index": "NIFTY50", "max_watchlist": 8, "mode": "auto"},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "NIFTY50" in result.note
    assert len(result.state["watchlist_symbols"]) == 8
    assert instruments_for()[0]["symbol"] == result.state["watchlist_symbols"][0]
    assert events and events[0][0] == "InvestmentUniverseUpdated"


def test_program_lists_investment_universe_first():
    prog = get_program("market_intelligence")
    assert prog is not None
    assert prog.members[0].template == "investment_universe"


def test_india_learner_overrides_cash():
    o = india_equity_learner_overrides()
    assert o["decision_simulation"]["starting_cash"] == 10000.0
    assert o["decision_simulation"]["instruments"] == []
    assert o["investment_universe"]["index"] == "NIFTY50"


def test_planner_routes_india_learner():
    plan = Planner().plan("start India learner with 10000")
    assert plan.intent == Intent.START_INVESTMENT_LEARNER
    assert plan.steps[0].args["preset"] == "india_equity_learner"
    assert plan.steps[0].args["capital"] == 10000.0
    # OX.2 — Chat default is preview (no activate)
    assert plan.steps[0].args.get("activate") is False


def test_paper_trading_auto_loads_when_instruments_empty():
    from atlas.workers.paper_trading import PaperTradingWorker

    clear()
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "RELIANCE.NS"}],
        ranked=[{"symbol": "RELIANCE.NS", "rank": 1}],
    )

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            return {"id": "p1", "cash": 10000}

        def snapshot(self, portfolio_id, prices=None):
            return {
                "equity": 10000,
                "cash": 10000,
                "positions": [],
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            }

    class FakeEngine:
        def decide(self, *a, **k):
            raise AssertionError("should not decide without bars")

    class FakeLive:
        def bars_for(self, symbol, **kwargs):
            return {"outcome": "empty", "bars": [], "reason": "hermetic"}

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=FakeEngine(),
        portfolio=FakePortfolio(),
        live_market=FakeLive(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={
                "instruments": [],
                "feed_mode": "live",
                "starting_cash": 10000,
                "respect_market_hours": False,
                "market_session": "always_open",
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("auto_instruments") is True
    assert "RELIANCE.NS" in (result.state.get("auto_symbols") or [])
    assert "auto universe" in (result.note or "")
