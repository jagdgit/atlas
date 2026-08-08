"""LQ.4 — primary root cause + top feature drivers on material exits."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_attribution import (
    DecisionAttributionStore,
    format_attribution_section,
    infer_primary_root_cause,
    is_material_exit,
    rank_feature_drivers,
)
from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.learning_intelligence import (
    feature_driver_histogram,
    failure_cause_histogram,
)


def test_rank_feature_drivers_orders_by_abs():
    ranked = rank_feature_drivers(
        {"technical": 12, "valuation": -20, "macro": 0, "news": 3, "version": 1},
        top_n=3,
    )
    assert [r["feature"] for r in ranked] == ["valuation", "technical", "news"]
    assert ranked[0]["contrib"] == -20


def test_infer_root_cause_regime_and_research():
    grades_crash = {
        "market_quality": "F",
        "decision_quality": "A",
        "thesis_correct": "no",
        "price_change_pct": -15.0,
        "notes": ["regime-size move -15.0%"],
    }
    assert (
        infer_primary_root_cause({}, grades_crash)
        == "market_regime_failure"
    )

    packet = {
        "action": "buy",
        "gates": {"research": {"allowed": False}},
        "meta": {"completeness": 0.8},
        "unknowns": [],
    }
    grades_block = {
        "market_quality": "C",
        "decision_quality": "D",
        "thesis_correct": "no",
        "notes": ["bought through research block"],
        "price_change_pct": -3.0,
    }
    assert (
        infer_primary_root_cause(packet, grades_block)
        == "research_failure"
    )

    # Explicit operator cause wins later in record(); infer returns None on win
    grades_win = {
        "market_quality": "B",
        "decision_quality": "B",
        "thesis_correct": "yes",
        "price_change_pct": 5.0,
        "notes": [],
    }
    assert infer_primary_root_cause({}, grades_win) is None


def test_material_exit_gate():
    assert is_material_exit(trigger="revisit", price_change_pct=-10) is False
    assert is_material_exit(trigger="exit", price_change_pct=-3.0) is True
    assert is_material_exit(
        trigger="exit", price_change_pct=0.5, grades={"thesis_correct": "no"}
    )


def test_exit_record_densifies_cause_and_drivers(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    attrs = DecisionAttributionStore(
        data_dir=tmp_path, packet_store=packets, timeline=timeline
    )
    pkt = packets.record(
        action="buy",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-01",
        reasons_for=["signal"],
        prices={"mark": 100, "fill_price": 100, "filled_qty": 2},
        investment_score={
            "overall": 0.7,
            "axes": {
                "financial_health": 0.7,
                "valuation": 0.8,
                "technical": 0.9,
                "macro_theme": 0.4,
                "risk": 0.5,
            },
        },
        fundamentals={"pe": 20, "fcf": 1, "roe": 0.2},
    )["packet"]
    assert pkt.get("feature_contributions")

    out = attrs.record(
        decision_id=pkt["decision_id"],
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        trigger="exit",
        checkpoint="exit",
        packet=pkt,
        pnl=-40.0,
        price_change_pct=-12.0,
        extra={"why": "stop"},
        failure_cause=None,
    )
    attr = out["attribution"]
    payload = attr["payload"]
    assert payload.get("failure_cause") in {
        "market_regime_failure",
        "research_failure",
    }
    assert payload.get("feature_drivers")
    assert payload["feature_drivers"][0]["feature"]
    assert payload["extra"].get("material_exit") is True
    assert payload["extra"].get("exit_reason") == "stop"

    # Explicit cause wins
    out2 = attrs.record(
        decision_id=pkt["decision_id"],
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        trigger="exit",
        packet=pkt,
        pnl=-10,
        price_change_pct=-5.0,
        failure_cause="execution_failure",
    )
    assert out2["attribution"]["payload"]["failure_cause"] == "execution_failure"

    lines = format_attribution_section([attr])
    text = "\n".join(lines)
    assert "Root cause:" in text
    assert "Drivers:" in text

    hist = failure_cause_histogram([attr])
    assert sum(hist.values()) >= 1
    dhist = feature_driver_histogram([attr])
    assert sum(dhist.values()) >= 1
