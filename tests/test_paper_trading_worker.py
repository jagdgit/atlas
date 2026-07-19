"""Hermetic tests for the PaperTradingWorker (Phase D · §D.6, flagship tick).

Wires a *real* DecisionEngine (+ StrategyDecisionRule) and a *real* PortfolioService over in-memory
fakes (no DB), with a fake feed reader. Proves the full tick: read → indicators → decide → apply →
journal → notify, plus reboot-resume from the bar cursor, a live operator "don't trade SYM" input,
config-version pickup, and policy arbitration (``avoid SYM`` suppresses its buy).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
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
    """Maps market_data asset name → an asset row; the reader is keyed by the same name."""

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


class _AvoidPolicy:
    """Fake policy: a signed, bounded negative influence for `avoid <symbol>` (DD5)."""

    def __init__(self, term: str, weight: float = -10.0) -> None:
        self._inf = [{"id": f"policy-avoid-{term}", "terms": [term], "weight": weight}]

    def advice_influence(self, *, scope=None):
        return list(self._inf)


def _bars(closes: list[float]) -> list[dict[str, Any]]:
    return [{"t": i, "open": c, "high": c, "low": c, "close": c, "volume": 100}
            for i, c in enumerate(closes)]


# Flat warmup, an uptrend with a pullback (so RSI isn't saturated → a buy fires when the fast MA
# leads the slow MA and RSI cools below the overbought line), then a clear downtrend (→ sells).
_UPDOWN = [10, 10, 10, 10, 10, 10.5, 11, 10.8, 11.6, 12.2, 11.9, 12.8, 13.5, 12.5, 11, 9.5, 8, 7]


def _engine(policy=None) -> DecisionEngine:
    reg = DecisionRuleRegistry()
    reg.register(StrategyDecisionRule())
    return DecisionEngine(_FakeDecisionRepo(), rules=reg, policy=policy)


def _worker(feeds, *, engine=None, events=None, portfolio=None):
    assets = _FakeAssets(feeds)
    reader = _FakeReader(assets, feeds)
    return PaperTradingWorker(
        assets=assets,
        market_data=reader,
        decision_engine=engine or _engine(),
        portfolio=portfolio or PortfolioService(InMemorySimRepo()),
        events=events,
    )


def _ctx(config, state=None, *, version=1, inputs=None):
    return TickContext(
        worker_id="w1", mission_id=str(uuid.uuid4()), config=config,
        config_version=version, state=state or {}, inputs=inputs or [],
    )


_CFG = {
    "instruments": [{"symbol": "ACME", "asset": "acme"}],
    "starting_cash": 100000.0,
    "strategy": {"sma_fast": 3, "sma_slow": 5, "rsi_period": 5},
    "bars_per_tick": 100,
}


def test_full_run_buys_then_sells_and_journals():
    events = _FakeEvents()
    portfolio = PortfolioService(InMemorySimRepo())
    engine = _engine()
    worker = _worker({"acme": _bars(_UPDOWN)}, engine=engine, events=events, portfolio=portfolio)

    result = worker.do_tick(_ctx(_CFG))
    assert result.done is True  # feed exhausted in one big tick
    # Decisions were journaled (one per bar) and at least one buy + one sell filled.
    assert len(engine._repo.rows) == len(_UPDOWN)
    fills = [p for (t, p) in events.emitted if t == "PaperTradingFill"]
    sides = {f["side"] for f in fills}
    assert "buy" in sides and "sell" in sides


def test_reboot_resumes_from_cursor():
    feeds = {"acme": _bars(_UPDOWN)}
    cfg = {**_CFG, "bars_per_tick": 5}
    portfolio = PortfolioService(InMemorySimRepo())

    w1 = _worker(feeds, portfolio=portfolio)
    r1 = w1.do_tick(_ctx(cfg))
    assert r1.state["cursors"]["ACME"] == 5
    assert r1.done is False

    # Simulate a reboot: a brand-new worker instance resumes from the checkpoint state.
    w2 = _worker(feeds, portfolio=portfolio)
    r2 = w2.do_tick(_ctx(cfg, state=r1.state))
    assert r2.state["cursors"]["ACME"] == 10  # advanced, not restarted
    assert r2.state["ticks"] == 2


def test_operator_block_prevents_trading():
    events = _FakeEvents()
    worker = _worker({"acme": _bars(_UPDOWN)}, events=events)
    result = worker.do_tick(_ctx(_CFG, inputs=[{"block_symbol": "ACME"}]))
    assert result.state["blocked_symbols"] == ["acme"]
    fills = [p for (t, p) in events.emitted if t == "PaperTradingFill"]
    assert fills == []  # blocked → only holds, no fills


def test_config_version_pickup_noted():
    worker = _worker({"acme": _bars(_UPDOWN)})
    result = worker.do_tick(_ctx(_CFG, version=7))
    assert result.state["config_version"] == 7
    assert "config v7 picked up" in result.note


def test_policy_avoid_suppresses_buys():
    # Baseline (no policy): buys happen.
    base = _worker({"acme": _bars(_UPDOWN)}, engine=_engine(), events=_FakeEvents())
    base_events = base._events
    base.do_tick(_ctx(_CFG))
    base_buys = [p for (t, p) in base_events.emitted if t == "PaperTradingFill" and p["side"] == "buy"]
    assert base_buys  # sanity: without policy, it buys

    # With `avoid acme`: the buy option is pushed below hold → no buys fill.
    events = _FakeEvents()
    worker = _worker({"acme": _bars(_UPDOWN)}, engine=_engine(policy=_AvoidPolicy("acme")), events=events)
    worker.do_tick(_ctx(_CFG))
    buys = [p for (t, p) in events.emitted if t == "PaperTradingFill" and p["side"] == "buy"]
    assert buys == []


def test_drawdown_alert_emitted():
    events = _FakeEvents()
    # Buy into an uptrend (equity peaks on unrealized gains), then a steep fall → the per-bar equity
    # drawdown breaches the alert threshold before the position is fully exited.
    closes = [10, 10, 10, 10, 10, 9.4, 10.3, 11.2, 10.9, 12, 13.5, 11, 8.5, 6]
    cfg = {
        **_CFG,
        "strategy": {"sma_fast": 3, "sma_slow": 5, "rsi_period": 5, "trade_fraction": 1.0},
        "drawdown_alert_pct": 5.0,
    }
    worker = _worker({"acme": _bars(closes)}, events=events)
    worker.do_tick(_ctx(cfg))
    drawdowns = [p for (t, p) in events.emitted if t == "PaperTradingDrawdown"]
    assert drawdowns and drawdowns[0]["drawdown_pct"] >= 5.0
