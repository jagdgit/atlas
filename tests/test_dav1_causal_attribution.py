"""DAV.1 — causal factor helped/hurt/unknown densify (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.causal_attribution import (
    enrich_attributions_for_evening,
    evaluate_causal_factors,
    format_causal_learning_lines,
)
from atlas.investment.decision_attribution import DecisionAttributionStore
from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.reports import format_evening_report, format_learned_today_section


def test_evaluate_causal_helped_hurt_unknown():
    packet = {
        "symbol": "EICHERMOT.NS",
        "feature_contributions": {
            "valuation": 12,
            "technical": 8,
            "research": 4,
            "version": 1,
        },
        "fundamentals": {"pe": 28},
        "valuation": {"margin_of_safety_pct": 10},
        "unknowns": [],
    }
    out = evaluate_causal_factors(
        packet,
        price_change_pct=8.0,
        thesis_correct="yes",
        sector_rel_pct=None,
        news_count=0,
    )
    assert out["version"].startswith("dav.1")
    assert "valuation" in out["helped"]
    assert "technical" in out["helped"]
    assert "sector" in out["unknown"]
    assert "news" in out["unknown"]
    assert "thesis" in out["helped"]
    assert "helped:" in out["narrative"]

    down = evaluate_causal_factors(
        packet,
        price_change_pct=-6.0,
        thesis_correct="no",
        exit_reason_code="stop_loss",
        sector_rel_pct=-3.0,
        news_count=2,
        news_sentiment="negative",
    )
    assert "valuation" in down["hurt"]
    assert "thesis" in down["hurt"]
    assert "sector" in down["hurt"]
    assert "news" in down["hurt"]
    assert "timing" in down["hurt"]


def test_no_pe_valuation_unknown():
    out = evaluate_causal_factors(
        {"feature_contributions": {"technical": 5}, "fundamentals": {}, "valuation": {}},
        price_change_pct=5.0,
    )
    assert "valuation" in out["unknown"]
    assert "valuation_inputs" in out["missing_evidence"]


def test_exit_record_stamps_causal_factors(tmp_path: Path):
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
                "technical": 0.65,
                "macro_theme": 0.5,
                "risk": 0.5,
            },
        },
        fundamentals={"pe": 22},
        valuation={"margin_of_safety_pct": 12},
    )["packet"]
    out = attrs.record(
        decision_id=pkt["decision_id"],
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        trigger="exit",
        pnl=40.0,
        price_change_pct=8.0,
        packet=pkt,
        what_changed={"news_delta": {"count": 0}},
        extra={"exit_reason_code": "sma_crossunder", "why": "signal"},
    )
    attr = out["attribution"]
    payload = attr.get("payload") or {}
    causal = payload.get("causal_factors")
    assert isinstance(causal, dict)
    assert causal.get("narrative")
    assert "helped" in causal or "hurt" in causal or "unknown" in causal


def test_evening_includes_causes_section():
    lines = format_learned_today_section(
        portfolio={
            "attributions": [
                {
                    "symbol": "EICHERMOT.NS",
                    "trigger": "exit",
                    "payload": {
                        "causal_factors": {
                            "helped": ["valuation", "technical"],
                            "hurt": [],
                            "unknown": ["sector", "news"],
                            "narrative": "helped: valuation, technical; unknown: sector, news",
                        }
                    },
                }
            ]
        }
    )
    blob = "\n".join(lines)
    assert "WHAT ATLAS LEARNED" in blob
    assert "valuation" in blob
    assert "What changed today" in blob
    assert "What Atlas is uncertain about" in blob
    assert "What Atlas will do tomorrow" in blob

    assert "none yet" in "\n".join(format_causal_learning_lines([])).lower()


def test_evening_densifies_legacy_attributions_and_mail_body():
    attrs = [
        {
            "symbol": "EICHERMOT.NS",
            "trigger": "exit",
            "decision_id": "d1",
            "grades": {"price_change_pct": 8.0, "thesis_correct": "yes"},
            "payload": {
                "pnl": 40,
                "what_changed": {},
                "feature_drivers": [{"feature": "valuation", "contrib": 10}],
            },
        }
    ]
    densified = enrich_attributions_for_evening(
        attrs,
        packet_by_id={
            "d1": {
                "decision_id": "d1",
                "symbol": "EICHERMOT.NS",
                "feature_contributions": {"valuation": 10, "technical": 5},
                "fundamentals": {"pe": 20},
                "valuation": {"margin_of_safety_pct": 8},
            }
        },
    )
    assert densified[0]["payload"]["causal_factors"]["narrative"]
    assert densified[0]["payload"]["causal_factors"].get("display_only") is True

    plan = {
        "as_of": "2026-08-09",
        "phase": "learning",
        "confidence": "very_low",
        "summary": "test plan",
        "candidates": [],
        "avoids": [],
        "notes": [],
    }
    _subj, body = format_evening_report(
        plan=plan,
        portfolio={
            "portfolio_key": "india_equity_learner",
            "cash": 10000,
            "positions": [],
            "attributions": densified,
            "observations": [{"kind": "market_event"}],
            "evolution": {"done_revisits": 8, "pending_revisits": 16},
            "fundamentals_coverage": {"with_pe": 18, "symbols": 20},
            "meta_learning": {"intelligence_score": 50.2},
        },
    )
    assert "WHAT ATLAS LEARNED TODAY" in body
    assert "WHAT ATLAS LEARNED" in body
    assert "What Atlas will do tomorrow" in body
    assert "EICHERMOT" in body