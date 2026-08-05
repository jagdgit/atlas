"""DI.3 staged dashboards + sample gates — hermetic."""

from __future__ import annotations

from atlas.investment.di_dashboards import (
    build_di_dashboards,
    edge_metrics_for_lane,
    format_di_dashboard_section,
    sample_tier,
)
from atlas.investment.reports import format_evening_report


def test_sample_tiers():
    assert sample_tier(0) == "hidden"
    assert sample_tier(29) == "hidden"
    assert sample_tier(30) == "provisional"
    assert sample_tier(99) == "provisional"
    assert sample_tier(100) == "usable"
    assert sample_tier(299) == "usable"
    assert sample_tier(300) == "trusted"


def test_edge_hidden_under_30():
    exits = [{"pnl": 10.0} for _ in range(10)] + [{"pnl": -5.0} for _ in range(5)]
    m = edge_metrics_for_lane(exits, tier=sample_tier(len(exits)))
    assert m["edge_visible"] is False
    assert m.get("win_rate") is None
    assert "hidden" in (m.get("note") or "").lower() or m["tier"] == "hidden"


def test_edge_visible_at_30_and_never_mixed():
    wins = [{"pnl": 10.0} for _ in range(20)]
    losses = [{"pnl": -5.0} for _ in range(10)]
    m = edge_metrics_for_lane(wins + losses, tier="provisional")
    assert m["edge_visible"] is True
    assert m["provisional"] is True
    assert m["win_rate"] == round(20 / 30, 4)
    assert m["n_closed"] == 30


def test_build_dashboards_separates_strategy_tags():
    packets = [
        {
            "decision_id": "a1",
            "strategy_tag": "sma_cross_rsi",
            "action": "buy",
            "meta": {"completeness": 0.8},
            "observation_ids": ["o1"],
        },
        {
            "decision_id": "b1",
            "strategy_tag": "next_alternative",
            "action": "buy",
            "meta": {"completeness": 0.5},
            "observation_ids": [],
        },
    ]
    # 30 exits for sma, 5 for next_alternative
    attributions = []
    for i in range(30):
        attributions.append(
            {
                "decision_id": "a1",
                "trigger": "exit",
                "grades": {"pnl": 5.0 if i % 2 == 0 else -3.0},
                "payload": {"pnl": 5.0 if i % 2 == 0 else -3.0},
            }
        )
    for i in range(5):
        attributions.append(
            {
                "decision_id": "b1",
                "trigger": "exit",
                "grades": {"pnl": 1.0},
                "payload": {"pnl": 1.0},
            }
        )
    doc = build_di_dashboards(
        portfolio_key="india_equity_learner",
        trading_kpis={"cash": 1000, "equity": 5000, "fills_today": 2},
        packets=packets,
        attributions=attributions,
        evolution={"pending_revisits": 3, "done_revisits": 1},
        observations=[{"id": "o1"}],
        fundamentals_coverage={
            "symbols": 2,
            "with_pe": 0,
            "with_fcf": 0,
            "learner_gaps": {"symbols_with_gaps": 2, "symbols_checked": 2},
        },
        ist_date="2026-08-05",
    )
    lanes = doc["dashboards"]["D2"]["strategy_lanes"]
    assert lanes["sma_cross_rsi"]["tier"] == "provisional"
    assert lanes["sma_cross_rsi"]["edge_visible"] is True
    assert lanes["next_alternative"]["tier"] == "hidden"
    assert lanes["next_alternative"]["edge_visible"] is False
    assert doc["dashboards"]["D6"]["metrics"]["avg_packet_completeness"] == 0.65
    assert doc["dashboards"]["D6"]["metrics"]["observation_citation_rate"] == 0.5


def test_evening_includes_di_dashboards():
    doc = build_di_dashboards(
        portfolio_key="india_equity_learner",
        trading_kpis={"equity": 50000, "cash": 10000, "day_pnl": 100},
        packets=[],
        attributions=[],
        ist_date="2026-08-05",
    )
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={"cash": 1, "di_dashboards": doc},
    )
    assert "DI dashboards" in body
    assert "D6 intelligence" in body
    lines = format_di_dashboard_section(doc)
    assert any("D3 book" in ln for ln in lines)
