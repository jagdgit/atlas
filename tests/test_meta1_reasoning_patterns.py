"""META.1 — reasoning-pattern ledger hermetic tests."""

from __future__ import annotations

from atlas.investment.meta_cognition import (
    VOCAB_GATE_N,
    build_pattern_ledger,
    collect_reasoning_events,
    format_meta_cognition_section,
    load_ledger,
    run_meta_cognition,
    tag_reason,
)
from atlas.investment.reports import format_evening_report
from atlas.investment.world_state import append_revision, empty_wso, save_wso


def _wso(symbol: str, lab: str, steps: list[tuple[str, str]]):
    w = empty_wso(symbol=symbol, laboratory_id=lab)
    for status, reason in steps:
        append_revision(w, status=status, reason=reason, llm=True)
    return w


def test_tag_reason_heuristics():
    assert "brand_moat" in tag_reason("Strong brand implies pricing power")
    assert "valuation" in tag_reason("PE looks cheap vs FCF")
    assert "untagged" in tag_reason("xyz")


def test_ledger_reliability_and_flip(tmp_path):
    lab = "india_equity_learner"
    w1 = _wso(
        "EICHERMOT.NS",
        lab,
        [
            ("strengthened", "brand moat and pricing power intact"),
            ("weakened", "news contradicted brand thesis"),
        ],
    )
    w2 = _wso(
        "TCS.NS",
        lab,
        [("strengthened", "valuation and FCF coverage improved")],
    )
    w3 = _wso(
        "INFY.NS",
        lab,
        [("falsified", "falsifier hit on sector theme")],
    )
    save_wso(tmp_path, w1)
    save_wso(tmp_path, w2)
    save_wso(tmp_path, w3)

    doc = run_meta_cognition(tmp_path, laboratory_id=lab)
    assert doc["status"] == "done"
    assert doc["advice_only"] is True
    assert doc["tagged_revisions"] >= 3
    assert doc["vocab_mode"] == "free_text_tags"
    assert doc["vocab_gate_n"] == VOCAB_GATE_N
    tags = {p["tag"] for p in doc.get("patterns") or []}
    assert "brand_moat" in tags or "news_catalyst" in tags
    brand = next(
        (p for p in doc["patterns"] if p["tag"] == "brand_moat"),
        None,
    )
    if brand:
        assert brand.get("flip_after", 0) >= 1
    loaded = load_ledger(tmp_path, laboratory_id=lab)
    assert loaded is not None


def test_empty_ledger(tmp_path):
    doc = run_meta_cognition(tmp_path, laboratory_id="empty", wsos=[])
    assert doc["status"] == "empty"


def test_evening_section():
    events = collect_reasoning_events(
        [
            _wso(
                "A.NS",
                "lab",
                [("strengthened", "relative strength and momentum hold")],
            )
        ]
    )
    built = build_pattern_ledger(events)
    doc = {
        "status": "done",
        "tagged_revisions": built["tagged_revisions"],
        "unique_tags": built["unique_tags"],
        "vocab_mode": built["vocab_mode"],
        "vocab_gate_n": VOCAB_GATE_N,
        "patterns": built["patterns"],
        "advice": ["sample advice"],
        "advice_only": True,
    }
    lines = format_meta_cognition_section(doc)
    assert any("META.1" in x for x in lines)
    assert any("momentum_rs" in x or "reliability=" in x for x in lines)

    subject, body = format_evening_report(
        plan={"as_of": "2026-08-10", "phase": "review", "summary": "t"},
        portfolio={"portfolio_key": "lab", "meta_cognition": doc},
        laboratory_id="lab",
    )
    assert "Reasoning patterns (META.1)" in body
