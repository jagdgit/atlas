"""IIP.5 Market Knowledge Graph — seed, why-own, who-benefits."""

from __future__ import annotations

from atlas.investment.fundamentals import import_json_payload
from atlas.investment.mkg import (
    ensure_seeded,
    financial_cites_for,
    neighborhood,
    who_benefits,
    why_own,
)
from atlas.investment.mkg.seed import HINT_TO_POLICY
from atlas.investment.research.service import InvestmentResearchService


def test_seed_integrity(tmp_path):
    g = ensure_seeded(tmp_path, force=True)
    assert (g.get("stats") or {}).get("nodes", 0) >= 10
    assert (g.get("stats") or {}).get("edges", 0) >= 20
    nodes = g.get("nodes") or {}
    assert any(n.get("kind") == "theme" for n in nodes.values())
    assert any(n.get("kind") == "policy" for n in nodes.values())
    assert any(n.get("kind") == "company" for n in nodes.values())
    # Policy hint mapping resolves
    assert HINT_TO_POLICY["energy_transition"] == "renewable_energy_push"
    assert "policy:renewable_energy_push" in nodes


def test_why_own_waaree_cites_theme_and_policy(tmp_path):
    g = ensure_seeded(tmp_path, force=True)
    # Optional financials join
    import_json_payload(
        tmp_path,
        [{"symbol": "WAAREE", "roe": 18, "roce": 20, "debt_to_equity": 0.3, "pe": 35}],
    )
    fin = financial_cites_for(str(tmp_path), "WAAREE.NS")
    assert fin
    ans = why_own(g, "WAAREE.NS", financial_cites=fin)
    assert ans["status"] == "ok"
    assert len(ans["themes"]) >= 1
    assert len(ans["policies"]) >= 1
    assert "green" in ans["summary"].lower() or "renewable" in ans["summary"].lower()
    assert ans["financial_cites"]
    # Never invent supplies
    assert not any(e.get("rel") == "supplies" for e in ans["edges"])


def test_who_benefits_defence_includes_bel(tmp_path):
    g = ensure_seeded(tmp_path, force=True)
    res = who_benefits(g, theme_id="defence")
    assert res["status"] == "ok"
    syms = {c["symbol"] for c in res["companies"]}
    assert "BEL.NS" in syms


def test_unknown_symbol_honest(tmp_path):
    g = ensure_seeded(tmp_path, force=True)
    ans = why_own(g, "NOTAREALCO.NS")
    assert ans["status"] == "unknown_relation"
    assert ans.get("capability_gap")
    hood = neighborhood(g, symbol="NOTAREALCO.NS")
    assert hood["status"] == "unknown_relation"


def test_awareness_includes_mkg(tmp_path):
    ensure_seeded(tmp_path, force=True)
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    aw = svc.awareness("WAAREE.NS")
    mkg = aw.get("mkg") or {}
    assert mkg.get("status") == "ok"
    assert "theme" in (mkg.get("summary") or "").lower() or (mkg.get("why_own") or {}).get("themes")
