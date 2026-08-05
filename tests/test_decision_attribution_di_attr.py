"""DI.Attr outcome attribution + Replay — hermetic."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_attribution import (
    DecisionAttributionStore,
    grade_attribution,
    may_update_priors,
)
from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.reports import format_evening_report
from atlas.investment.thesis_tracker import close_with_attribution, load_priors


def test_hard_rule_blocks_priors_on_market_f_decision_ab():
    grades = {
        "decision_quality": "A",
        "market_quality": "F",
    }
    assert may_update_priors(grades) is False
    assert may_update_priors({"decision_quality": "C", "market_quality": "F"}) is True
    assert may_update_priors({"decision_quality": "A", "market_quality": "C"}) is True


def test_grade_attribution_buy_crash(tmp_path: Path):
    packets = DecisionPacketStore(data_dir=tmp_path)
    out = packets.record(
        action="buy",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        reasons_for=["SMA"],
        prices={"mark": 100, "fill_price": 100, "filled_qty": 2, "fees": 5},
        investment_score={
            "overall": 0.7,
            "axes": {
                "financial_health": 0.6,
                "valuation": 0.6,
                "technical": 0.8,
                "macro_theme": 0.5,
                "risk": 0.5,
            },
        },
        fundamentals={"pe": 20, "fcf": 1, "roe": 0.2},
    )
    packet = out["packet"]
    grades = grade_attribution(packet, pnl=-50, price_change_pct=-15.0, trigger="exit")
    assert grades["market_quality"] in {"E", "F", "D"}
    assert grades["decision_quality"] in {"A", "B", "C"}
    if grades["decision_quality"] in {"A", "B"} and grades["market_quality"] == "F":
        assert grades["may_update_priors"] is False


def test_attribution_store_and_replay(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    attrs = DecisionAttributionStore(
        data_dir=tmp_path, packet_store=packets, timeline=timeline
    )
    pkt = packets.record(
        action="buy",
        symbol="INFY.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-01",
        reasons_for=["signal"],
        prices={"mark": 1500, "fill_price": 1500, "filled_qty": 1},
    )["packet"]
    did = pkt["decision_id"]
    result = attrs.record(
        decision_id=did,
        symbol="INFY.NS",
        portfolio_key="india_equity_learner",
        trigger="exit",
        checkpoint="exit",
        packet=pkt,
        pnl=-20,
        price_change_pct=-12.0,
    )
    assert result["attribution"]["grades"]["market_quality"]
    assert Path(result["mirror_path"]).is_file()

    replay = attrs.build_replay(did)
    assert replay["packet"]["decision_id"] == did
    assert replay["latest_attribution"] is not None


def test_priors_weight_skip(tmp_path: Path):
    grades = grade_attribution(
        {
            "action": "buy",
            "meta": {"completeness": 0.95},
            "reasons_for": ["a", "b"],
            "unknowns": [],
            "feature_contributions": {"technical": 8, "valuation": 4},
            "gates": {},
            "prices": {"fill_price": 100, "filled_qty": 1, "fees": 1},
        },
        price_change_pct=-20.0,
        pnl=-100,
    )
    grades["decision_quality"] = "A"
    grades["market_quality"] = "F"
    grades["may_update_priors"] = False

    close_with_attribution(
        tmp_path,
        "TESTCO.NS",
        program_id="market_intelligence",
        result="falsified",
        pnl=-100,
        note="crash",
        di_grades=grades,
    )
    priors = load_priors(tmp_path, "market_intelligence")
    deltas = priors.get("weight_deltas") or {}
    assert int(deltas.get("di_attr_skipped") or 0) >= 1
    assert float(deltas.get("ranking_penalty_global") or 0) == 0.0


def test_evening_attribution_section():
    _subj, body = format_evening_report(
        plan={
            "as_of": "2026-08-05",
            "summary": "x",
            "phase": "learning",
            "confidence": "low",
        },
        portfolio={
            "cash": 1,
            "attributions": [
                {
                    "symbol": "EICHERMOT.NS",
                    "trigger": "exit",
                    "grades": {
                        "decision_quality": "B",
                        "market_quality": "F",
                        "execution_quality": "B",
                        "portfolio_quality": "C",
                        "thesis_correct": "no",
                        "may_update_priors": False,
                        "priors_block_reason": "market_quality=F with decision_quality A/B",
                    },
                }
            ],
        },
    )
    assert "Outcome attribution" in body
    assert "BLOCKED" in body
