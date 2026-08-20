"""LOOP0 L1 — versioned E[R] prototype (hermetic)."""

from __future__ import annotations

from atlas.investment.expected_return_prototype import (
    ER_BASIS,
    ER_MODEL,
    compute_prototype_er,
    expected_block_from_metrics,
    overlay_fundamentals_for_er,
)
from atlas.investment.opportunity_switch import (
    REASON_BLOCKED_COLD_START,
    REASON_BLOCKED_MISSING_ER,
    estimate_opportunity_metrics,
    expected_return_from_row,
    review_hold_vs_challengers,
)


def test_learning_row_emits_versioned_number():
    row = {
        "symbol": "CIPLA.NS",
        "score": 0.7,
        "phase": "learning",
        "confidence": "very_low",
        "components": {"momentum": 0.8},
    }
    er = expected_return_from_row(row)
    assert er is not None
    snap = compute_prototype_er(row)
    assert snap["er_model"] == ER_MODEL
    assert snap["er_basis"] == ER_BASIS
    assert snap["expected_return"] == er
    assert 0.0 < snap["er_completeness"] < 0.6
    assert snap["confidence"] == 0.35
    assert "momentum" in snap["present_terms"]
    assert "belief" in snap["missing_terms"]
    assert snap["er_inputs"]["terms"]["momentum"]["source"] == "components.momentum"
    m = estimate_opportunity_metrics(row)
    assert m["computable"] is True
    assert m["er_model"] == "prototype_v1"
    assert isinstance(m["er_inputs"], dict)
    assert m["er_inputs"]["weights"]["momentum"] == 0.30


def test_incomplete_caps_high_label_to_low():
    row = {
        "symbol": "EICHERMOT.NS",
        "score": 0.7,
        "phase": "active",
        "confidence": "high",
        "components": {"momentum": 0.7},
    }
    snap = compute_prototype_er(row)
    assert snap["er_completeness"] < 0.6
    assert snap["confidence"] == 0.35


def test_complete_inputs_keep_high_confidence():
    row = {
        "symbol": "TCS.NS",
        "phase": "active",
        "confidence": "high",
        "components": {"momentum": 0.7, "quality": 0.7},
        "rs_vs_benchmark_pct": 4.0,
        "pe": 20.0,
        "industry_pe_median": 25.0,
        "roe": 0.22,
        "debt_to_equity": 0.3,
        "belief_adj": 0.01,
        "closed_trade_n": 5,
        "closed_trade_hit_rate": 0.6,
    }
    snap = compute_prototype_er(row)
    assert snap["er_completeness"] >= 0.6
    assert snap["confidence"] == 0.75
    assert set(snap["present_terms"]) == {
        "momentum",
        "sector_rs",
        "valuation",
        "quality",
        "belief",
        "experience",
    }


def test_valuation_cheaper_than_median_is_positive():
    cheap = compute_prototype_er(
        {"pe": 15.0, "industry_pe_median": 30.0, "symbol": "A.NS"}
    )
    rich = compute_prototype_er(
        {"pe": 40.0, "industry_pe_median": 20.0, "symbol": "B.NS"}
    )
    assert cheap["expected_return"] > rich["expected_return"]
    assert cheap["er_inputs"]["terms"]["valuation"]["present"] is True


def test_experience_requires_n_ge_3():
    thin = compute_prototype_er(
        {"closed_trade_n": 2, "closed_trade_hit_rate": 0.9, "symbol": "X.NS"}
    )
    assert "experience" in thin["missing_terms"]
    fat = compute_prototype_er(
        {"closed_trade_n": 4, "closed_trade_hit_rate": 0.9, "symbol": "Y.NS"}
    )
    assert "experience" in fat["present_terms"]
    assert fat["expected_return"] > 0


def test_overlay_fundamentals_fills_gaps_only():
    row = {"symbol": "CIPLA.NS", "pe": 28.0}
    overlay_fundamentals_for_er(
        row,
        {"pe": 99.0, "roe": 0.16, "industry_pe_median": 32.0, "debt_to_equity": 0.2},
    )
    assert row["pe"] == 28.0
    assert row["roe"] == 0.16
    assert row["industry_pe_median"] == 32.0


def test_packet_expected_block_preserves_snapshot():
    snap = compute_prototype_er(
        {"symbol": "CIPLA.NS", "components": {"momentum": 0.6}, "confidence": "low"}
    )
    block = expected_block_from_metrics(snap)
    assert block["er_model"] == "prototype_v1"
    assert block["expected_return"] == snap["expected_return"]
    assert block["er_inputs"]["terms"]["momentum"]["present"] is True


def test_learning_hold_evaluates_instead_of_missing_er():
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 13,
        "score": 0.7,
        "confidence": "very_low",
        "phase": "learning",
        "components": {"momentum": 0.7},
    }
    chal = {
        "symbol": "ASTRAL.NS",
        "score": 0.9,
        "confidence": "high",
        "phase": "active",
        "components": {"momentum": 0.9},
    }
    out = review_hold_vs_challengers(hold, [chal], exploratory=False)
    assert out["reason_code"] not in {
        REASON_BLOCKED_MISSING_ER,
        REASON_BLOCKED_COLD_START,
    }
    assert out["hold_metrics"]["er_model"] == "prototype_v1"
    assert out["hold_metrics"]["expected_return"] is not None
    assert out["decision"] in {"hold", "switch"}
