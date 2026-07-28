"""SI.3 — Research Strategy Generator + question mix."""

from __future__ import annotations

from atlas.investment.research import research_strategy as rs
from atlas.investment.research import sector_packs as packs
from atlas.investment.research import business_identity as bi
from atlas.investment.research import InvestmentResearchService


def test_mix_targets_sector_majority():
    pack = packs.pack_by_id("healthcare")
    assert pack
    questions, mix = rs.build_question_plan("APOLLOHOSP", pack=pack, max_total=16)
    assert mix["sector"] > mix["universal"]
    assert mix["sector_share"] >= 0.65
    assert any(q["kind"] == "sector" for q in questions)
    assert any(q["kind"] == "universal" for q in questions)


def test_hospital_vs_defence_questions_differ():
    hosp = rs.generate_research_strategy(
        "APOLLOHOSP",
        identity=bi.resolve_identity("APOLLOHOSP"),
        pack=packs.pack_by_id("healthcare"),
    )
    defn = rs.generate_research_strategy(
        "MTARTECH",
        identity=bi.resolve_identity("MTARTECH"),
        pack=packs.pack_by_id("defence"),
    )
    h_texts = {q["text"] for q in hosp["question_plan"] if q["kind"] == "sector"}
    d_texts = {q["text"] for q in defn["question_plan"] if q["kind"] == "sector"}
    assert h_texts != d_texts
    assert any("occupancy" in t.lower() or "arpob" in t.lower() for t in h_texts)
    assert any("order book" in t.lower() or "receivable" in t.lower() for t in d_texts)


def test_dcf_unavailable_without_fcf():
    pack = {
        "id": "saas_it",
        "valuation_methods": ["DCF on FCF", "PE vs growth"],
    }
    paths = rs.build_valuation_paths(pack, available_inputs={})
    assert paths.get("active", {}).get("kind") != "dcf_fcf"
    assert any(u.get("reason") == "fcf_absent" for u in (paths.get("unavailable") or []))
    assert paths.get("primary")  # back-compat label


def test_strategy_on_mvr_start(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("APOLLOHOSP", mode="mvr", force=True)
    assert out["ok"] is True
    strat = (out["dossier"].get("research_strategy") or {})
    assert strat.get("version") == "si.3"
    assert strat.get("sector_pack_id") == "healthcare"
    mix = strat.get("mix") or {}
    assert mix.get("sector", 0) >= mix.get("universal", 0)
    aw = out["awareness"]
    assert aw.get("research_strategy", {}).get("sector_pack_id") == "healthcare"


def test_identity_unknown_blocks_strategy():
    strat = rs.generate_research_strategy("XYZUNKNOWNCO")
    assert "identity_unknown" in (strat.get("blockers") or [])
    assert strat.get("strategy_id") == "blocked_identity"
