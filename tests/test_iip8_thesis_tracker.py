"""IIP.8 Thesis Tracker — open → revisit → close ×20 → prior unlock."""

from __future__ import annotations

from pathlib import Path

from atlas.investment import thesis_tracker as tt
from atlas.investment.research.service import InvestmentResearchService


def test_open_revisit_close_and_mentor_lesson(tmp_path: Path):
    data = str(tmp_path)
    tr = tt.open_tracker(
        data,
        "INFY",
        hypothesis="IT services growth + MoS",
        theme_links=["ai_it"],
        assumptions=[
            {"id": "a1", "kind": "leverage_ok", "text": "Debt stays moderate", "status": "open"},
            {"id": "a2", "kind": "valuation_band", "text": "MoS holds", "status": "open"},
        ],
        decision="buy",
        research_confidence="medium",
        investment_confidence="medium",
    )
    assert tr["status"] == "open"
    assert tr["symbol"] == "INFY.NS"

    tr = tt.revisit_tracker(
        data,
        "INFY",
        assumption_updates=[{"id": "a1", "status": "failed", "note": "Debt rose"}],
        note="Q review",
        evidence_note="Balance sheet",
    )
    assert any(a.get("status") == "failed" for a in tr["assumptions"])
    assert tr["revisits"]

    closed = tt.close_with_attribution(
        data,
        "INFY",
        result="falsified",
        pnl=-120.0,
        note="Thesis break on leverage",
    )
    assert closed["tracker"]["status"] == "closed"
    lessons = closed["tracker"]["lessons"]
    assert lessons
    assert any("debt" in str(x).lower() or "leverage" in str(x).lower() for x in lessons)
    priors = closed["priors"]
    assert priors["closed_outcomes"] == 1
    assert priors["ready_for_weight_shift"] is False


def test_n20_unlocks_weight_shift(tmp_path: Path):
    data = str(tmp_path)
    for i in range(20):
        sym = f"SYM{i}"
        tt.open_tracker(
            data,
            sym,
            hypothesis=f"H{i}",
            theme_links=["defence"],
            assumptions=[
                {
                    "id": "a1",
                    "kind": "theme_tailwind",
                    "text": "Defence demand",
                    "status": "open",
                }
            ],
            decision="buy",
            force=True,
        )
        result = "held" if i % 3 else "falsified"
        if result == "falsified":
            tt.revisit_tracker(
                data,
                sym,
                assumption_updates=[{"id": "a1", "status": "failed"}],
            )
        tt.close_with_attribution(data, sym, result=result, pnl=10.0 if result == "held" else -5.0)

    view = tt.priors_view(tt.load_priors(data))
    assert view["closed_outcomes"] >= 20
    assert view["ready_for_weight_shift"] is True
    deltas = view["weight_deltas"] or {}
    assert deltas.get("unlocked") is True
    boost = deltas.get("discovery_theme_boost") or {}
    pens = deltas.get("scoring_axis_penalty") or {}
    assert boost.get("defence") or pens or float(deltas.get("ranking_penalty_global") or 0) > 0


def test_record_outcome_wires_tracker(tmp_path: Path):
    data = str(tmp_path)
    svc = InvestmentResearchService(data_dir=data)
    svc.start("BEL", mode="mvr", force=True)
    svc.record_outcome(
        "BEL",
        result="observed",
        note="Sim buy",
        trade={"side": "buy", "quantity": 1, "price": 100, "realized_pnl": 0},
    )
    tr = tt.load_tracker(data, "BEL")
    assert tr is not None
    assert tr.get("decision") == "buy"

    svc.record_outcome(
        "BEL",
        result="weakened",
        note="Sim loss",
        trade={"side": "sell", "realized_pnl": -40},
    )
    tr2 = tt.load_tracker(data, "BEL")
    assert tr2 and tr2.get("status") == "closed"
    priors = tt.priors_view(tt.load_priors(data))
    assert priors["closed_outcomes"] >= 1


def test_awareness_includes_tracker_and_priors(tmp_path: Path):
    data = str(tmp_path)
    svc = InvestmentResearchService(data_dir=data)
    tt.open_tracker(data, "TCS", hypothesis="Stable cash", decision="watch")
    aw = svc.awareness("TCS")
    assert aw.get("thesis_tracker") is not None
    assert "thesis_priors" in aw
