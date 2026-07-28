"""SI.4 — valuation path branching on missing evidence."""

from __future__ import annotations

from atlas.investment.research import sector_packs as packs
from atlas.investment.research.valuation import build_valuation_case
from atlas.investment.research.valuation_paths import (
    PATH_DCF,
    PATH_PE,
    apply_branching_to_valuation_case,
    branch_valuation_paths,
)
from atlas.investment.research import InvestmentResearchService


def test_dcf_absent_activates_multiples():
    # Explicit DCF method (saas_it YAML lists FCF yield as multiples, not dcf_fcf).
    pack = {
        "id": "energy_utilities",
        "valuation_methods": ["DCF on FCF", "PE vs growth peers"],
    }
    br = branch_valuation_paths(pack, inputs={"pe": 22.0})
    assert br["version"] == "si.4"
    assert br["active"]["kind"] in {PATH_PE, "sector_relative"}
    assert br["active"]["kind"] != PATH_DCF
    assert any(u["kind"] == PATH_DCF and u["reason"] == "fcf_absent" for u in br["unavailable"])
    assert any(e.get("need") == "fcf" for e in br["next_evidence"])


def test_apply_branching_never_claims_dcf_mos_without_fcf():
    case = build_valuation_case(
        symbol="TEST.NS",
        ratios={"pe": 18.0, "roe": 0.18, "sector": "Information Technology"},
        price=100.0,
    )
    br = branch_valuation_paths(
        {"valuation_methods": ["DCF on FCF", "PE vs growth"]},
        inputs={"pe": 18.0, "price": 100.0},
    )
    out = apply_branching_to_valuation_case(case, br)
    assert out["active_valuation_path"] == PATH_PE
    assert out.get("mos_method") in {"pe_vs_fair", "unavailable"}
    assert "fcf_absent" in " ".join(
        str(u.get("reason")) for u in (out.get("path_branching") or {}).get("unavailable") or []
    )


def test_fcf_present_can_activate_dcf():
    br = branch_valuation_paths(
        {"valuation_methods": ["DCF on FCF", "PE vs growth"]},
        inputs={"fcf": 1e9, "price": 100.0, "shares": 1e8, "pe": 20.0},
    )
    assert br["active"]["kind"] == PATH_DCF


def test_mvr_stamps_path_branching(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("INFY", mode="mvr", force=True)
    assert out["ok"] is True
    val = out["dossier"].get("valuation") or {}
    pb = val.get("path_branching") or {}
    assert pb.get("version") == "si.4"
    assert pb.get("active_path")
    strat_paths = (out["dossier"].get("research_strategy") or {}).get("valuation_paths") or {}
    assert strat_paths.get("version") == "si.4"
