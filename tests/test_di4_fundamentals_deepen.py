"""DI.4 deepen — learner gap template, industry median honesty, never invent."""

from __future__ import annotations

from atlas.investment.fundamentals import (
    import_csv_text,
    learner_fundamentals_gaps,
    learner_gap_fill_template,
    normalize_row,
    peer_context,
)
from atlas.investment.reports import format_evening_report
from atlas.investment.research.valuation import build_valuation_case


def test_industry_median_aliases_and_peer_context():
    row = normalize_row(
        {
            "symbol": "INFY",
            "pe": 24,
            "Industry PE median": 30,
            "fcf": 1000,
            "roe": 28,
        }
    )
    assert row is not None
    assert row["industry_pe_median"] == 30.0
    peer = peer_context(row)
    assert peer["may_claim_below_industry_pe"] is True
    assert peer["pe_vs_industry_median_pct"] is not None
    assert peer["fair_pe_is_not_industry_average"] is True

    bare = peer_context({"symbol": "X", "pe": 20})
    assert bare["may_claim_below_industry_pe"] is False
    assert "industry_pe_median missing" in (bare.get("honesty") or "")


def test_valuation_never_claims_industry_without_median():
    case = build_valuation_case(
        symbol="INFY.NS",
        ratios={"pe": 22, "roe": 0.28, "sector": "IT"},
    )
    assert case["pe"] == 22
    assert case["fair_pe"] is not None
    assert case["fair_pe_source"] == "quality_heuristic"
    assert case["industry_pe_median"] is None
    assert case["may_claim_below_industry_pe"] is False
    assert any("industry_pe_median" in g for g in (case.get("gaps") or []))

    case2 = build_valuation_case(
        symbol="INFY.NS",
        ratios={
            "pe": 22,
            "roe": 0.28,
            "sector": "IT",
            "industry_pe_median": 28,
        },
    )
    assert case2["industry_pe_median"] == 28
    assert case2["may_claim_below_industry_pe"] is True
    assert case2["pe_vs_industry_median_pct"] is not None


def test_learner_gap_fill_template_prefills_and_leaves_holes(tmp_path):
    import_csv_text(
        tmp_path,
        "symbol,pe,roe,debt_to_equity\nINFY,25,28,0.1\n",
        note="partial",
    )
    tpl = learner_gap_fill_template(
        tmp_path,
        ["INFY.NS", "TCS.NS", "APOLLOHOSP.NS"],
        only_gaps=True,
    )
    # INFY missing fcf → gap; TCS/APOLLO no row → gaps
    syms = {r["symbol"] for r in tpl["rows"]}
    assert "INFY.NS" in syms
    assert "TCS.NS" in syms
    assert "APOLLOHOSP.NS" in syms
    infy = next(r for r in tpl["rows"] if r["symbol"] == "INFY.NS")
    assert infy["pe"] == 25.0 or infy["pe"] == 25
    assert infy["fcf"] == ""  # never invent
    assert "fill:" in str(infy.get("note") or "")
    assert "csv" in tpl and "symbol,pe,pb,fcf" in tpl["csv"]
    gaps = tpl["gaps"]
    assert gaps["missing_fcf"] >= 1
    assert gaps["symbols_with_gaps"] >= 2


def test_sample_fixture_import(tmp_path):
    from pathlib import Path

    sample = Path("tests/fixtures/investment/learner_fundamentals_sample.csv")
    text = sample.read_text(encoding="utf-8")
    result = import_csv_text(tmp_path, text)
    assert result["imported"] >= 2
    gaps = learner_fundamentals_gaps(
        tmp_path, ["INFY.NS", "TCS.NS", "APOLLOHOSP.NS"]
    )
    # INFY+TCS have pe; APOLLO empty row not imported (no fields) — only 2 rows
    assert gaps["symbols_with_row"] >= 2
    assert gaps["missing_pe"] >= 1  # APOLLO


def test_evening_lists_gap_symbols():
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={
            "cash": 1,
            "fundamentals_coverage": {
                "symbols": 2,
                "with_pe": 0,
                "with_fcf": 0,
                "note": "Empty PE/FCF is honest incomplete evidence",
                "learner_gaps": {
                    "symbols_with_gaps": 2,
                    "symbols_checked": 3,
                    "missing_pe": 2,
                    "missing_fcf": 2,
                    "with_industry_pe_median": 0,
                    "gaps": [
                        {"symbol": "A.NS", "missing": ["pe", "fcf"]},
                        {"symbol": "B.NS", "missing": ["pe"]},
                    ],
                },
            },
        },
    )
    assert "Fundamentals coverage" in body
    assert "learner-template" in body
    assert "A.NS" in body
