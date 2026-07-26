"""IL.11 — Simulation Engine instrument packs (hermetic)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas.configuration.schemas import PaperTradingConfig, default_registry
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.investment.packs import list_packs, normalize_pack_id, resolve_pack
from atlas.investment.portfolios import clear as clear_portfolios
from atlas.trading.portfolio import PortfolioService
from atlas.trading.strategy import StrategyDecisionRule
from atlas.workers.base import TickContext
from atlas.workers.paper_trading import PaperTradingWorker
from tests.test_trading_portfolio import InMemorySimRepo


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def record(self, decision):
        self.rows.append(decision)
        return {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc)}


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


class _FakeAssets:
    def __init__(self, feeds: dict[str, list[dict[str, Any]]]) -> None:
        self._ids = {name: str(uuid.uuid4()) for name in feeds}
        self._by_id = {self._ids[name]: name for name in feeds}

    def get_by_name(self, kind, name):
        aid = self._ids.get(name)
        return {"id": aid, "name": name} if aid else None

    def name_for(self, asset_id):
        return self._by_id[asset_id]


class _FakeReader:
    def __init__(self, assets: _FakeAssets, feeds: dict[str, list[dict[str, Any]]]) -> None:
        self._assets = assets
        self._feeds = feeds

    def read(self, asset_id, asset_version=None, *, filename=None, force=False):
        name = self._assets.name_for(asset_id)
        return {"outcome": "ok", "bars": self._feeds[name], "count": len(self._feeds[name])}


def _bars(closes: list[float]) -> list[dict[str, Any]]:
    return [
        {"t": i, "open": c, "high": c, "low": c, "close": c, "volume": 100}
        for i, c in enumerate(closes)
    ]


def _worker(feeds: dict[str, list[dict[str, Any]]]) -> PaperTradingWorker:
    assets = _FakeAssets(feeds)
    reader = _FakeReader(assets, feeds)
    registry = DecisionRuleRegistry()
    registry.register(StrategyDecisionRule())
    engine = DecisionEngine(_FakeDecisionRepo(), rules=registry)
    return PaperTradingWorker(
        assets=assets,
        market_data=reader,
        decision_engine=engine,
        portfolio=PortfolioService(InMemorySimRepo()),
        events=_FakeEvents(),
    )


def test_list_packs_marks_cash_equity_ready():
    packs = {p["id"]: p for p in list_packs()}
    assert packs["cash_equity"]["ready"] is True
    assert packs["etf"]["ready"] is True
    assert packs["futures"]["ready"] is True
    assert packs["options"]["ready"] is True
    assert packs["commodity"]["ready"] is False
    assert packs["commodity"]["gap_detail"]


def test_resolve_pack_aliases():
    assert resolve_pack("equity").id == "cash_equity"
    assert resolve_pack("fx").id == "currency"
    assert normalize_pack_id("F&O") == "futures"
    assert resolve_pack(config={"instrument_pack": "options"}).id == "options"
    assert resolve_pack(
        allowed_assets=["futures"],
        asset_class="cash_equity",
    ).id == "cash_equity"  # asset_class wins over allowed_assets


def test_paper_trading_config_accepts_il10_il11_fields():
    cfg = PaperTradingConfig.model_validate(
        {
            "instruments": [{"symbol": "DEMO", "asset": "demo", "asset_class": "cash_equity"}],
            "portfolio_key": "india_equity_learner",
            "persona": {
                "objective": "Wealth",
                "risk": "medium",
                "capital": 10000,
                "allowed_assets": ["cash_equity"],
            },
            "instrument_pack": "cash_equity",
            "asset_class": "cash_equity",
            "feed_mode": "live",
        }
    )
    assert cfg.portfolio_key == "india_equity_learner"
    assert cfg.instrument_pack == "cash_equity"
    assert cfg.persona is not None
    assert cfg.persona.capital == 10000
    reg = default_registry()
    validated, version = reg.validate("paper_trading", cfg.model_dump())
    assert version == 1
    assert validated["portfolio_key"] == "india_equity_learner"


def test_cash_equity_pack_still_trades():
    clear_portfolios()
    closes = [100.0] * 35 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
    worker = _worker({"DEMO": _bars(closes)})
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-cash",
            config={
                "instruments": [{"symbol": "DEMO", "asset": "DEMO"}],
                "starting_cash": 10000,
                "bars_per_tick": 50,
                "feed_mode": "asset_replay",
                "respect_market_hours": False,
                "market_session": "always_open",
                "portfolio_key": "cash_book",
                "instrument_pack": "cash_equity",
                "persona": {
                    "objective": "Learning",
                    "risk": "medium",
                    "capital": 10000,
                    "allowed_assets": ["cash_equity"],
                },
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("instrument_pack") == "cash_equity"
    assert result.state.get("instrument_pack_ready") is True
    assert "pack=cash_equity" in (result.note or "")
    assert "capability_gap" not in (result.note or "")
    assert "decision" in (result.note or "")


def test_futures_pack_is_ready_and_reaches_engine():
    """Ready F&O pack no longer gaps at tick start — may idle on empty feed."""
    clear_portfolios()
    decided = []

    class TrackingEngine:
        def decide(self, request):
            from atlas.decision.contracts import Decision

            decided.append(request)
            return Decision(
                mission_id=request.mission_id,
                mission_type=request.mission_type,
                action_kind="hold",
                action={"kind": "hold"},
                why="test hold",
            )

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            return {"id": "p1", "cash": kwargs.get("starting_cash", 0)}

        def snapshot(self, *a, **k):
            return {
                "equity": 50000,
                "cash": 50000,
                "positions": [],
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }

        def apply_trade(self, *a, **k):
            raise AssertionError("hold path must not fill")

        def position(self, *a, **k):
            return {"quantity": 0.0}

    assets = _FakeAssets({"NIFTY-FUT": _bars([22000.0] * 40)})
    reader = _FakeReader(assets, {"NIFTY-FUT": _bars([22000.0] * 40)})
    worker = PaperTradingWorker(
        assets=assets,
        market_data=reader,
        decision_engine=TrackingEngine(),
        portfolio=FakePortfolio(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-fut",
            config={
                "instruments": [
                    {
                        "symbol": "NIFTY-FUT",
                        "asset": "NIFTY-FUT",
                        "asset_class": "futures",
                        "lot_size": 25,
                    }
                ],
                "starting_cash": 50000,
                "bars_per_tick": 5,
                "portfolio_key": "fo_demo",
                "asset_class": "futures",
                "instrument_pack": "futures",
                "persona": {
                    "objective": "Learning",
                    "risk": "very_high",
                    "allowed_assets": ["futures"],
                    "capital": 50000,
                },
                "feed_mode": "asset_replay",
                "respect_market_hours": False,
                "market_session": "always_open",
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "capability_gap" not in (result.note or "")
    assert result.state.get("instrument_pack_ready") is True
    assert result.state.get("instrument_pack") == "futures"
    assert decided  # engine reached


def test_unknown_pack_is_not_ready():
    pack = resolve_pack("weird_derivatives")
    assert pack.ready is False
    assert "weird" in pack.id


def test_commodity_pack_still_journals_capability_gap():
    clear_portfolios()

    class TrackingEngine:
        def decide(self, request):
            raise AssertionError("stub pack must not reach DecisionEngine")

    class FakePortfolio:
        def ensure_portfolio(self, **kwargs):
            raise AssertionError("stub pack must not fill")

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=TrackingEngine(),
        portfolio=FakePortfolio(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m-cmd",
            config={
                "instruments": [{"symbol": "GOLD", "asset_class": "commodity"}],
                "portfolio_key": "cmd_demo",
                "asset_class": "commodity",
                "instrument_pack": "commodity",
                "persona": {
                    "objective": "Learning",
                    "risk": "high",
                    "allowed_assets": ["commodity"],
                    "capital": 50000,
                },
                "feed_mode": "asset_replay",
                "respect_market_hours": False,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "capability_gap" in (result.note or "")
    assert "instrument_pack:commodity" in (result.note or "")
    assert result.state.get("instrument_pack_ready") is False
