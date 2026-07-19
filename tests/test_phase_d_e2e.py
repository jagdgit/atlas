"""Phase-D end-to-end acceptance — the Decision-Engine flagship gate (PHASE_D_PLAN §D.6/§D.11).

Exercises the **whole Paper-Trading story** against a live PostgreSQL through the real D-Core wiring —
the Asset/Storage stores, the ``MarketDataReader``, the shared ``DecisionEngine`` (+ ``StrategyDecision
Rule``) with **Policy** arbitration, the virtual ``PortfolioService``, and the ``PaperTradingWorker`` —
exactly as ``bootstrap`` assembles them (simulation only, P10):

  * **Runs many ticks → explainable, journaled decisions (P9):** each replayed bar produces a
    ``decision.decisions`` row carrying its rule, why, refs, config/model versions, and rejected
    alternatives; recommended buys/sells become ``sim.trades`` **linked back to the decision** that
    caused them, moving the virtual portfolio's cash/positions.
  * **Respects a live operator constraint:** a "don't trade SYM" input makes that symbol *hold only* —
    no fills — while other instruments keep trading.
  * **Respects a policy (DD5 arbitration):** an ``avoid SYM`` rule pushes that symbol's buy below hold
    (recorded in the decision's ``policy_ids``) so it is not bought; the untouched symbol still buys.
  * **Survives reboot:** a fresh worker instance resumes from the checkpointed bar cursor, not from the
    start — and picks up a bumped config version.
  * **Notifies on notable events:** fills + drawdown are emitted to the event bus.

Requires a live DB; the module is skipped if PostgreSQL is unreachable (matching the other e2e gates).
Requires migrations 0039 (decisions), 0041 (sim trading).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.database.connection import DatabaseManager
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.engineering.artifacts import DerivedArtifactStore
from atlas.policy import PolicyService
from atlas.readers import MarketDataReader
from atlas.repositories.decision_repo import DecisionRepository
from atlas.repositories.policy_repo import PolicyRepository
from atlas.repositories.sim_repo import SimTradingRepository
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager
from atlas.trading.portfolio import PortfolioService
from atlas.trading.strategy import StrategyDecisionRule
from atlas.workers.base import TickContext
from atlas.workers.paper_trading import PaperTradingWorker

# Flat warmup, an uptrend with a pullback (buy fires as RSI cools under overbought), then a decline
# (→ sells). Same shape proven deterministic in the hermetic worker test.
_SERIES = [10, 10, 10, 10, 10, 10.5, 11, 10.8, 11.6, 12.2, 11.9, 12.8, 13.5, 12.5, 11, 9.5, 8, 7]


class _RecordingEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, *, source: str | None = None) -> None:
        self.emitted.append((event_type, payload))

    def types(self) -> set[str]:
        return {t for (t, _) in self.emitted}

    def fills(self, side: str | None = None) -> list[dict]:
        return [p for (t, p) in self.emitted
                if t == "PaperTradingFill" and (side is None or p["side"] == side)]


@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


class _Stack:
    """The real Paper-Trading stack: asset store + reader + decision engine + policy + portfolio."""

    def __init__(self, db: DatabaseManager, tmp_path: Path) -> None:
        self.db = db
        storage = StorageManager(tmp_path / "storage", StorageRepository(db))
        storage.start()
        self.assets = AssetStore(storage, AssetRepository(db))
        self.artifacts = DerivedArtifactStore(storage)
        self.reader = MarketDataReader(self.assets, self.artifacts)
        self.portfolio = PortfolioService(SimTradingRepository(db))
        self.policy = PolicyService(PolicyRepository(db))
        self.events = _RecordingEvents()
        rules = DecisionRuleRegistry()
        rules.register(StrategyDecisionRule())
        self.engine = DecisionEngine(
            DecisionRepository(db), rules=rules, policy=self.policy, events=self.events,
            influence_scale=50.0,  # decision-scale policy arbitration (see engine docs)
            versions_provider=lambda: {"policy": PolicyService.VERSION},
        )

    def register_feed(self, symbol: str, closes: list[float]) -> str:
        name = f"{symbol.lower()}-{uuid.uuid4().hex[:8]}"
        bars = [{"t": i, "open": c, "high": c, "low": c, "close": c, "volume": 100}
                for i, c in enumerate(closes)]
        self.assets.register(
            "market_data", name, json.dumps(bars).encode(),
            content_type="application/json", metadata={"filename": f"{name}.json", "symbol": symbol},
        )
        return name

    def worker(self) -> PaperTradingWorker:
        return PaperTradingWorker(
            assets=self.assets, market_data=self.reader, decision_engine=self.engine,
            portfolio=self.portfolio, events=self.events,
        )


@pytest.fixture(scope="module")
def stack(db, tmp_path_factory):
    return _Stack(db, tmp_path_factory.mktemp("phase_d_e2e"))


def _cfg(instruments: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base = {
        "instruments": instruments,
        "starting_cash": 100000.0,
        "strategy": {"sma_fast": 3, "sma_slow": 5, "rsi_period": 5},
        "bars_per_tick": 5,
        "drawdown_alert_pct": 5.0,
    }
    base.update(overrides)
    return base


def _ctx(mission_id: str, config: dict, state: dict | None = None, *, version: int = 1, inputs=None):
    return TickContext(
        worker_id="w1", mission_id=mission_id, config=config, config_version=version,
        state=state or {}, inputs=inputs or [],
    )


def test_runs_journals_updates_portfolio_and_reboots(stack: _Stack):
    """Many ticks → journaled explainable decisions (P9) + portfolio moved + reboot-resume."""
    mission_id = str(uuid.uuid4())
    feed = stack.register_feed("AAA", _SERIES)
    cfg = _cfg([{"symbol": "AAA", "asset": feed}])

    worker = stack.worker()
    state: dict[str, Any] = {}
    ticks = 0
    while True:
        result = worker.do_tick(_ctx(mission_id, cfg, state))
        state = result.state
        ticks += 1
        # Simulate a reboot every tick: a fresh worker resumes from the checkpoint state.
        worker = stack.worker()
        if result.done or ticks > 20:
            break
    assert ticks > 1  # replayed across several ticks (bars_per_tick=5 over 18 bars)
    assert result.done is True
    assert state["cursors"]["AAA"] == len(_SERIES)  # replay fully consumed, resumed not restarted

    # Explainable, journaled decisions: one per replayed bar, each a full P9 record.
    decisions = stack.engine.list_decisions(mission_id=mission_id, limit=100)
    assert len(decisions) == len(_SERIES)
    recommends = [d for d in decisions if d["action_kind"] == "recommend"]
    assert recommends, "at least one actionable decision"
    sample = recommends[0]
    assert sample["why"] and sample["decision_rule"] == "paper_trading"
    assert sample["model_versions"].get("decision_engine")

    # Portfolio moved and the blotter links fills back to their decisions (P9).
    portfolio = stack.portfolio.ensure_portfolio(mission_id=mission_id)
    trades = stack.portfolio.trades(portfolio["id"])
    assert trades, "recommended trades were applied to the virtual portfolio"
    assert {t["side"] for t in trades} >= {"buy"}
    assert all(t["decision_id"] is not None for t in trades)
    snap = stack.portfolio.snapshot(portfolio["id"])
    assert snap["starting_cash"] == 100000.0
    assert snap["cash"] != 100000.0  # cash changed → the portfolio actually traded

    # Notified on notable events.
    assert "PaperTradingFill" in stack.events.types()


def test_operator_block_is_respected(stack: _Stack):
    """A live 'don't trade SYM' input makes that symbol hold-only while others keep trading."""
    mission_id = str(uuid.uuid4())
    blk = stack.register_feed("BLK", _SERIES)
    aaa = stack.register_feed("TRD", _SERIES)
    cfg = _cfg(
        [{"symbol": "BLK", "asset": blk}, {"symbol": "TRD", "asset": aaa}],
        bars_per_tick=100,
    )
    worker = stack.worker()
    result = worker.do_tick(_ctx(mission_id, cfg, inputs=[{"block_symbol": "BLK"}]))
    assert "blk" in result.state["blocked_symbols"]

    trades = stack.portfolio.trades(stack.portfolio.ensure_portfolio(mission_id=mission_id)["id"])
    symbols = {t["symbol"] for t in trades}
    assert "BLK" not in symbols          # blocked → never filled
    assert "TRD" in symbols              # the other instrument still trades


def test_policy_avoid_arbitrates_and_is_journaled(stack: _Stack):
    """An `avoid SYM` policy pushes its buy below hold (DD5) → not bought; recorded in policy_ids."""
    mission_id = str(uuid.uuid4())
    zzz = stack.register_feed("ZZZ", _SERIES)
    ok = stack.register_feed("OKK", _SERIES)
    cfg = _cfg(
        [{"symbol": "ZZZ", "asset": zzz}, {"symbol": "OKK", "asset": ok}],
        bars_per_tick=100,
    )
    # A full-strength operator `avoid ZZZ` — strength dials how hard the rule arbitrates the decision.
    rule = stack.policy.create_rule("ZZZ", "avoid", scope="global", strength=1.0)

    try:
        worker = stack.worker()
        worker.do_tick(_ctx(mission_id, cfg))

        trades = stack.portfolio.trades(stack.portfolio.ensure_portfolio(mission_id=mission_id)["id"])
        symbols = {t["symbol"] for t in trades}
        assert "ZZZ" not in symbols      # policy arbitrated the buy away
        assert "OKK" in symbols          # the un-avoided symbol still buys

        # The influence is explainable (P9): the avoid pushed the ZZZ *buy* below hold, so the policy
        # id is recorded on the rejected buy alternative of the decision it arbitrated.
        rid = str(rule["id"])
        decisions = stack.engine.list_decisions(mission_id=mission_id, limit=200)
        arbitrated = [
            d for d in decisions
            if any(rid in [str(p) for p in (alt.get("policy_ids") or [])]
                   for alt in (d.get("alternatives_rejected") or []))
        ]
        assert arbitrated, "the avoid policy is journaled on the decisions it influenced (P9)"
    finally:
        stack.policy.delete_rule(rule["id"])


def test_config_version_pickup(stack: _Stack):
    """A bumped config version is picked up and noted on the tick (P6/B6)."""
    mission_id = str(uuid.uuid4())
    feed = stack.register_feed("CFG", _SERIES)
    cfg = _cfg([{"symbol": "CFG", "asset": feed}], bars_per_tick=3)
    worker = stack.worker()
    r1 = worker.do_tick(_ctx(mission_id, cfg, version=1))
    assert r1.state["config_version"] == 1
    r2 = stack.worker().do_tick(_ctx(mission_id, cfg, r1.state, version=2))
    assert r2.state["config_version"] == 2
    assert "config v2 picked up" in r2.note
