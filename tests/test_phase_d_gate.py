"""Phase-D end-to-end gate (PHASE_D_PLAN §D.11) — Decision Engine + applied Missions.

This is the formal Phase-D acceptance module. It proves, against a live PostgreSQL (skipped if
unreachable), that a Decision-driven Mission (Paper Trading) runs across reboots, is
live-configurable, policy-arbitrated, and notifying, with every decision provenance-stamped (P9);
that side-effecting recommendations are human-gated and reversible (P14); and that the bootstrapped
kernel exposes the full D-Core + D-Missions inventory. Per-slice hermetic coverage for D.1–D.10
lives in the sibling test modules and is re-run as part of the Phase-D suite.

Requires migrations 0039–0041.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.database.connection import DatabaseManager
from atlas.decision.approvals import ApprovalService
from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.engineering.artifacts import DerivedArtifactStore
from atlas.eval.baseline import BaselineReport
from atlas.improvement.applier import SelfImprovementApplier
from atlas.improvement.board import ImprovementBoard
from atlas.improvement.decision_rule import SelfImprovementDecisionRule
from atlas.kernel.bootstrap import build_application
from atlas.ops.dashboard import OperationsDashboard
from atlas.policy import PolicyService
from atlas.readers import MarketDataReader
from atlas.repositories.approval_repo import ApprovalRepository
from atlas.repositories.decision_repo import DecisionRepository
from atlas.repositories.policy_repo import PolicyRepository
from atlas.repositories.sim_repo import SimTradingRepository
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager
from atlas.system.host import HostMetrics
from atlas.trading.portfolio import PortfolioService
from atlas.trading.strategy import StrategyDecisionRule
from atlas.workers.base import TickContext
from atlas.workers.paper_trading import PaperTradingWorker
from atlas.workers.self_improvement import SelfImprovementWatcher

_SERIES = [10, 10, 10, 10, 10, 10.5, 11, 10.8, 11.6, 12.2, 11.9, 12.8, 13.5, 12.5, 11, 9.5, 8, 7]


class _RecordingEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, *, source: str | None = None) -> None:
        self.emitted.append((event_type, payload))

    def types(self) -> set[str]:
        return {t for (t, _) in self.emitted}


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


class _PaperStack:
    def __init__(self, db: DatabaseManager, tmp_path: Path) -> None:
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
            DecisionRepository(db),
            rules=rules,
            policy=self.policy,
            events=self.events,
            influence_scale=50.0,
            versions_provider=lambda: {"policy": PolicyService.VERSION},
        )

    def register_feed(self, symbol: str, closes: list[float]) -> str:
        name = f"gate-{symbol.lower()}-{uuid.uuid4().hex[:8]}"
        bars = [
            {"t": i, "open": c, "high": c, "low": c, "close": c, "volume": 100}
            for i, c in enumerate(closes)
        ]
        self.assets.register(
            "market_data",
            name,
            json.dumps(bars).encode(),
            content_type="application/json",
            metadata={"filename": f"{name}.json", "symbol": symbol},
        )
        return name

    def worker(self) -> PaperTradingWorker:
        return PaperTradingWorker(
            assets=self.assets,
            market_data=self.reader,
            decision_engine=self.engine,
            portfolio=self.portfolio,
            events=self.events,
        )


@pytest.fixture(scope="module")
def paper(db, tmp_path_factory):
    return _PaperStack(db, tmp_path_factory.mktemp("phase_d_gate_paper"))


def _paper_cfg(instruments: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base = {
        "instruments": instruments,
        "starting_cash": 100000.0,
        "strategy": {"sma_fast": 3, "sma_slow": 5, "rsi_period": 5},
        "bars_per_tick": 5,
    }
    base.update(overrides)
    return base


def _ctx(mission_id: str, config: dict, state: dict | None = None, *, version: int = 1, inputs=None):
    return TickContext(
        worker_id="gate-w",
        mission_id=mission_id,
        config=config,
        config_version=version,
        state=state or {},
        inputs=inputs or [],
    )


# --- D.11 acceptance ----------------------------------------------------


def test_gate_decision_mission_paper_trading_full_story(paper: _PaperStack):
    """Decision-driven Paper Trading: reboot, config, policy, notify, P9 provenance."""
    mission_id = str(uuid.uuid4())
    traded = paper.register_feed("GTD", _SERIES)
    avoided = paper.register_feed("AVD", _SERIES)
    cfg = _paper_cfg(
        [{"symbol": "GTD", "asset": traded}, {"symbol": "AVD", "asset": avoided}],
        bars_per_tick=100,
    )
    rule = paper.policy.create_rule("AVD", "avoid", scope="global", strength=1.0)

    try:
        # Config pickup + first pass (policy + trades).
        w1 = paper.worker()
        r1 = w1.do_tick(_ctx(mission_id, cfg, version=1))
        assert r1.state["config_version"] == 1

        # Reboot: fresh worker + bumped config resumes from checkpoint, not from bar 0.
        w2 = paper.worker()
        # Force re-eval by clearing fingerprint-equivalent: paper trading uses cursors.
        # After bars_per_tick=100 the feed is exhausted → done; prove cursor preserved.
        assert r1.state.get("cursors", {}).get("GTD", 0) >= 1
        r2 = w2.do_tick(_ctx(mission_id, cfg, r1.state, version=2))
        assert r2.state["config_version"] == 2
        assert "config v2 picked up" in r2.note
        assert r2.state["cursors"]["GTD"] == r1.state["cursors"]["GTD"]  # no rewind

        # P9 journal: decisions exist with why + rule + model versions.
        decisions = paper.engine.list_decisions(mission_id=mission_id, limit=500)
        assert decisions
        sample = decisions[0]
        assert sample["why"] and sample["decision_rule"] == "paper_trading"
        assert sample["model_versions"].get("decision_engine")

        # Policy arbitration: avoided symbol not filled; traded symbol is.
        portfolio = paper.portfolio.ensure_portfolio(mission_id=mission_id)
        trades = paper.portfolio.trades(portfolio["id"])
        symbols = {t["symbol"] for t in trades}
        assert "AVD" not in symbols
        assert "GTD" in symbols
        assert all(t["decision_id"] is not None for t in trades)

        # Policy influence journaled on rejected alternatives (P9).
        rid = str(rule["id"])
        arbitrated = [
            d for d in decisions
            if any(
                rid in [str(p) for p in (alt.get("policy_ids") or [])]
                for alt in (d.get("alternatives_rejected") or [])
            )
        ]
        assert arbitrated

        # Notify.
        assert "PaperTradingFill" in paper.events.types()
    finally:
        paper.policy.delete_rule(rule["id"])


def test_gate_side_effecting_is_gated_and_reversible(db, tmp_path):
    """Side-effecting recommendations open the P14 gate and can be applied then reverted."""
    board = ImprovementBoard(tmp_path)
    approvals = ApprovalService(ApprovalRepository(db))
    approvals.register_applier(SelfImprovementApplier(board))
    events = _RecordingEvents()
    rules = DecisionRuleRegistry()
    rules.register(SelfImprovementDecisionRule())
    engine = DecisionEngine(
        DecisionRepository(db), rules=rules, approvals=approvals, events=events
    )
    worker = SelfImprovementWatcher(
        decision_engine=engine, board=board, events=events
    )

    mission_id = str(uuid.uuid4())
    state = {
        "last_metrics": {
            "retrieval_hermetic.precision_at_k": 0.95,
            "retrieval_hermetic.recall_at_k": 0.9,
        }
    }
    report = BaselineReport(
        milestone="3B.0",
        version="gate",
        captured_at="2026-01-01T00:00:00Z",
        sections={
            "retrieval_hermetic": {
                "precision_at_k": 0.3,
                "recall_at_k": 0.9,
                "n_cases": 3,
            }
        },
    )
    with patch(
        "atlas.workers.self_improvement.run_baseline_suite", return_value=report
    ):
        result = worker.do_tick(
            _ctx(
                mission_id,
                {"gate_fixes": True, "regression_drop": 0.05},
                state,
                version=1,
            )
        )

    assert result.state["last_finding_count"] >= 1
    assert "SelfImprovementFinding" in events.types()

    decisions = engine.list_decisions(mission_id=mission_id, limit=20)
    gated = [d for d in decisions if d.get("requires_approval")]
    assert gated, "propose_fix must require approval (P14)"
    decision_id = gated[0]["id"]

    pending = [
        p for p in approvals.list_pending()
        if str(p.get("decision_id")) == str(decision_id)
    ]
    assert pending
    aid = pending[0]["id"]

    approvals.approve(aid, actor="gate-tester")
    applied = approvals.apply(aid, actor="gate-tester")
    assert applied["status"] == "applied"
    assert board.snapshot()["approved"], "approved intent recorded on the board"

    # Surfaced on the Operations Dashboard.
    class _App:
        container = type("C", (), {"resolve": staticmethod(
            lambda key: board if key == "improvement_board" else None
        )})()
        capabilities = None

        def status(self):
            return {"state": "running"}

    dash = OperationsDashboard(_App(), HostMetrics(check_internet=lambda: True))
    snap = dash.snapshot()
    assert snap["self_improvement"]["approved"]

    reverted = approvals.revert(aid, actor="gate-tester")
    assert reverted["status"] == "reverted"
    assert board.snapshot()["approved"] == []


def test_gate_bootstrap_exposes_d_core_and_d_missions(tmp_path):
    """Kernel bootstrap wires Decision Engine, approvals, arbiter, and every D-Mission rule/worker."""
    from atlas.config import load_config

    cfg = load_config()
    cfg.paths.logs = tmp_path / "logs"  # hermetic: never write /data/atlas_data/logs
    app = build_application(cfg)
    c = app.container
    decision = c.resolve("decision")
    workers = c.resolve("workers")
    approvals = c.resolve("approvals")
    arbiter = c.resolve("arbiter")
    dashboard = c.resolve("ops_dashboard")

    expected_rules = {
        "paper_trading",
        "research",
        "job_hunting",
        "technology_watch",
        "security_monitoring",
        "self_improvement",
    }
    assert expected_rules <= set(decision.known_types())

    expected_workers = {
        "paper_trading",
        "research_watcher",
        "job_watcher",
        "tech_security_watcher",
        "self_improvement",
    }
    known_workers = set(workers.known_types())
    assert expected_workers <= known_workers

    assert approvals is not None and arbiter is not None
    snap = dashboard.snapshot()
    assert "self_improvement" in snap

    # P15: missing rule → honest capability_gap, not a fabricated action.
    gap = decision.decide(
        DecisionRequest(mission_id=None, mission_type="no_such_mission_type_for_gate")
    )
    assert gap.action_kind == "capability_gap"
    assert "no_such_mission_type_for_gate" in (gap.action.get("capability") or "")
