"""Judgment Month J2 (open-book evidence densify) + J3 (evening belief answers)."""

from __future__ import annotations

from atlas.investment.fundamentals import (
    OPEN_BOOK_CRITICAL_FIELDS,
    learner_fundamentals_gaps,
    upsert_rows,
)
from atlas.investment.open_book_packs import _fundamentals_block
from atlas.investment.world_state import (
    append_revision,
    empty_wso,
    format_mind_change_section,
    sync_open_book_wsos,
)


def test_open_book_critical_includes_j2_fields():
    assert "pb" in OPEN_BOOK_CRITICAL_FIELDS
    assert "roic" in OPEN_BOOK_CRITICAL_FIELDS
    assert "promoter_holding" in OPEN_BOOK_CRITICAL_FIELDS
    assert "fcf" in OPEN_BOOK_CRITICAL_FIELDS


def test_fundamentals_block_surfaces_j2_unknowns():
    block = _fundamentals_block({"pe": 22.0, "roe": 18.0})
    assert block["pe"] == 22.0
    assert "fcf" in block["unknowns"]
    assert "roic" in block["unknowns"]
    assert "promoter_holding" in block["unknowns"]
    assert "management_commentary" in block["unknowns"]
    full = _fundamentals_block(
        {
            "pe": 1,
            "pb": 2,
            "roe": 3,
            "roic": 4,
            "fcf": 5,
            "debt_to_equity": 0.1,
            "promoter_holding": 50,
            "earnings_date": "2026-09-01",
        }
    )
    assert "earnings_proximity" not in full["unknowns"]
    assert full["earnings_proximity"]["earnings_date"] == "2026-09-01"


def test_open_book_gaps_use_j2_fields(tmp_path):
    upsert_rows(
        tmp_path,
        [{"symbol": "EICHERMOT.NS", "pe": 30.0, "roe": 20.0}],
        program_id="market_intelligence",
        source="test",
    )
    doc = learner_fundamentals_gaps(
        tmp_path,
        ["EICHERMOT.NS"],
        critical_fields=OPEN_BOOK_CRITICAL_FIELDS,
    )
    assert doc["symbols_with_gaps"] == 1
    missing = set(doc["gaps"][0]["missing"])
    assert "fcf" in missing
    assert "pb" in missing
    assert "roic" in missing
    assert "promoter_holding" in missing
    assert "pe" not in missing


def test_j3_mind_change_four_answers_idle():
    w = empty_wso(symbol="CIPLA.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf", "news"]
    w["status"] = "insufficient_evidence"
    lines = format_mind_change_section([w])
    body = "\n".join(lines)
    assert "belief_changed=no" in body
    assert "why:" in body
    assert "evidence:" in body
    assert "falsifier:" in body
    assert "No beliefs changed today." in body


def test_j3_mind_change_four_answers_material():
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["falsifiers"] = ["RS breaks vs auto sector"]
    append_revision(
        w,
        status="weakened",
        reason="Sector RS softened while FCF still unknown",
        evidence_delta={"news": 1, "bars": 1},
        llm=True,
    )
    lines = format_mind_change_section([w])
    body = "\n".join(lines)
    assert "belief_changed=yes" in body
    assert "why: Sector RS softened" in body
    assert "evidence: news=1" in body or "bars=1" in body
    assert "falsifier: RS breaks" in body
    assert "No beliefs changed today." not in body


def test_evening_sync_stamps_missing_fundamentals(tmp_path):
    wsos = sync_open_book_wsos(
        tmp_path,
        "india_equity_learner",
        ["CIPLA.NS"],
        missing_fundamentals={"CIPLA.NS": ["fcf", "roic", "promoter_holding"]},
    )
    assert "fcf" in (wsos[0].get("unknowns") or [])
    assert "roic" in (wsos[0].get("unknowns") or [])
