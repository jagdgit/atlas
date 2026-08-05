"""DI.6 meta-learning + Intelligence Dashboard enrichment — hermetic."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.investment.meta_learning import (
    build_meta_learning_digest,
    enrich_d6_metrics,
    format_meta_learning_section,
    week_key,
)
from atlas.investment.reports import format_evening_report, format_weekly_research_report


def test_week_key_shape():
    assert week_key().count("-W") == 1


def test_meta_learning_feature_and_proposals():
    good = build_packet(
        action="buy",
        symbol="A.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        reasons_for=["plan"],
        plan_link={"in_daily_plan": True, "rank": 1},
        investment_score={
            "axes": {"business": 0.8, "valuation": 0.7, "technical": 0.6}
        },
    )
    poor = build_packet(
        action="buy",
        symbol="B.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="next_alternative",
        reasons_for=[],
        plan_link={"in_daily_plan": False},
    )
    poor["unknowns"] = ["pe_missing", "fcf_missing"]
    attrs = [
        {
            "decision_id": good["decision_id"],
            "grades": {"decision_quality": "A", "may_update_priors": True},
        },
        {
            "decision_id": poor["decision_id"],
            "grades": {"decision_quality": "F", "may_update_priors": False},
        },
    ]
    digest = build_meta_learning_digest(
        portfolio_key="india_equity_learner",
        packets=[good, poor],
        attributions=attrs,
        process_proxies={
            "process_score": 7.0,
            "counts": {"fomo": 1, "plan_violation": 1},
        },
        evolution={"pending_revisits": 2, "done_revisits": 3},
        fundamentals_gaps={"symbols_with_gaps": 4},
        week="2026-W32",
    )
    assert digest["version"] == "di.meta.1"
    assert digest["intelligence_score"] is not None
    assert digest["answers"]["atlas"]["incomplete_packets_pct"] is not None
    assert digest["proposals"]
    assert any(p.get("kind") == "fundamentals_coverage" for p in digest["proposals"])
    assert "silent" in (digest.get("honesty") or "").lower()


def test_enrich_d6_and_evening():
    meta = build_meta_learning_digest(
        packets=[],
        attributions=[],
        process_proxies={"process_score": 9.0, "counts": {}},
        evolution={"pending_revisits": 0, "done_revisits": 1},
        week="2026-W32",
    )
    d6 = enrich_d6_metrics(
        {"avg_packet_completeness": 0.8},
        meta=meta,
        process_proxies={"process_score": 9.0},
    )
    assert d6.get("intelligence_score") is not None
    assert d6.get("process_score") == 9.0
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={"cash": 1, "meta_learning": meta},
    )
    assert "Meta-learning" in body
    lines = format_meta_learning_section(meta)
    assert any("intelligence_score" in ln or "Score" in ln or "Week" in ln for ln in lines)


def test_weekly_includes_meta():
    meta = build_meta_learning_digest(
        packets=[],
        attributions=[],
        week="2026-W32",
        process_proxies={"process_score": 8.0, "counts": {}},
    )
    _subj, body = format_weekly_research_report(
        digest={"count": 0, "studied": [], "meta_learning": meta},
        program_id="market_intelligence",
    )
    assert "Meta-learning" in body
    assert "proposals" in body.lower() or "→" in body
