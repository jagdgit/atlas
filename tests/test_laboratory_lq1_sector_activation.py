"""LQ.1 — sector packs drive the live research question head (Apollo ≠ MTAR)."""

from __future__ import annotations

from atlas.investment.research import InvestmentResearchService
from atlas.investment.research import research_strategy as rs
from atlas.investment.research import sector_packs as packs


def _research_questions(doc: dict) -> list[dict]:
    return [
        q
        for q in (doc.get("questions") or [])
        if isinstance(q, dict) and q.get("kind") in {"sector", "universal"}
    ]


def test_build_question_plan_sector_first():
    pack = packs.pack_by_id("healthcare")
    assert pack
    questions, mix = rs.build_question_plan("APOLLOHOSP", pack=pack, max_total=16)
    assert mix.get("activation") == "sector_first"
    assert questions[0]["kind"] == "sector"
    assert mix["sector"] > mix["universal"]
    kinds = [q["kind"] for q in questions]
    first_univ = next(i for i, k in enumerate(kinds) if k == "universal")
    assert all(k == "sector" for k in kinds[:first_univ])


def test_live_start_apollo_mtar_heads_differ(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    apollo = svc.start("APOLLOHOSP", mode="mvr", force=True)
    mtar = svc.start("MTARTECH", mode="mvr", force=True)
    assert apollo["ok"] and mtar["ok"]

    aq = _research_questions(apollo["dossier"])
    mq = _research_questions(mtar["dossier"])
    assert aq and mq
    assert aq[0]["kind"] == "sector"
    assert mq[0]["kind"] == "sector"

    a_head = [q["text"] for q in aq[:6]]
    m_head = [q["text"] for q in mq[:6]]
    assert a_head != m_head
    assert any("occupancy" in t.lower() or "arpob" in t.lower() for t in a_head)
    assert any("order book" in t.lower() or "receivable" in t.lower() for t in m_head)

    # Generic seed q1–q6 must not lead the live list
    ids = [q.get("id") for q in apollo["dossier"].get("questions") or []]
    assert not any(str(i).startswith("q") and str(i)[1:].isdigit() for i in ids[:6])

    act = apollo["dossier"].get("question_activation") or {}
    assert act.get("version") == "lq.1"
    assert act.get("mode") == "sector_first"
    assert act.get("sector_pack_id") == "healthcare"

    mix = (apollo["dossier"].get("research_strategy") or {}).get("mix") or {}
    assert float(mix.get("sector_share") or 0) >= 0.65


def test_apply_strategy_replaces_seed_keeps_mgmt():
    seed = {
        "symbol": "APOLLOHOSP",
        "questions": [
            {"id": "q1", "text": "seed", "status": "open"},
            {
                "id": "mgmt-q1",
                "text": "management checklist",
                "status": "open",
                "kind": "management",
            },
        ],
    }
    pack = packs.pack_by_id("healthcare")
    strat = rs.generate_research_strategy(
        "APOLLOHOSP",
        identity={"status": "resolved", "business_type": "hospital", "pack_id": "healthcare"},
        pack=pack,
    )
    out = rs.apply_strategy_to_dossier(seed, strat)
    ids = [q.get("id") for q in out["questions"]]
    assert "q1" not in ids
    assert "mgmt-q1" in ids
    research = _research_questions(out)
    assert research[0]["kind"] == "sector"
