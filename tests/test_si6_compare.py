"""SI.6 — Opportunity Comparison Engine (Why A vs B)."""

from __future__ import annotations

from atlas.investment.research import compare as cmp
from atlas.investment.research import InvestmentResearchService


def test_hospital_vs_defence_incomparable_lenses(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("APOLLOHOSP", mode="mvr", force=True)
    svc.start("MTARTECH", mode="mvr", force=True)
    out = svc.compare("APOLLOHOSP", "MTARTECH")
    assert out["ok"] is True
    assert out["version"] == "si.6"
    assert out["verdict"] == cmp.VERDICT_INCOMPARABLE
    assert out["a"]["pack_id"] == "healthcare"
    assert out["b"]["pack_id"] in {"defence", "manufacturing"}
    assert any("Different sector" in x or "different" in x.lower() for x in out["why_not_interchangeable"])
    assert "not a buy" in (out["honesty"] or "").lower()


def test_same_symbol_rejected(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.compare("INFY", "INFY")
    assert out["ok"] is False
    assert out["reason"] == "same_symbol"


def test_holdings_context(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("APOLLOHOSP", mode="mvr", force=True)
    svc.start("INFY", mode="mvr", force=True)
    out = svc.compare(
        "APOLLOHOSP",
        "INFY",
        holdings={"APOLLOHOSP": 10, "INFY": 0},
    )
    assert out["portfolio_context"]["a_held"] is True
    assert out["portfolio_context"]["b_held"] is False
    assert out["portfolio_context"]["note"]


def test_compare_axes_present(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("APOLLOHOSP", mode="mvr", force=True)
    svc.start("MTARTECH", mode="mvr", force=True)
    out = svc.compare("APOLLOHOSP", "MTARTECH")
    ids = {ax["id"] for ax in out["axes"]}
    assert "identity" in ids
    assert "distinctiveness" in ids
    assert "valuation_path" in ids
