"""OI-EXP0 / OI-RLD0 — experience integrity (dedupe HOLDs + truth metrics)."""

from __future__ import annotations

from atlas.investment.experience_integrity import (
    build_experience_metrics,
    build_maturity_split,
    classify_experience_kind,
    fingerprint,
    format_experience_metrics_lines,
    material_decision_state,
    should_record_packet,
)
from atlas.investment.reports import (
    format_learned_today_section,
    format_ranking_movements_section,
    ranking_trust_status,
)


def test_routine_hold_limited_once_per_day():
    existing = [
        {
            "symbol": "EICHERMOT.NS",
            "action": "hold",
            "strategy_tag": "switch_blocked_cold_start",
            "meta": {
                "ist_day": "2026-08-09",
                "experience_fingerprint": fingerprint(
                    portfolio_key="india_equity_learner",
                    symbol="EICHERMOT.NS",
                    action="hold",
                    strategy_tag="switch_blocked_cold_start",
                    ist_day_s="2026-08-09",
                ),
            },
        }
    ]
    ok, reason = should_record_packet(
        existing,
        portfolio_key="india_equity_learner",
        symbol="EICHERMOT.NS",
        action="hold",
        strategy_tag="switch_blocked_cold_start",
        ist_day_s="2026-08-09",
    )
    assert ok is False
    assert "duplicate" in reason

    ok2, _ = should_record_packet(
        existing,
        portfolio_key="india_equity_learner",
        symbol="CIPLA.NS",
        action="hold",
        strategy_tag="switch_blocked_cold_start",
        ist_day_s="2026-08-09",
    )
    assert ok2 is True

    ok_buy, reason_buy = should_record_packet(
        existing,
        portfolio_key="india_equity_learner",
        symbol="EICHERMOT.NS",
        action="buy",
        strategy_tag="sma_cross_rsi",
        ist_day_s="2026-08-09",
    )
    assert ok_buy is True
    assert reason_buy == "material_or_trade"


def test_rld_three_tier_metrics_collapse_hold_spam():
    """100 identical HOLDs → many evaluations, few unique states, 0 experiences."""
    packets = []
    for i in range(100):
        packets.append(
            {
                "decision_id": f"h{i}",
                "symbol": f"SYM{i % 18}.NS",
                "action": "hold",
                "strategy_tag": "switch_blocked_cold_start",
                "portfolio_key": "india_equity_learner",
                "reasons_against": ["fcf_missing"],
                "meta": {"ist_day": "2026-08-09"},
            }
        )
    doc = build_experience_metrics(
        packets=packets,
        attributions=[
            {
                "trigger": "revisit",
                "payload": {
                    "causal_factors": {
                        "helped": [],
                        "hurt": [],
                        "unknown": ["sector", "news"],
                    }
                },
            }
        ]
        * 8,
        observations=[{"id": "o1"}],
        evolution={"done_revisits": 8, "pending_revisits": 16},
        positions=[{"symbol": "SYM0.NS", "qty": 2}],
        fills_buy=0,
        fills_sell=0,
    )
    assert doc["decision_evaluations"] == 100
    assert doc["unique_decision_states"] == 1  # same hold+tag+reason
    assert doc["actual_fills"] == 0
    assert doc["closed_trades"] == 0
    assert doc["trading_experiences"] == 0
    assert doc["attributed_all_unknown"] == 8
    assert doc["revisits"] == 8
    blob = "\n".join(format_experience_metrics_lines(doc))
    assert "Decision evaluations" in blob
    assert "Unique decision states" in blob
    assert "Trading experiences" in blob
    assert "Activity inflation" in blob


def test_material_state_keeps_buys_distinct():
    a = {
        "action": "buy",
        "symbol": "A.NS",
        "strategy_tag": "sma_cross_rsi",
        "reasons_for": ["cross"],
    }
    b = {
        "action": "buy",
        "symbol": "B.NS",
        "strategy_tag": "sma_cross_rsi",
        "reasons_for": ["cross"],
    }
    assert material_decision_state(a) != material_decision_state(b)


def test_evening_shows_learning_dataset_truth():
    lines = format_learned_today_section(
        portfolio={
            "decisions": [
                {
                    "action": "hold",
                    "symbol": "X.NS",
                    "strategy_tag": "switch_blocked_cold_start",
                    "decision_id": "h1",
                    "reasons_against": ["fcf_missing"],
                }
            ]
            * 5,
            "positions": [{"symbol": "X.NS", "qty": 1}],
            "evolution": {"done_revisits": 2, "pending_revisits": 10},
            "observations": [{"id": "o1"}],
        }
    )
    blob = "\n".join(lines)
    assert "Learning dataset truth" in blob
    assert "Decision evaluations" in blob
    assert "Unique decision states" in blob
    assert "Trading experiences" in blob


def test_ranking_not_yet_trustworthy_when_cold():
    trust = ranking_trust_status(
        triage={
            "ok": True,
            "coverage": {
                "price_coverage_pct": 12.0,
                "acceleration_status": "pending_history",
            },
        },
        plan={"phase": "learning", "confidence": "very_low"},
        fundamentals_coverage={"with_pe": 18, "symbols": 18},
    )
    assert trust["trustworthy"] is False
    assert trust["status"] == "NOT YET TRUSTWORTHY"

    lines = format_ranking_movements_section(
        ranked=[{"symbol": "AAA.NS", "rank": 1, "score": 0.5, "confidence": "low"}],
        triage={
            "ok": True,
            "coverage": {
                "price_coverage_pct": 12.0,
                "acceleration_status": "pending_history",
            },
        },
        plan={"phase": "learning", "confidence": "very_low"},
        fundamentals_coverage={"with_pe": 18, "symbols": 18},
    )
    blob = "\n".join(lines)
    assert "NOT YET TRUSTWORTHY" in blob
    assert "Provisional ranking" in blob
    assert "AAA.NS" in blob
    assert "Price coverage" in blob


def test_classify_kinds():
    assert classify_experience_kind(action="buy") == "investment_decision"
    assert (
        classify_experience_kind(
            action="hold", strategy_tag="switch_blocked_cold_start"
        )
        == "hold_review"
    )
    assert classify_experience_kind(action="hold", trigger="revisit") == "revisit"


def test_maturity_split_trading_near_zero_without_outcomes():
    exp = build_experience_metrics(
        packets=[
            {
                "action": "hold",
                "strategy_tag": "switch_blocked_cold_start",
                "symbol": "CIPLA.NS",
            }
        ]
        * 20,
        attributions=[
            {
                "trigger": "revisit",
                "payload": {
                    "causal_factors": {
                        "helped": [],
                        "hurt": [],
                        "unknown": ["news", "sector"],
                    }
                },
            }
        ]
        * 8,
    )
    mat = build_maturity_split(
        experience_metrics=exp,
        system_score=46.5,
        genealogy_pct=0.0,
        readiness_grade="B",
        durable_bars_ok=True,
    )
    assert mat["system_maturity"] == 46.5
    assert mat["trading_evidence_maturity"] <= 5.0
    assert mat["strategy_evidence"] == "insufficient"
    assert "all-unknown" in mat["attribution_maturity"]
    assert mat["data_readiness"] == "B"
