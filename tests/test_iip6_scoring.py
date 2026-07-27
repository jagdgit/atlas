"""IIP.6 investment scoring — dual confidence + watch path."""

from __future__ import annotations

from atlas.investment.scoring import (
    compute_investment_score,
    score_from_awareness,
)
from atlas.investment.research.service import InvestmentResearchService


def test_high_research_low_investment_watch():
    """Done-when: high research + low investment → watch (not buy)."""
    sections = {
        "business": {
            "confidence": "high",
            "status": "present",
            "gaps": [],
            "fields": {"evidence": [{"x": 1}, {"y": 2}]},
        },
        "growth": {
            "confidence": "high",
            "status": "present",
            "gaps": [],
            "fields": {"evidence": [{"x": 1}]},
        },
        "financial_health": {
            "confidence": "medium",
            "status": "present",
            "gaps": ["leverage"],
            "fields": {},
        },
        "management": {
            "confidence": "high",
            "status": "present",
            "gaps": [],
            "fields": {"evidence": [{"x": 1}]},
        },
        "valuation": {
            "confidence": "very_low",
            "status": "present",
            "gaps": ["mos unknown"],
            "fields": {},
        },
        "risks": {
            "confidence": "low",
            "status": "present",
            "gaps": ["leverage", "cycle"],
            "fields": {},
        },
    }
    score = compute_investment_score(
        symbol="DEMO.NS",
        sections=sections,
        valuation={"method": "insufficient", "margin_of_safety_pct": -25},
        coverage=80.0,
        research_confidence="high",
        research_quality={"level": "substantive"},
        mvr_satisfied=True,
        mkg={
            "why_own": {
                "status": "ok",
                "themes": [{"label": "t"}],
                "policies": [{"label": "p"}],
            }
        },
        quality={"debt_to_equity": 2.5},
        horizon="long_term",
    )
    assert score["research_confidence_score"] >= 0.55
    assert score["investment_confidence_score"] < 0.40
    assert score["path"] == "watch"
    assert score["path_reason"] == "high_research_low_investment"
    assert "research_confidence" in score and "investment_confidence" in score


def test_dual_confidence_fields_distinct():
    score = compute_investment_score(
        sections={},
        coverage=10,
        research_confidence="very_low",
        research_quality={"level": "basic"},
        valuation={"margin_of_safety_pct": 40, "method": "dcf"},
        horizon="swing",
    )
    assert score["research_confidence"] != score["investment_confidence"] or score["path"] in {
        "watch",
        "buy_eligible",
        "avoid",
    }
    assert set(score["axes"]) >= {
        "business",
        "growth",
        "financial_health",
        "management",
        "valuation",
        "technical",
        "macro_theme",
        "risk",
    }


def test_gate_surfaces_score_and_watch(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    doc = svc.get_or_create("WATCHME.NS")
    from atlas.investment.research.models import mark_section

    for name in ("business", "growth", "management", "financial_health"):
        mark_section(
            doc,
            name,
            fields={"evidence": [{"claim": "seed", "level": "F", "status": "present"}]},
            confidence="medium",
            gaps=[],
            sources=["test"],
            status="present",
        )
    mark_section(
        doc,
        "valuation",
        fields={},
        confidence="very_low",
        gaps=["no mos"],
        sources=["test"],
        status="present",
    )
    doc["valuation"] = {"method": "insufficient", "margin_of_safety_pct": -10}
    doc["thesis"] = {"id": "t1", "stance": "watch", "summary": "Understood but unattractive"}
    doc["memories"] = [{"observation": "x"} for _ in range(5)]
    svc._store.save(doc)

    aw = svc.awareness("WATCHME.NS")
    assert aw.get("investment_score")
    score = aw["investment_score"]
    assert "research_confidence" in score
    assert "investment_confidence" in score

    gate = svc.gate_buy("WATCHME.NS", require_mvr=False, require_thesis=True, mos_mode="soft")
    assert "score_band" in gate
    assert gate.get("research_confidence") or gate.get("investment_confidence")
    assert gate.get("action") in {"watch", "hold_research", "avoid", "buy_ok"}


def test_score_from_awareness_horizon():
    aw = {
        "symbol": "X.NS",
        "coverage": 50,
        "confidence": "low",
        "research_quality": {"level": "developing"},
        "mvr_satisfied": False,
        "sections": {},
        "valuation": {},
        "mkg": {},
    }
    a = score_from_awareness(aw, horizon="structural")
    b = score_from_awareness(aw, horizon="swing")
    assert a["horizon"] == "structural"
    assert b["horizon"] == "swing"
    assert a["weights"]["macro_theme"] > b["weights"]["macro_theme"]
