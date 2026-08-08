"""LI.4 — DI hardening: triple lanes, replay filters, export quality (hermetic)."""

from __future__ import annotations

import pytest

from atlas.investment.decision_attribution import DecisionAttributionStore
from atlas.investment.decision_packets import build_packet
from atlas.investment.di_dashboards import classify_exits_by_strategy, sample_tier
from atlas.investment.laboratory import (
    DEFAULT_EXPERIMENT_ID,
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
    lane_display_key,
    lane_key,
    normalize_experiment_id,
)
from atlas.investment.ml_export import (
    build_export_quality_report,
    count_closed_by_lane,
    gate_status,
)


def test_lane_key_and_default_experiment():
    assert normalize_experiment_id(None) == DEFAULT_EXPERIMENT_ID
    assert lane_key(DEFAULT_SWING_LAB, "sma_cross_rsi") == (
        f"{DEFAULT_SWING_LAB}|sma_cross_rsi|{DEFAULT_EXPERIMENT_ID}"
    )
    assert lane_display_key("sma_cross_rsi") == "sma_cross_rsi"
    assert lane_display_key("sma_cross_rsi", "ab_test") == "sma_cross_rsi@ab_test"


def test_packet_stamps_experiment_id():
    pkt = build_packet(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        experiment_id="exp_a",
        ts_ist="2026-08-08",
    )
    assert pkt["experiment_id"] == "exp_a"
    assert pkt["laboratory_id"] == DEFAULT_SWING_LAB


def test_experiments_do_not_share_trusted_tier():
    """Same strategy, two experiments → separate sample gates."""
    packets_by_id = {}
    attrs = []
    for i in range(40):
        pkt = build_packet(
            action="buy",
            symbol=f"S{i}.NS",
            portfolio_key=DEFAULT_SWING_LAB,
            strategy_tag="sma_cross_rsi",
            experiment_id="exp_a" if i < 30 else "exp_b",
            ts_ist="2026-08-08",
            reasons_for=["x"],
        )
        packets_by_id[pkt["decision_id"]] = pkt
        attrs.append(
            {
                "decision_id": pkt["decision_id"],
                "trigger": "exit",
                "portfolio_key": DEFAULT_SWING_LAB,
                "laboratory_id": DEFAULT_SWING_LAB,
                "grades": {"pnl": 1.0},
                "payload": {"pnl": 1.0, "extra": {"experiment_id": pkt["experiment_id"]}},
            }
        )
    lanes = classify_exits_by_strategy(attrs, packets_by_id)
    assert "sma_cross_rsi@exp_a" in lanes
    assert "sma_cross_rsi@exp_b" in lanes
    assert sample_tier(len(lanes["sma_cross_rsi@exp_a"])) == "provisional"
    assert sample_tier(len(lanes["sma_cross_rsi@exp_b"])) == "hidden"

    closed = count_closed_by_lane(attrs, packets_by_id)
    assert closed[lane_key(DEFAULT_SWING_LAB, "sma_cross_rsi", "exp_a")] == 30
    assert closed[lane_key(DEFAULT_SWING_LAB, "sma_cross_rsi", "exp_b")] == 10
    g = gate_status(closed_by_lane=closed)
    assert g["allowed"] is False  # neither lane trusted (≥300)
    assert g["gate_scope"] == "(laboratory_id, strategy_tag, experiment_id)"


def test_attribution_stamps_lab_and_experiment(tmp_path):
    store = DecisionAttributionStore(data_dir=tmp_path)
    pkt = build_packet(
        action="buy",
        symbol="INFY.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        experiment_id="pilot",
        reasons_for=["signal"],
    )
    out = store.record(
        decision_id=pkt["decision_id"],
        symbol="INFY.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        trigger="exit",
        packet=pkt,
        pnl=-2.0,
        failure_cause="execution",
    )
    doc = out["attribution"]
    assert doc["laboratory_id"] == DEFAULT_SWING_LAB
    assert doc["experiment_id"] == "pilot"
    assert doc["payload"]["experiment_id"] == "pilot"


def test_replay_filters_reject_mismatch(tmp_path):
    store = DecisionAttributionStore(data_dir=tmp_path)
    pkt = build_packet(
        action="buy",
        symbol="TCS.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        experiment_id="default",
        reasons_for=["signal"],
    )
    # bind a tiny packet getter
    class _Pkts:
        def get(self, did):
            return pkt if did == pkt["decision_id"] else None

    store.bind(packets=_Pkts())
    store.record(
        decision_id=pkt["decision_id"],
        symbol="TCS.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        trigger="exit",
        packet=pkt,
        pnl=1.0,
    )
    ok = store.build_replay(
        pkt["decision_id"], laboratory_id=DEFAULT_SWING_LAB, strategy_tag="sma_cross_rsi"
    )
    assert ok["matched"] is True
    bad = store.build_replay(
        pkt["decision_id"], laboratory_id=DEFAULT_INTRADAY_LAB
    )
    assert bad["matched"] is False
    assert bad["packet"] is None


def test_export_quality_report_hermetic_and_honest():
    swing_pkts = [
        build_packet(
            action="buy",
            symbol="A.NS",
            portfolio_key=DEFAULT_SWING_LAB,
            strategy_tag="sma_cross_rsi",
            prior_thesis_id="th1",
            evidence_refs=["ev1"],
            market_snapshot={"regime_tags": ["sideways"], "session": "regular"},
            reasons_for=["x"],
        )
    ]
    swing_attrs = [
        {
            "decision_id": swing_pkts[0]["decision_id"],
            "trigger": "exit",
            "portfolio_key": DEFAULT_SWING_LAB,
            "laboratory_id": DEFAULT_SWING_LAB,
            "payload": {"failure_cause": "evidence_failure", "pnl": -1},
            "grades": {"pnl": -1},
        }
    ]
    report = build_export_quality_report(
        packets=swing_pkts,
        attributions=swing_attrs,
        laboratory_id=DEFAULT_SWING_LAB,
    )
    assert report["laboratory_id"] == DEFAULT_SWING_LAB
    assert report["regime_tag_fill_rate"] == 1.0
    assert report["provenance_cite_rate"] == 1.0
    assert report["hypothesis_link_rate"] == 1.0
    assert report["failure_cause_tag_rate"] == 1.0

    # Cross-lab pool must refuse
    mixed = swing_pkts + [
        build_packet(
            action="buy",
            symbol="B.NS",
            portfolio_key=DEFAULT_INTRADAY_LAB,
            strategy_tag="sma_cross_rsi",
            reasons_for=["y"],
        )
    ]
    with pytest.raises(LaboratoryContaminationError):
        build_export_quality_report(
            packets=mixed,
            attributions=swing_attrs,
            laboratory_id=DEFAULT_SWING_LAB,
        )
