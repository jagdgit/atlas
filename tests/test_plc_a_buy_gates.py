"""PLC.A — fund sanity + thesis trigger buy gates (hermetic)."""

from __future__ import annotations

from atlas.investment.plc_buy_gates import (
    evaluate_fundamental_sanity,
    evaluate_plc_a_buy,
    extract_thesis_trigger,
    plc_a_enabled,
)


def test_plc_a_enabled_learner_default():
    assert plc_a_enabled({}, "india_equity_learner") is True
    assert plc_a_enabled({}, "equity_intraday_learner") is False
    assert plc_a_enabled({}, "india_fno_learner") is False
    assert plc_a_enabled({}, "some_other_book") is False
    assert plc_a_enabled({"plc_a_gates": False}, "india_equity_learner") is False
    assert plc_a_enabled({"plc_a_gates": True}, "manual") is True
    assert plc_a_enabled({"plc_a_gates": True}, "equity_intraday_learner") is True


def test_fundamental_sanity_requires_pe_roe_de_sector():
    bad = evaluate_fundamental_sanity({"pe": 20}, sector=None)
    assert bad["ok"] is False
    assert "roe" in bad["missing"]
    assert "debt_to_equity" in bad["missing"]
    assert "sector" in bad["missing"]

    good = evaluate_fundamental_sanity(
        {"pe": 18.0, "roe": 0.22, "debt_to_equity": 30.0},
        sector="Healthcare",
    )
    assert good["ok"] is True


def test_thesis_trigger_rejects_boilerplate():
    weak = extract_thesis_trigger(
        awareness={"thesis": {"summary": "Researched (MVR/coverage)"}},
        engine_why="SMA10 crossed SMA30; RSI 55",
    )
    assert weak["ok"] is False
    assert weak["code"] == "thesis_trigger_missing"

    strong = extract_thesis_trigger(
        awareness={
            "thesis_distinctiveness": {
                "value_drivers": [
                    "Hospital occupancy expansion and pricing power in metros"
                ]
            }
        },
        engine_why="SMA cross",
    )
    assert strong["ok"] is True
    assert "occupancy" in (strong["trigger"] or "").lower()


def test_evaluate_plc_a_blocks_and_allows():
    blocked = evaluate_plc_a_buy(
        fundamentals=None,
        awareness={"thesis": {"id": "t1", "summary": "researched"}},
        instrument_sector=None,
        engine_why="SMA10 > SMA30",
    )
    assert blocked["allowed"] is False
    assert any("fundamentals" in b or "sector" in b for b in blocked["blocks"])

    allowed = evaluate_plc_a_buy(
        fundamentals={"pe": 22.0, "roe": 15.0, "debt_to_equity": 40.0},
        awareness={
            "thesis": {
                "id": "t1",
                "summary": "Premium motorcycle demand and pricing power remain strong",
            }
        },
        instrument_sector="Automobile",
        engine_why="SMA10 > SMA30",
    )
    assert allowed["allowed"] is True
    assert allowed["thesis_trigger"]
    assert allowed["strategy_tag"] == "sma_cross_rsi"
