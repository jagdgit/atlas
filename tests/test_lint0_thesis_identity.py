"""OI-LINT0 Phase 2 — CIPLA hospital-network thesis is quarantined."""

from __future__ import annotations

from atlas.investment.lab_contracts import decompose_decision
from atlas.investment.plc_buy_gates import evaluate_plc_a_buy
from atlas.investment.research.sector_packs import hint_for
from atlas.investment.thesis_identity import (
    IDENTITY_QUARANTINED,
    IDENTITY_VALID,
    STATUS_THESIS_INVALID,
    validate_thesis_identity,
)


_HOSPITAL_THESIS = {
    "thesis": {
        "stance": "WATCH — not BUY",
        "summary": (
            "CIPLA is a branded hospital network. Occupancy, ARPOB, doctor "
            "retention and bed expansion ROIC drive returns."
        ),
    }
}

_PHARMA_THESIS = {
    "thesis": {
        "stance": "WATCH",
        "summary": (
            "Cipla's India branded generics and respiratory franchise; "
            "US ANDA execution remains the swing factor."
        ),
    }
}


def test_cipla_hint_is_pharma_not_hospital():
    hint = hint_for("CIPLA.NS")
    assert hint is not None
    assert hint["pack"] == "pharma"
    joined = " ".join(hint.get("facts") or []).lower()
    assert "not a hospital" in joined


def test_hospital_prose_quarantines_cipla_thesis():
    row = validate_thesis_identity("CIPLA.NS", _HOSPITAL_THESIS)
    assert row["identity"] == IDENTITY_QUARANTINED
    assert row["thesis_invalid"] is True
    assert row["status"] == STATUS_THESIS_INVALID
    assert row["identity_pack"] == "pharma"
    assert row["thesis_pack"] == "healthcare"


def test_pharma_prose_is_valid_for_cipla():
    row = validate_thesis_identity("CIPLA.NS", _PHARMA_THESIS)
    assert row["identity"] == IDENTITY_VALID
    assert row["thesis_invalid"] is False


def test_swing_buy_hold_when_thesis_quarantined():
    d = decompose_decision(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        action="buy",
        awareness=_HOSPITAL_THESIS,
        held=0.0,
    )
    assert d["identity"] == IDENTITY_QUARANTINED
    assert d["fundamental_thesis"] == "INVALID"
    assert d["final_decision"] == "HOLD"
    assert "identity_quarantined" in d["contradictions"]


def test_plc_a_does_not_use_hospital_copy_as_trigger():
    fund = {"pe": 36.0, "roe": 0.12, "debt_to_equity": 0.1, "sector": "Pharma"}
    out = evaluate_plc_a_buy(
        fundamentals=fund,
        awareness=_HOSPITAL_THESIS,
        instrument_sector="Pharma",
        engine_why="SMA10 cross with hospital occupancy thesis",
        symbol="CIPLA.NS",
    )
    assert out["allowed"] is False
    assert out["thesis_trigger"] is None
    assert any("thesis_invalid" in b for b in out["blocks"])
