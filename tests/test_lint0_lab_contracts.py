"""OI-LINT0 Phase 1 — lab contracts: FNO isolation, EOD flatten, thesis/engine packet."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.investment.lab_contracts import (
    CLASS_CASH_EQUITY,
    CLASS_INDEX_PROXY,
    CONTRADICTION_TECH_VS_THESIS,
    LAB_FNO,
    LAB_INTRADAY,
    LAB_SWING,
    POLICY_TECHNICAL_ONLY,
    POLICY_THESIS_GATED,
    REASON_LAB_INSTRUMENT,
    apply_lab_policy,
    decompose_decision,
    flatten_session_date,
    instrument_class,
    intraday_must_be_flat,
    is_instrument_permitted,
    lab_kind,
    skip_cash_alts_for_lab,
)
from atlas.investment.opportunity_switch import (
    REASON_BLOCKED_LAB_CONTRACT,
    review_hold_vs_challengers,
)
from atlas.trading.portfolio import PortfolioError, PortfolioService
from atlas.workers.base import TickContext
from atlas.workers.paper_trading import PaperTradingWorker
from tests.test_paper_trading_worker import (
    _FakeAssets,
    _FakeEvents,
    _FakeReader,
    _bars,
    _engine,
)
from tests.test_trading_portfolio import InMemorySimRepo

_IST = ZoneInfo("Asia/Kolkata")


def test_fno_allows_nifty_rejects_cash():
    assert lab_kind("india_fno_learner") == LAB_FNO
    nifty = is_instrument_permitted("india_fno_learner", "NIFTY", path="buy")
    assert nifty.allowed is True
    assert nifty.instrument_class == CLASS_INDEX_PROXY
    bosch = is_instrument_permitted("india_fno_learner", "BOSCHLTD.NS", path="switch")
    assert bosch.allowed is False
    assert bosch.reason == REASON_LAB_INSTRUMENT
    assert instrument_class("CIPLA.NS") == CLASS_CASH_EQUITY
    for path in ("buy", "switch", "alternative", "allocation", "replace"):
        v = is_instrument_permitted("india_fno_learner", "ASTRAL.NS", path=path)
        assert v.allowed is False, path


def test_fno_ledger_rejects_cash_buy_allows_nifty_and_cash_exit():
    svc = PortfolioService(InMemorySimRepo())
    p = svc.ensure_portfolio(
        mission_id="m-fno", name="india_fno_learner", starting_cash=100_000.0
    )
    lot = svc.apply_trade(
        p["id"],
        symbol="NIFTY",
        side="buy",
        quantity=25,
        price=24154.90,
        laboratory_id="india_fno_learner",
    )
    assert lot["side"] == "buy"
    with pytest.raises(PortfolioError, match="lab_instrument_rejected"):
        svc.apply_trade(
            p["id"],
            symbol="BOSCHLTD.NS",
            side="buy",
            quantity=2,
            price=47250.0,
            laboratory_id="india_fno_learner",
            instrument_path="switch",
        )
    # Contaminated cash (if it existed) may still be sold.
    svc.apply_trade(
        p["id"], symbol="NIFTY", side="sell", quantity=25, price=24160.0
    )


def test_uts_switch_cannot_replace_nifty_with_bosch():
    hold = {
        "symbol": "NIFTY",
        "qty": 25,
        "expected_return": 0.04,
        "confidence": 0.6,
        "score": 0.7,
        "phase": "active",
    }
    chal = {
        "symbol": "BOSCHLTD.NS",
        "expected_return": 0.20,
        "confidence": 0.8,
        "score": 0.9,
        "phase": "active",
    }
    rev = review_hold_vs_challengers(
        hold,
        [chal],
        exploratory=True,
        laboratory_id="india_fno_learner",
    )
    assert rev["decision"] == "hold"
    assert rev["reason_code"] == REASON_BLOCKED_LAB_CONTRACT
    assert rev["challenger_symbol"] == "BOSCHLTD.NS"


def test_intraday_flatten_window():
    open_sess = datetime(2026, 8, 19, 10, 0, tzinfo=_IST)
    flatten = datetime(2026, 8, 19, 15, 22, tzinfo=_IST)
    after = datetime(2026, 8, 19, 16, 0, tzinfo=_IST)
    morning = datetime(2026, 8, 20, 10, 5, tzinfo=_IST)
    assert intraday_must_be_flat(open_sess) is False
    assert intraday_must_be_flat(flatten) is True
    assert intraday_must_be_flat(after) is True
    assert flatten_session_date(flatten) == "2026-08-19"
    assert flatten_session_date(datetime(2026, 8, 20, 8, 0, tzinfo=_IST)) == "2026-08-19"
    assert intraday_must_be_flat(morning) is False


def test_swing_watch_blocks_new_buy_allows_intraday():
    swing_new = apply_lab_policy(
        lab_kind_s=LAB_SWING, technical="BUY", thesis="WATCH", held=0.0
    )
    assert swing_new["final_decision"] == "HOLD"
    assert CONTRADICTION_TECH_VS_THESIS in swing_new["contradictions"]
    assert swing_new["lab_policy"] == POLICY_THESIS_GATED
    swing_add = apply_lab_policy(
        lab_kind_s=LAB_SWING, technical="BUY", thesis="WATCH", held=13.0
    )
    assert swing_add["final_decision"] == "BUY"
    assert swing_add["add_to_incumbent"] is True
    intra = apply_lab_policy(
        lab_kind_s=LAB_INTRADAY, technical="BUY", thesis="WATCH", held=0.0
    )
    assert intra["final_decision"] == "BUY"
    assert intra["lab_policy"] == POLICY_TECHNICAL_ONLY
    d = decompose_decision(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        action="buy",
        awareness={"thesis": {"stance": "WATCH — not BUY"}},
        held=0.0,
    )
    assert d["final_decision"] == "HOLD"
    assert d["fundamental_thesis"] == "WATCH"


class _FakeEOS:
    def __init__(self) -> None:
        self.journals: list[dict] = []

    def journal(self, **kwargs):
        self.journals.append(kwargs)
        return {"id": f"exp-{len(self.journals)}", "ok": True}


def test_intraday_eod_flatten_full_lifecycle():
    clock = {"t": datetime(2026, 8, 19, 10, 0, tzinfo=_IST)}

    def now():
        return clock["t"]

    eos = _FakeEOS()
    events = _FakeEvents()
    repo = InMemorySimRepo()
    portfolio = PortfolioService(repo)
    feeds = {"astral": _bars([1535.0] * 8)}
    assets = _FakeAssets(feeds)
    worker = PaperTradingWorker(
        assets=assets,
        market_data=_FakeReader(assets, feeds),
        decision_engine=_engine(),
        portfolio=portfolio,
        events=events,
        experience_os=eos,
        clock=now,
    )
    cfg = {
        "portfolio_key": "equity_intraday_learner",
        "instruments": [{"symbol": "ASTRAL.NS", "asset": "astral"}],
        "starting_cash": 50_000.0,
        "strategy": {"sma_fast": 3, "sma_slow": 5, "rsi_period": 5},
        "bars_per_tick": 1,
        "feed_mode": "asset_replay",
        "market_session": "nse_equity",
        "respect_market_hours": True,
        "prefer_next_alternatives": False,
        "persona": {
            "time_horizon": "intraday",
            "allowed_assets": ["cash_equity"],
            "capital": 50_000.0,
        },
    }
    ctx = TickContext(
        worker_id="w-intra",
        mission_id=str(uuid.uuid4()),
        config=cfg,
        config_version=1,
        state={},
        inputs=[],
    )
    r1 = worker.do_tick(ctx)
    pid = r1.state["portfolio_id"]
    worker._portfolio.apply_trade(
        pid,
        symbol="ASTRAL.NS",
        side="buy",
        quantity=5,
        price=1535.0,
        laboratory_id="equity_intraday_learner",
    )
    pos = worker._portfolio.snapshot(pid, prices={"ASTRAL.NS": 1535.0})
    assert any(float(p.get("quantity") or 0) > 0 for p in pos["positions"])

    clock["t"] = datetime(2026, 8, 19, 15, 22, tzinfo=_IST)
    r2 = worker.do_tick(
        TickContext(
            worker_id="w-intra",
            mission_id=ctx.mission_id,
            config=cfg,
            config_version=1,
            state={**r1.state, "last_marks": {"ASTRAL.NS": 1544.90}},
            inputs=[],
        )
    )
    assert r2.state.get("intraday_must_be_flat") is True
    assert r2.state.get("intraday_eod_flat_ist") == "2026-08-19"
    snap = worker._portfolio.snapshot(pid, prices={"ASTRAL.NS": 1544.90})
    assert snap["positions"] == [] or all(
        abs(float(p.get("quantity") or 0)) < 1e-9 for p in snap["positions"]
    )
    outcomes = r2.state.get("eod_flatten_outcomes") or []
    assert outcomes, "EOD flatten must write an outcome/experience record"
    assert outcomes[0]["symbol"] == "ASTRAL.NS"
    assert float(outcomes[0]["qty"]) == 5
    assert "realized_pnl" in outcomes[0]
    sells = [
        t for t in repo.trades
        if t.get("side") == "sell" and t.get("symbol") == "ASTRAL.NS"
    ]
    assert sells
    assert eos.journals, "flatten must journal an experience"

    clock["t"] = datetime(2026, 8, 20, 10, 5, tzinfo=_IST)
    r3 = worker.do_tick(
        TickContext(
            worker_id="w-intra",
            mission_id=ctx.mission_id,
            config=cfg,
            config_version=1,
            state=r2.state,
            inputs=[],
        )
    )
    snap3 = worker._portfolio.snapshot(pid)
    assert snap3["positions"] == [] or all(
        abs(float(p.get("quantity") or 0)) < 1e-9 for p in snap3["positions"]
    )
    assert r3.state.get("intraday_must_be_flat") is False
    assert skip_cash_alts_for_lab({}, portfolio_key="equity_intraday_learner") is True


def test_skip_cash_alts_still_true_for_fno():
    assert skip_cash_alts_for_lab({}, portfolio_key="india_fno_learner") is True
    assert skip_cash_alts_for_lab({}, portfolio_key="india_equity_learner") is False
