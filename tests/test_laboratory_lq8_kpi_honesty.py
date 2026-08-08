"""LQ.8 — KPI Stage A/B honesty (no Stage C/D vanity early)."""

from __future__ import annotations

from atlas.investment.di_dashboards import (
    build_di_dashboards,
    edge_metrics_for_lane,
    format_di_dashboard_section,
    kpi_stage_for_tier,
    stage_c_metrics_allowed,
)
from atlas.investment.reports import format_evening_report


def test_kpi_stage_maps_from_tier():
    assert kpi_stage_for_tier("hidden") == "A"
    assert kpi_stage_for_tier("provisional") == "B"
    assert kpi_stage_for_tier("usable") == "B"
    assert kpi_stage_for_tier("trusted") == "C"
    assert stage_c_metrics_allowed("usable") is False
    assert stage_c_metrics_allowed("trusted") is True


def test_hidden_lane_is_stage_a_only():
    m = edge_metrics_for_lane([{"pnl": 1.0}] * 5, tier="hidden")
    assert m["kpi_stage"] == "A"
    assert m["edge_visible"] is False
    assert m["stage_c_visible"] is False
    assert m.get("win_rate") is None
    assert m.get("stage3_sharpe") is None


def test_provisional_is_stage_b_no_sharpe():
    m = edge_metrics_for_lane([{"pnl": 1.0}] * 20 + [{"pnl": -1.0}] * 10, tier="provisional")
    assert m["kpi_stage"] == "B"
    assert m["edge_visible"] is True
    assert m["win_rate"] is not None
    assert m["stage_c_visible"] is False
    assert m["stage3_sharpe"] is None
    assert "Stage C" in (m.get("stage3_note") or "")


def test_trusted_stage_c_eligible_but_never_invents_sharpe():
    m = edge_metrics_for_lane([{"pnl": 1.0}] * 300, tier="trusted")
    assert m["kpi_stage"] == "C"
    assert m["stage_c_visible"] is True
    assert m["stage3_sharpe"] is None
    assert m["stage3_sortino"] is None
    assert m["stage_d_visible"] is False


def test_dashboard_doc_kpi_staging_honesty():
    packets = [
        {
            "decision_id": "a1",
            "strategy_tag": "sma_cross_rsi",
            "action": "buy",
            "meta": {"completeness": 0.8},
            "observation_ids": ["o1"],
        }
    ]
    attributions = [
        {
            "decision_id": "a1",
            "trigger": "exit",
            "grades": {"pnl": 1.0},
            "payload": {"pnl": 1.0},
        }
        for _ in range(10)
    ]
    doc = build_di_dashboards(
        portfolio_key="india_equity_learner",
        trading_kpis={"cash": 1000, "equity": 5000},
        packets=packets,
        attributions=attributions,
        ist_date="2026-08-08",
    )
    assert doc["lq"] == "lq.8"
    assert doc["kpi_staging"]["stage_a_always"] is True
    assert doc["kpi_staging"]["stage_b_visible"] is False
    assert doc["kpi_staging"]["stage_c_visible"] is False
    assert doc["kpi_staging"]["stage_d_visible"] is False
    assert doc["dashboards"]["D1"]["kpi_stage"] == "A"
    assert doc["dashboards"]["D3"]["kpi_stage"] == "A"
    assert doc["dashboards"]["D6"]["kpi_stage"] == "A"
    lane = doc["dashboards"]["D2"]["strategy_lanes"]["sma_cross_rsi"]
    assert lane["kpi_stage"] == "A"
    assert lane["stage3_sharpe"] is None
    summary = doc["strategy_lane_summary"]["sma_cross_rsi"]
    assert summary["win_rate"] is None  # edge hidden
    assert summary["stage3_sharpe"] is None


def test_mail_labels_stages_and_hides_c_d():
    doc = build_di_dashboards(
        portfolio_key="india_equity_learner",
        trading_kpis={"equity": 50000, "cash": 10000, "day_pnl": 100},
        packets=[],
        attributions=[],
        ist_date="2026-08-08",
    )
    lines = format_di_dashboard_section(doc)
    blob = "\n".join(lines)
    assert "LQ.8" in blob
    assert "Stage A" in blob
    assert "Stage C/D" in blob
    assert "Sharpe" not in blob or "not invented" in blob or "stub" in blob.lower()
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-08", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={"cash": 1, "di_dashboards": doc},
    )
    assert "LQ.8" in body
    assert "Stage A · D6 intelligence" in body
