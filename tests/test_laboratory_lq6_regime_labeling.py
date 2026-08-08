"""LQ.6 — regime labeling on closed rows (unknown OK; never invent)."""

from __future__ import annotations

from atlas.investment.decision_attribution import DecisionAttributionStore
from atlas.investment.decision_packets import (
    build_packet,
    empty_market_snapshot,
    normalize_regime_tags,
    regime_tags_for_closed_row,
    resolve_regime_tags,
    stamp_regime_on_snapshot,
)
from atlas.investment.laboratory import DEFAULT_SWING_LAB
from atlas.investment.ml_export import build_export_quality_report, row_from_packet_attr


def test_normalize_drops_invented_and_maps_aliases():
    assert normalize_regime_tags(["Bullish", "risk_on", "HIGH-VOL"]) == [
        "bull",
        "high_vol",
    ]
    assert normalize_regime_tags([]) == []
    assert normalize_regime_tags(["unknown"]) == ["unknown"]


def test_resolve_defaults_unknown_never_from_pnl():
    assert resolve_regime_tags(explicit=None) == ["unknown"]
    assert resolve_regime_tags(explicit=["made_up"]) == ["unknown"]
    assert resolve_regime_tags(
        explicit=["unknown"],
        macro_observations=[
            {
                "kind": "macro_event",
                "payload": {"regime_tags": ["geopolitical"]},
            }
        ],
    ) == ["geopolitical"]


def test_stamp_and_build_packet_carry_unknown():
    snap = stamp_regime_on_snapshot(empty_market_snapshot())
    assert snap["regime_tags"] == ["unknown"]
    pkt = build_packet(
        action="buy",
        symbol="RELIANCE",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="swing",
        market_snapshot=empty_market_snapshot(),
    )
    assert pkt["market_snapshot"]["regime_tags"] == ["unknown"]


def test_closed_row_export_fills_unknown_for_legacy_empty():
    pkt = {
        "decision_id": "d1",
        "laboratory_id": DEFAULT_SWING_LAB,
        "portfolio_key": DEFAULT_SWING_LAB,
        "symbol": "TCS",
        "action": "buy",
        "strategy_tag": "swing",
        "market_snapshot": {"regime_tags": [], "session": "nse_equity"},
        "feature_contributions": {},
        "confidence_breakdown": {},
        "meta": {},
        "unknowns": [],
        "observation_ids": [],
        "plan_link": {},
        "expected": {},
    }
    attr = {
        "id": "a1",
        "decision_id": "d1",
        "trigger": "exit",
        "laboratory_id": DEFAULT_SWING_LAB,
        "portfolio_key": DEFAULT_SWING_LAB,
        "grades": {"thesis_correct": "yes", "pnl": 1.0},
        "payload": {},
    }
    assert regime_tags_for_closed_row(pkt, attr) == ["unknown"]
    row = row_from_packet_attr(pkt, attr)
    assert row["features"]["regime_tags"] == ["unknown"]
    assert row["labels"]["regime_tags"] == ["unknown"]


def test_closed_row_preserves_evidence_tags():
    pkt = {
        "decision_id": "d2",
        "laboratory_id": DEFAULT_SWING_LAB,
        "portfolio_key": DEFAULT_SWING_LAB,
        "symbol": "INFY",
        "action": "buy",
        "strategy_tag": "swing",
        "market_snapshot": {"regime_tags": ["rate_cut", "sideways"]},
        "feature_contributions": {},
        "confidence_breakdown": {},
        "meta": {},
        "unknowns": [],
        "observation_ids": [],
        "plan_link": {},
        "expected": {},
    }
    attr = {
        "id": "a2",
        "decision_id": "d2",
        "trigger": "exit",
        "laboratory_id": DEFAULT_SWING_LAB,
        "grades": {"thesis_correct": "no", "pnl": -1.0},
        "payload": {},
    }
    assert regime_tags_for_closed_row(pkt, attr) == ["rate_cut", "sideways"]


def test_export_quality_closed_regime_fill_rate():
    lab = DEFAULT_SWING_LAB
    packets = [
        {
            "decision_id": "d1",
            "laboratory_id": lab,
            "portfolio_key": lab,
            "market_snapshot": {"regime_tags": []},
        },
        {
            "decision_id": "d2",
            "laboratory_id": lab,
            "portfolio_key": lab,
            "market_snapshot": {"regime_tags": ["bear"]},
        },
    ]
    attrs = [
        {
            "decision_id": "d1",
            "trigger": "exit",
            "laboratory_id": lab,
            "portfolio_key": lab,
            "payload": {},
            "grades": {},
        },
        {
            "decision_id": "d2",
            "trigger": "exit",
            "laboratory_id": lab,
            "portfolio_key": lab,
            "payload": {},
            "grades": {},
        },
    ]
    report = build_export_quality_report(
        packets=packets, attributions=attrs, laboratory_id=lab
    )
    assert report["closed_regime_tag_fill_rate"] == 1.0
    assert report["closed_regime_tags_present"] == 2
    assert report["closed_regime_unknown_only"] == 1
    assert report["regime_tag_fill_rate"] == 0.5  # only d2 has concrete/normalized tags


def test_attribution_record_stamps_regime_on_exit(tmp_path):
    store = DecisionAttributionStore(data_dir=tmp_path)
    pkt = build_packet(
        action="buy",
        symbol="HDFCBANK",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="swing",
        market_snapshot=stamp_regime_on_snapshot(
            empty_market_snapshot(),
            explicit=["election"],
        ),
    )
    out = store.record(
        decision_id=pkt["decision_id"],
        symbol="HDFCBANK",
        portfolio_key=DEFAULT_SWING_LAB,
        trigger="exit",
        packet=pkt,
        pnl=-2.0,
        price_change_pct=-3.0,
    )
    doc = out["attribution"]
    assert doc["payload"]["regime_tags"] == ["election"]
    assert doc["payload"]["extra"]["regime_tags"] == ["election"]
