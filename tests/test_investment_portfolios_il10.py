"""IL.10 — multi-portfolio registry + persona isolation."""

from __future__ import annotations

from atlas.investment import portfolios as vp
from atlas.workers.base import TickContext
from atlas.workers.paper_trading import PaperTradingWorker


def test_normalize_persona_defaults():
    p = vp.normalize_persona({"objective": "Wealth"}, capital=25000)
    assert p["objective"] == "Wealth"
    assert p["capital"] == 25000.0
    assert p["allowed_assets"] == ["cash_equity"]
    assert p["risk"] == "medium"


def test_two_books_independent_registry():
    vp.clear()
    a = vp.register(
        label="₹10k Equity",
        portfolio_key="equity_10k",
        persona={"objective": "Wealth", "risk": "low", "time_horizon": "5y", "capital": 10000},
    )
    b = vp.register(
        label="F&O Demo",
        portfolio_key="fo_demo",
        persona={
            "objective": "Learning",
            "risk": "very_high",
            "time_horizon": "intraday",
            "capital": 50000,
            "allowed_assets": ["futures"],
        },
        asset_class="futures",
    )
    assert a["persona"]["capital"] == 10000
    assert b["persona"]["risk"] == "very_high"
    assert a["experience_scope"] == "portfolio:equity_10k"
    assert b["experience_scope"] == "portfolio:fo_demo"
    assert len(vp.list_portfolios()) == 2
    assert vp.asset_allowed(a["persona"], "cash_equity")
    assert not vp.asset_allowed(b["persona"], "cash_equity")
    assert vp.asset_allowed(b["persona"], "futures")


def test_filter_journals_isolates_books():
    journals = [
        {"tags": ["portfolio:a"], "advice": "from A"},
        {"tags": ["portfolio:b"], "advice": "from B"},
        {"tags": ["markets"], "advice": "legacy"},
        {"metadata": {"portfolio_key": "a"}, "tags": [], "advice": "meta A"},
    ]
    only_a = vp.filter_journals_for_portfolio(journals, "a")
    assert len(only_a) == 2
    assert all(
        "portfolio:a" in (j.get("tags") or []) or j.get("metadata", {}).get("portfolio_key") == "a"
        for j in only_a
    )
    only_b = vp.filter_journals_for_portfolio(journals, "b")
    assert len(only_b) == 1
    assert only_b[0]["advice"] == "from B"


def test_ensure_from_config_and_decision_overrides():
    vp.clear()
    row = vp.ensure_from_config(
        {
            "portfolio_key": "swing_25k",
            "portfolio_label": "₹25k Swing",
            "starting_cash": 25000,
            "persona": {"objective": "Growth", "risk": "high", "time_horizon": "3m"},
            "program_id": "market_intelligence",
        },
        mission_id="m-swing",
    )
    assert row["mission_id"] == "m-swing"
    cfg = vp.default_decision_config(row)
    assert cfg["portfolio_key"] == "swing_25k"
    assert cfg["starting_cash"] == 25000.0
    assert cfg["persona"]["objective"] == "Growth"


def test_create_book_without_templates():
    vp.clear()
    row = vp.create_book(
        label="Experiment #7",
        capital=7000,
        persona={"objective": "Experiment", "risk": "high"},
        instantiate=False,
    )
    assert row["portfolio_key"] == "experiment_7"
    assert row["persona"]["capital"] == 7000.0


def test_paper_trading_uses_portfolio_key_name():
    vp.clear()
    ensured: list[dict] = []

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            ensured.append(kwargs)
            return {"id": "p1", "cash": kwargs.get("starting_cash", 0)}

        def snapshot(self, portfolio_id, prices=None):
            return {
                "equity": 10000,
                "cash": 10000,
                "positions": [],
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            }

        def position(self, *a, **k):
            return None

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
    from atlas.investment.watchlists import clear, publish

    clear()
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "RELIANCE.NS"}],
        ranked=[{"symbol": "RELIANCE.NS", "rank": 1}],
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="mission-a",
            config={
                "instruments": [],
                "feed_mode": "live",
                "starting_cash": 10000,
                "portfolio_key": "equity_10k",
                "persona": {
                    "objective": "Wealth",
                    "risk": "low",
                    "time_horizon": "5y",
                    "capital": 10000,
                    "allowed_assets": ["cash_equity"],
                },
                "respect_market_hours": False,
                "market_session": "always_open",
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("portfolio_key") == "equity_10k"
    assert result.state.get("persona", {}).get("risk") == "low"
    assert ensured and ensured[0]["name"] == "equity_10k"
    assert ensured[0]["mission_id"] == "mission-a"
    assert "book=equity_10k" in (result.note or "")


def test_persona_blocks_disallowed_asset_class():
    """Ready pack + persona filter — cash_equity pack rejects futures-only instruments."""
    vp.clear()

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            return {"id": "p1", "cash": 10000}

        def snapshot(self, *a, **k):
            return {"equity": 10000, "cash": 10000, "positions": [], "realized_pnl": 0, "unrealized_pnl": 0}

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=object(),
        portfolio=FakePortfolio(),
        live_market=object(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-filter",
            config={
                "instruments": [{"symbol": "NIFTY-FUT", "asset_class": "futures"}],
                "feed_mode": "live",
                "portfolio_key": "equity_only",
                "instrument_pack": "cash_equity",
                "asset_class": "cash_equity",
                "persona": {
                    "objective": "Wealth",
                    "risk": "low",
                    "allowed_assets": ["cash_equity"],
                    "capital": 10000,
                },
                "respect_market_hours": False,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "idle" in result.note
    assert "excludes" in result.note


def test_futures_book_ready_ensures_portfolio():
    """IL.11 follow-on — futures pack is ready; book setup proceeds past pack gate."""
    vp.clear()
    ensured = []

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            ensured.append(kwargs)
            return {"id": "p1", "cash": kwargs.get("starting_cash", 0)}

        def snapshot(self, *a, **k):
            return {
                "equity": 50000,
                "cash": 50000,
                "positions": [],
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=object(),
        portfolio=FakePortfolio(),
        live_market=object(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-fo",
            config={
                "instruments": [{"symbol": "NIFTY-FUT", "asset_class": "futures"}],
                "feed_mode": "live",
                "portfolio_key": "fo_demo",
                "persona": {
                    "objective": "Learning",
                    "risk": "very_high",
                    "allowed_assets": ["futures"],
                    "capital": 50000,
                },
                "respect_market_hours": False,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "capability_gap" not in (result.note or "")
    assert result.state.get("instrument_pack_ready") is True
    assert ensured
    assert ensured[0].get("name") == "fo_demo"


def test_commodity_book_capability_gap_when_pack_not_ready():
    """Unready packs still journal capability_gap (no silent fills)."""
    vp.clear()

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            raise AssertionError("stub pack should gap before ensure_portfolio")

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=object(),
        portfolio=FakePortfolio(),
        live_market=object(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-cmd",
            config={
                "instruments": [{"symbol": "GOLD", "asset_class": "commodity"}],
                "feed_mode": "live",
                "portfolio_key": "cmd_demo",
                "persona": {
                    "objective": "Learning",
                    "risk": "high",
                    "allowed_assets": ["commodity"],
                    "capital": 50000,
                },
                "respect_market_hours": False,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "capability_gap" in result.note
    assert "instrument_pack:commodity" in result.note
