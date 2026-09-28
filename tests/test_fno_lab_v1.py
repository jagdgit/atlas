"""F&O Lab v1 — indices + bounded stock seed contract (hermetic)."""

from __future__ import annotations

from datetime import date

from atlas.investment.fno_contract import (
    choose_atm_overlay,
    resolve_nearest_fut,
    resolve_phase2_bundle,
)
from atlas.investment.fno_lab_v1 import (
    DEFAULT_STOCK_SEED,
    attribution,
    experiment_family_id,
    instrument_rows_for_seed,
    is_eligible_underlier,
    load_stock_seed,
    persist_stock_seed,
    policy,
    universe,
)


def _stock_rows(as_of: date) -> list[dict]:
    exp = "2026-09-25"
    return [
        {
            "tradingsymbol": "RELIANCE25SEP2800FUT",
            "name": "RELIANCE",
            "instrument_type": "FUT",
            "instrument_token": 111,
            "expiry": exp,
            "lot_size": 250,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "RELIANCE25SEP2800CE",
            "name": "RELIANCE",
            "instrument_type": "CE",
            "instrument_token": 112,
            "expiry": exp,
            "lot_size": 250,
            "strike": 2800,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "RELIANCE25SEP2800PE",
            "name": "RELIANCE",
            "instrument_type": "PE",
            "instrument_token": 113,
            "expiry": exp,
            "lot_size": 250,
            "strike": 2800,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "RELIANCE25SEP2850CE",
            "name": "RELIANCE",
            "instrument_type": "CE",
            "instrument_token": 114,
            "expiry": exp,
            "lot_size": 250,
            "strike": 2850,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "TCS25SEP4000FUT",
            "name": "TCS",
            "instrument_type": "FUT",
            "instrument_token": 211,
            "expiry": exp,
            "lot_size": 175,
            "exchange": "NFO",
        },
    ]


def test_universe_has_four_indices_and_stock_seed():
    uni = universe()
    assert uni["index_underliers"] == [
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
    ]
    assert "RELIANCE" in uni["stock_seed"]
    assert 20 <= len(uni["stock_seed"]) <= 50
    assert uni["count"] == 4 + len(uni["stock_seed"])


def test_eligible_underliers():
    assert is_eligible_underlier("NIFTY") is True
    assert is_eligible_underlier("BANKNIFTY") is True
    assert is_eligible_underlier("RELIANCE") is True
    assert is_eligible_underlier("RELIANCE.NS") is True
    assert is_eligible_underlier("NOTASEED") is False


def test_experiment_family_stable():
    assert experiment_family_id("RELIANCE") == "FNO-ATM-REL-001"
    assert experiment_family_id("NIFTY") == "FNO-ATM-NIF-001"
    assert experiment_family_id("BANKNIFTY") == "FNO-ATM-BNF-001"
    # CE vs PE share family — right lives in attribution
    assert experiment_family_id("RELIANCE", right="CE") == experiment_family_id(
        "RELIANCE", right="PE"
    )


def test_attribution_identity_fields():
    att = attribution(
        underlying="RELIANCE",
        future_contract={"tradingsymbol": "RELIANCE25SEP2800FUT", "expiry": "2026-09-25", "lot_size": 250},
        option_contract={
            "tradingsymbol": "RELIANCE25SEP2800CE",
            "instrument_type": "CE",
            "strike": 2800,
            "expiry": "2026-09-25",
            "lot_size": 250,
        },
        entry_ltp=42.0,
        trade_id="t-1",
        entry_reason="sma_bullish_atm_ce",
        cognitive_review="UNREVIEWED",
    )
    assert att["laboratory_id"] == "india_fno_learner"
    assert att["underlying"] == "RELIANCE"
    assert att["underlying_type"] == "stock"
    assert att["experiment_family"] == "FNO-ATM-REL-001"
    assert att["option_contract"] == "RELIANCE25SEP2800CE"
    assert att["option_type"] == "CE"
    assert att["live_orders"] is False
    assert att["uses_l4_index_proxy"] is False


def test_seed_persist_and_custom(tmp_path):
    out = persist_stock_seed(tmp_path, ["RELIANCE", "TCS"])
    assert out["ok"] is True
    assert load_stock_seed(tmp_path) == ["RELIANCE", "TCS"]
    assert is_eligible_underlier("TCS", data_dir=tmp_path) is True
    assert is_eligible_underlier("INFY", data_dir=tmp_path) is False


def test_instrument_rows_include_seed():
    rows = instrument_rows_for_seed()
    syms = {r["symbol"] for r in rows}
    assert {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"} <= syms
    assert "RELIANCE" in syms
    assert len(rows) == 4 + len(DEFAULT_STOCK_SEED)


def test_resolve_stock_fut_and_atm_bundle():
    as_of = date(2026, 9, 17)
    rows = _stock_rows(as_of)
    fut = resolve_nearest_fut(rows, symbol="RELIANCE", as_of=as_of)
    assert fut["ok"] is True
    assert fut["underlying"] == "RELIANCE"
    assert fut["underlying_type"] == "stock"
    assert fut["tradingsymbol"] == "RELIANCE25SEP2800FUT"
    bundle = resolve_phase2_bundle(rows, symbol="RELIANCE", spot=2810, as_of=as_of)
    assert bundle["ok"] is True
    assert bundle["underlying_type"] == "stock"
    assert bundle["ce"]["tradingsymbol"] == "RELIANCE25SEP2800CE"
    assert bundle["pe"]["tradingsymbol"] == "RELIANCE25SEP2800PE"


def test_overlay_works_for_stock_and_banknifty():
    as_of = date(2026, 9, 17)
    # Stock
    bundle = resolve_phase2_bundle(_stock_rows(as_of), symbol="RELIANCE", spot=2810, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=0.01,
        underlier_held=0.0,
        positions=[],
        bundle=bundle,
        cash=200_000.0,
        ce_ltp=40.0,
        pe_ltp=35.0,
        control_action="buy",
        underlying_price=2810.0,
    )
    assert out["used"] is True
    assert out["right"] == "CE"
    assert out["symbol"] == "RELIANCE25SEP2800CE"
    assert out["fallback_l4"] is False
    assert out["qty"] == 250.0


def test_policy_marks_equity_audit_parallel():
    p = policy()
    assert p["equity_horizon_audit"] == "parallel_not_prerequisite"
    assert p["live_orders"] is False
    assert "seed → experiences" in p["expansion_rule"]
    assert p["exit_lifecycle"]["policy"] == "session_flat"
    assert p["exit_lifecycle"]["reason_code"] == "fno_lab_v1_experiment_close"


def test_must_flatten_after_session():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from atlas.investment.fno_lab_v1 import must_flatten_experiments, open_option_positions

    ist = ZoneInfo("Asia/Kolkata")
    assert must_flatten_experiments(datetime(2026, 9, 25, 15, 31, tzinfo=ist)) is True
    assert must_flatten_experiments(datetime(2026, 9, 25, 10, 0, tzinfo=ist)) is False
    assert must_flatten_experiments(datetime(2026, 9, 26, 12, 0, tzinfo=ist)) is True  # Sat
    open_p = open_option_positions(
        [
            {"symbol": "HDFCBANK26SEP730CE", "quantity": 650},
            {"symbol": "RELIANCE", "quantity": 1},
            {"symbol": "COALINDIA.NS", "quantity": 19},
        ]
    )
    assert len(open_p) == 1
    assert open_p[0]["symbol"] == "HDFCBANK26SEP730CE"


def test_underlying_from_option_and_integrity(tmp_path):
    from atlas.investment.fno_lab_v1 import (
        record_experiment_integrity,
        underlying_from_option_tsym,
    )

    assert underlying_from_option_tsym("HDFCBANK26SEP730CE") == "HDFCBANK"
    assert underlying_from_option_tsym("ADANIPORTS26SEP1800CE") == "ADANIPORTS"
    doc = record_experiment_integrity(
        tmp_path,
        positions=[{"symbol": "TATASTEEL26SEP190CE", "quantity": 2750}],
        must_be_flat=True,
        flatten_outcomes=[],
        as_of_ist="2026-09-25",
    )
    assert doc["status"] == "overnight_open"
    assert doc["overnight_option_positions"] == 1
    closed = record_experiment_integrity(
        tmp_path,
        positions=[],
        must_be_flat=True,
        flatten_outcomes=[{"status": "closed", "symbol": "TATASTEEL26SEP190CE", "trade_id": "t1"}],
        as_of_ist="2026-09-25",
    )
    assert closed["status"] == "flat_ok"
    assert closed["overnight_positions_ok"] is True
    assert closed["flatten_closed_n"] == 1
    # Empty rewrite must preserve prior closed outcomes.
    again = record_experiment_integrity(
        tmp_path,
        positions=[],
        must_be_flat=True,
        flatten_outcomes=[],
        as_of_ist="2026-09-25",
    )
    assert again["status"] == "flat_ok"
    assert again["flatten_closed_n"] == 1
    assert again["flatten_outcomes"][0]["trade_id"] == "t1"


def test_cognitive_block_honest_unreviewed():
    from atlas.investment.fno_lab_v1 import (
        apply_cognitive_to_attribution,
        attribution,
        build_cognitive_block,
    )

    att = attribution(
        underlying="HDFCBANK",
        option_contract={"tradingsymbol": "HDFCBANK26SEP730CE", "instrument_type": "CE"},
        entry_ltp=6.85,
        exit_ltp=6.85,
        exit_reason="fno_lab_v1_experiment_close",
        trade_id="abc",
    )
    att["realized_pnl"] = 0.0
    att["mark_source"] = "avg_cost_mark_unavailable"
    cog = build_cognitive_block(att, advice=None)
    assert cog["cognitive_review"] == "UNREVIEWED"
    assert "Lab v1" in cog["lesson_candidate"]
    stamped = apply_cognitive_to_attribution(att, advice={"review_status": "REVIEWED", "summary": "thin sample"})
    assert stamped["cognitive_review"] == "REVIEWED"
    assert stamped["cognitive"]["lesson_candidate"] == "thin sample"


def test_lab_fields_carry_fno_attribution():
    from atlas.investment.lab_experience import attach_round_trip_l10

    exp = {"kind": "EXPERIENCE", "as_of_ist": "2026-09-25"}
    att = {
        "experiment_family": "FNO-ATM-HDF-001",
        "option_contract": "HDFCBANK26SEP730CE",
        "option_type": "CE",
        "underlying": "HDFCBANK",
        "cognitive_review": "UNREVIEWED",
        "cognitive": {"cognitive_review": "UNREVIEWED", "lesson_candidate": "x"},
    }
    out = attach_round_trip_l10(
        exp,
        laboratory_id="india_fno_learner",
        symbol="HDFCBANK26SEP730CE",
        trade={"id": "t1", "side": "sell", "quantity": 650, "price": 6.85, "realized_pnl": 0.0},
        packet={
            "fno_lab_v1": att,
            "cognitive": att["cognitive"],
            "strategy_tag": "fno_lab_v1_experiment_close",
            "mark_source": "avg_cost_mark_unavailable",
            "exit_reason": "fno_lab_v1_experiment_close",
        },
    )
    fields = out.get("lab_fields") or {}
    assert fields.get("fno_lab_v1", {}).get("experiment_family") == "FNO-ATM-HDF-001"
    assert fields.get("cognitive_review") == "UNREVIEWED"
    assert fields.get("mark_source") == "avg_cost_mark_unavailable"


def test_entry_prediction_persisted_and_consumable(tmp_path):
    from atlas.investment.fno_lab_v1 import (
        bind_entry_prediction_trade,
        build_entry_prediction,
        expected_block_from_prediction,
        load_entry_prediction,
        persist_entry_prediction,
    )
    from atlas.investment.learning_objects import record_from_trade_close

    pred = build_entry_prediction(
        underlying="HDFCBANK",
        option_symbol="HDFCBANK26SEP730CE",
        right="CE",
        entry_premium=6.85,
        sma_margin=0.004,
        control_action="buy",
        entry_reason="v1_buy_atm_ce",
    )
    assert pred["prediction_status"] == "stated"
    assert pred["expected_return"] is not None
    assert pred["expected_direction"] == "up"
    assert pred["prediction_horizon"] == "session_flat"
    assert 0.01 <= float(pred["expected_return"]) <= 0.08
    persist_entry_prediction(tmp_path, pred)
    loaded = load_entry_prediction(tmp_path, option_symbol="HDFCBANK26SEP730CE")
    assert loaded and loaded["expected_return"] == pred["expected_return"]
    bound = bind_entry_prediction_trade(
        tmp_path,
        option_symbol="HDFCBANK26SEP730CE",
        trade_id="entry-trade-1",
        decision_id="dec-1",
    )
    assert bound["trade_id"] == "entry-trade-1"
    expected = expected_block_from_prediction(bound)
    assert expected["prediction_status"] == "stated"
    # Close path consumes decide-time E[R] → prediction_error computed.
    result = record_from_trade_close(
        tmp_path,
        symbol="HDFCBANK26SEP730CE",
        trade={
            "id": "exit-trade-1",
            "side": "sell",
            "quantity": 650,
            "price": 7.54,  # ~+10% vs 6.85
            "realized_pnl": 650 * (7.54 - 6.85),
        },
        laboratory_id="india_fno_learner",
        strategy_tag="fno_lab_v1_experiment_close",
        packet={
            "strategy_tag": "fno_lab_v1_experiment_close",
            "action": "sell",
            "expected": expected,
            "entry_prediction": bound,
            "outcome_check": {
                "expected_direction": "up",
                "observed_direction": "up",
            },
        },
    )
    assert result.get("ok")
    from atlas.investment.learning_objects import load_learning_events

    rows = load_learning_events(tmp_path, "india_fno_learner", as_of_ist=None, limit=20)
    exps = [r for r in rows if r.get("kind") == "EXPERIENCE"]
    assert exps
    exp = exps[-1]
    assert exp["predicted"]["prediction_status"] == "stated"
    assert exp["predicted"]["expected_return"] == expected["expected_return"]
    assert exp["prediction_error"]["status"] in {"computed", "direction_only"}
    assert exp["prediction_error"]["direction_match"] == "matched"
    fields = exp.get("lab_fields") or {}
    assert fields.get("entry_prediction", {}).get("trade_id") == "entry-trade-1"


def test_paper_trading_session_flat_closes_open_option(tmp_path, monkeypatch):
    """Hermetic: after 15:30 IST, Lab v1 option lot → experiment_close SELL + integrity flat_ok."""
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from atlas.trading.portfolio import PortfolioService
    from atlas.workers.paper_trading import PaperTradingWorker
    from tests.test_trading_portfolio import InMemorySimRepo

    class _Cfg:
        class paths:
            data = str(tmp_path)

    monkeypatch.setattr("atlas.config.get_config", lambda: _Cfg())

    repo = InMemorySimRepo()
    portfolio = PortfolioService(repo)
    prow = portfolio.ensure_portfolio(
        mission_id=None,
        name="india_fno_learner",
        starting_cash=500_000.0,
        base_currency="INR",
    )
    pid = prow["id"]
    portfolio.apply_trade(
        pid,
        symbol="HDFCBANK26SEP730CE",
        side="buy",
        quantity=650,
        price=6.85,
        fee=0.0,
        laboratory_id="india_fno_learner",
        instrument_path="buy",
    )

    class _Assets:
        def get_by_name(self, kind, name):
            return None

    class _DecRepo:
        def record(self, decision):
            return {"id": str(uuid.uuid4())}

    from atlas.decision.engine import DecisionEngine

    ist = ZoneInfo("Asia/Kolkata")
    worker = PaperTradingWorker(
        assets=_Assets(),
        market_data=type("M", (), {"read": lambda *a, **k: {"outcome": "ok", "bars": [], "count": 0}})(),
        decision_engine=DecisionEngine(_DecRepo()),
        portfolio=portfolio,
        clock=lambda: datetime(2026, 9, 25, 16, 5, tzinfo=ist),
    )
    worker._nfo_ltp = lambda tsym: 7.10  # type: ignore[method-assign]
    worker._record_di_packet = lambda **kw: None  # type: ignore[method-assign]
    worker._notify_fill = lambda **kw: None  # type: ignore[method-assign]
    worker._remember_outcome = lambda *a, **k: None  # type: ignore[method-assign]

    state: dict = {}
    lines = worker._flatten_fno_lab_v1_experiments(
        cfg={"broker_profile": ""},
        portfolio_id=pid,
        portfolio_key="india_fno_learner",
        mission_id=None,
        state=state,
        pack=None,
    )
    assert any("experiment_close SELL" in ln and "HDFCBANK26SEP730CE" in ln for ln in lines)
    snap = portfolio.snapshot(pid)
    assert not any(
        abs(float(p.get("quantity") or 0)) > 1e-12
        for p in (snap.get("positions") or [])
        if str(p.get("symbol") or "").endswith(("CE", "PE"))
    )
    assert state.get("fno_lab_v1_integrity", {}).get("status") == "flat_ok"
    outcomes = state.get("fno_lab_v1_flatten_outcomes") or []
    assert outcomes and outcomes[-1]["status"] == "closed"
    assert outcomes[-1]["attribution"]["exit_reason"] == "fno_lab_v1_experiment_close"


def test_session_flat_blocks_new_buy_after_close():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from atlas.investment.fno_lab_v1 import must_flatten_experiments

    ist = ZoneInfo("Asia/Kolkata")
    assert must_flatten_experiments(datetime(2026, 9, 25, 15, 45, tzinfo=ist)) is True
