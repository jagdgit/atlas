"""LI.1a — laboratory hermeticity: isolation + cross-lab contamination tests."""

from __future__ import annotations

import pytest

from atlas.investment import portfolios as vp
from atlas.investment.decision_packets import build_packet
from atlas.investment.di_dashboards import classify_exits_by_strategy
from atlas.investment.laboratory import (
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
    assert_single_laboratory,
    laboratory_id_for,
    normalize_laboratory_id,
    refuse_pooled_edge_metrics,
    stamp_laboratory_identity,
    transfer_allowed,
)
from atlas.investment.thesis_tracker import apply_outcome_to_priors, load_priors


def test_laboratory_id_aliases_portfolio_key():
    assert laboratory_id_for("india_equity_learner") == DEFAULT_SWING_LAB
    assert normalize_laboratory_id(portfolio_key="equity_intraday_learner") == DEFAULT_INTRADAY_LAB
    stamped = stamp_laboratory_identity({"portfolio_key": "lab_a"})
    assert stamped["laboratory_id"] == "lab_a"
    assert stamped["portfolio_key"] == "lab_a"


def test_create_two_laboratories_isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_VIRTUAL_PORTFOLIOS", str(tmp_path / "vp.json"))
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    # Reset in-memory store between tests that touch disk.
    vp._STORE.clear()
    vp._LOADED = False

    swing = vp.create_laboratory(
        label="Equity Swing",
        laboratory_id=DEFAULT_SWING_LAB,
        capital=50_000.0,
    )
    intra = vp.create_laboratory(
        label="Equity Intraday",
        laboratory_id=DEFAULT_INTRADAY_LAB,
        capital=25_000.0,
        persona={
            "objective": "Learning",
            "risk": "high",
            "time_horizon": "intraday",
            "allowed_assets": ["cash_equity"],
            "capital": 25_000.0,
        },
    )
    assert swing["laboratory_id"] == DEFAULT_SWING_LAB
    assert swing["portfolio_key"] == DEFAULT_SWING_LAB
    assert intra["laboratory_id"] == DEFAULT_INTRADAY_LAB
    assert swing["portfolio_key"] != intra["portfolio_key"]
    assert swing["experience_scope"] == f"portfolio:{DEFAULT_SWING_LAB}"
    assert intra["lab_prior_tag"] == f"lab:{DEFAULT_INTRADAY_LAB}"
    assert float(swing["persona"]["capital"]) == 50_000.0
    assert float(intra["persona"]["capital"]) == 25_000.0

    keys = {r["portfolio_key"] for r in vp.list_portfolios()}
    assert DEFAULT_SWING_LAB in keys
    assert DEFAULT_INTRADAY_LAB in keys


def test_decision_packet_stamps_laboratory_id():
    pkt = build_packet(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-07",
    )
    assert pkt["laboratory_id"] == DEFAULT_SWING_LAB
    assert pkt["portfolio_key"] == DEFAULT_SWING_LAB


def test_refuse_pooled_win_rate_across_labs():
    rows = [
        {"laboratory_id": DEFAULT_SWING_LAB, "pnl": 100},
        {"portfolio_key": DEFAULT_INTRADAY_LAB, "pnl": -50},
    ]
    with pytest.raises(LaboratoryContaminationError):
        refuse_pooled_edge_metrics(rows, context="test_pool")
    assert assert_single_laboratory(
        [{"laboratory_id": DEFAULT_SWING_LAB}], expected=DEFAULT_SWING_LAB
    ) == DEFAULT_SWING_LAB


def test_classify_exits_refuses_cross_lab_packets():
    attrs = [
        {
            "decision_id": "d1",
            "trigger": "exit",
            "portfolio_key": DEFAULT_SWING_LAB,
            "grades": {"pnl": 10.0},
        },
        {
            "decision_id": "d2",
            "trigger": "exit",
            "portfolio_key": DEFAULT_INTRADAY_LAB,
            "grades": {"pnl": -5.0},
        },
    ]
    packets = {
        "d1": {
            "decision_id": "d1",
            "strategy_tag": "sma_cross_rsi",
            "laboratory_id": DEFAULT_SWING_LAB,
            "portfolio_key": DEFAULT_SWING_LAB,
        },
        "d2": {
            "decision_id": "d2",
            "strategy_tag": "sma_cross_rsi",
            "laboratory_id": DEFAULT_INTRADAY_LAB,
            "portfolio_key": DEFAULT_INTRADAY_LAB,
        },
    }
    with pytest.raises(LaboratoryContaminationError):
        classify_exits_by_strategy(attrs, packets)


def test_priors_scoped_per_laboratory(tmp_path):
    apply_outcome_to_priors(
        tmp_path,
        program_id="market_intelligence",
        laboratory_id=DEFAULT_SWING_LAB,
        result="falsified",
        failed_kinds=["valuation_band"],
        lessons=["swing lesson"],
    )
    apply_outcome_to_priors(
        tmp_path,
        program_id="market_intelligence",
        laboratory_id=DEFAULT_INTRADAY_LAB,
        result="held",
        held_kinds=["growth_path"],
        lessons=["intra lesson"],
    )
    swing = load_priors(
        tmp_path, "market_intelligence", laboratory_id=DEFAULT_SWING_LAB
    )
    intra = load_priors(
        tmp_path, "market_intelligence", laboratory_id=DEFAULT_INTRADAY_LAB
    )
    assert swing["closed_outcomes"] == 1
    assert intra["closed_outcomes"] == 1
    assert swing["laboratory_id"] == DEFAULT_SWING_LAB
    assert "swing lesson" in (swing.get("failure_lessons") or [])
    assert "intra lesson" not in (swing.get("failure_lessons") or [])
    assert (intra.get("by_result") or {}).get("held") == 1
    assert (swing.get("by_result") or {}).get("falsified") == 1


def test_controlled_transfer_classes():
    assert transfer_allowed("world") is True
    assert transfer_allowed("strategy") is False
    assert transfer_allowed("returns") is False
    assert transfer_allowed("win_rate") is False


def test_filter_journals_keeps_lab_scope():
    swing_tag = vp.experience_tag(DEFAULT_SWING_LAB)
    intra_tag = vp.experience_tag(DEFAULT_INTRADAY_LAB)
    journals = [
        {"id": "1", "tags": [swing_tag], "text": "swing"},
        {"id": "2", "tags": [intra_tag], "text": "intra"},
        {"id": "3", "tags": [], "text": "untagged legacy"},
    ]
    kept = vp.filter_journals_for_portfolio(journals, DEFAULT_SWING_LAB)
    ids = {j["id"] for j in kept}
    assert ids == {"1"}
