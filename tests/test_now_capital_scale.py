"""NOW #11 — Capital Scale Lab (virtual only)."""

from __future__ import annotations

from atlas.investment.capital_scale_lab import (
    DEFAULT_BANDS_INR,
    analyze_scale_band,
    answer_capital_scale_chat,
    build_and_persist_capital_scale,
    build_capital_scale_lab,
    detect_capital_scale_query,
    format_capital_scale_evening_lines,
    load_capital_scale,
)
from atlas.investment.next_rupee import build_next_rupee_center
from atlas.investment.capital_allocation import build_challenger_table
from atlas.planner.planner import Intent, Planner


def test_bands_cover_1l_to_2cr():
    assert DEFAULT_BANDS_INR[0] == 100_000
    assert DEFAULT_BANDS_INR[-1] == 20_000_000


def test_analyze_never_mutates_flags():
    row = analyze_scale_band(
        band_inr=10_000_000,
        destination="DEVYANI.NS",
        destination_action="DEPLOY",
        destination_er=0.06,
        destination_er_completeness=0.30,
        live_equity=50_000,
    )
    assert row["mutates_live_capital"] is False
    assert row["real_capital_increase"] is False
    assert row["verdict"] == "SCALE_HOLD"
    assert row["gates"]


def test_scale_ok_when_complete():
    row = analyze_scale_band(
        band_inr=100_000,
        destination="INFY.NS",
        destination_action="DEPLOY",
        destination_er=0.05,
        destination_er_completeness=0.8,
    )
    assert row["verdict"] == "SCALE_OK"


def test_build_persist_and_chat(tmp_path):
    tbl = build_challenger_table(
        holds=[],
        challengers=[
            {
                "symbol": "DEVYANI.NS",
                "score": 0.85,
                "confidence": "high",
                "phase": "active",
                "components": {"momentum": 0.85},
                "rs_vs_benchmark_pct": 4.0,
                "pe": 22.0,
                "industry_pe_median": 30.0,
            }
        ],
        cash=50_000,
        laboratory_id="india_equity_learner",
    )
    nr = build_next_rupee_center(tbl, laboratory_id="india_equity_learner")
    # Force thin completeness for large-band gate
    nr["destination_er_completeness"] = 0.30
    doc = build_and_persist_capital_scale(
        tmp_path,
        laboratory_id="india_equity_learner",
        next_rupee=nr,
        live_cash=50_000,
        live_equity=50_000,
    )
    assert doc["kind"] == "CAPITAL_SCALE_LAB"
    assert doc["mutates_live_capital"] is False
    assert doc["real_capital_increase"] is False
    assert doc["never_orders"] is True
    assert len(doc["scenarios"]) == len(DEFAULT_BANDS_INR)
    loaded = load_capital_scale(tmp_path, "india_equity_learner")
    assert loaded and loaded["next_rupee_destination"] == nr["destination"]
    lines = format_capital_scale_evening_lines(loaded)
    assert any("Capital Scale Lab" in ln for ln in lines)
    assert any("unchanged" in ln.lower() or "virtual" in ln.lower() for ln in lines)

    assert detect_capital_scale_query("What happens at 1 crore?")
    chat = answer_capital_scale_chat(
        "capital scale lab status",
        data_dir=tmp_path,
        laboratory_id="india_equity_learner",
    )
    assert chat and chat["kind"] == "capital_scale"
    assert chat["real_capital_increase"] is False


def test_planner_routes_scale_lab():
    assert Planner().plan("capital scale lab").intent == Intent.MARKET_STATUS
    assert Planner().plan("what happens at 1 crore?").intent == Intent.MARKET_STATUS


def test_empty_next_rupee_still_virtual():
    doc = build_capital_scale_lab(next_rupee=None, laboratory_id="lab")
    assert doc["real_capital_increase"] is False
    assert all(s["mutates_live_capital"] is False for s in doc["scenarios"])
