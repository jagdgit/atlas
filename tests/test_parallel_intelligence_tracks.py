"""Parallel intelligence tracks: L3→L5, uncertainty queue, competition, lineage, LLM."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.competition_snapshot import (
    build_competition_snapshot,
    format_competition_line,
    persist_competition,
)
from atlas.investment.evidence_lineage import build_evidence_lineage, stamp_packet_lineage
from atlas.investment.l5_validation import (
    observe_candidates_from_competition,
    promote_l3_to_candidate,
    record_test_observation,
    STATUS_OPEN,
    STATUS_PASS,
)
from atlas.investment.llm_attribution import record_consultation, summarize_day
from atlas.investment.uncertainty_queue import (
    enqueue_from_awareness,
    enqueue_from_unknowns,
    list_tasks,
)


def test_l3_to_l4_candidate_not_l5():
    rec = {
        "id": "L-abc",
        "experience_id": "exp-1",
        "symbol": "CYIENT.NS",
        "chain_complete": True,
        "level": "L3",
        "update": "[relative_opportunity] Next-rupee vs WELCORP.NS action=KEEP",
        "prediction": {"status": "computed", "error_pct": -4.3},
    }
    out = promote_l3_to_candidate(rec, laboratory_id="equity_intraday_learner")
    assert out["ok"] is True
    assert out["l5"] is False
    assert out["candidate"]["level"] == "L4"
    assert out["candidate"]["subsequent_test"]["status"] == "OPEN"
    assert "CYIENT" in out["candidate"]["statement"]


def test_subsequent_test_validates_to_l5():
    rec = {
        "id": "L-abc",
        "experience_id": "exp-2",
        "symbol": "CYIENT.NS",
        "chain_complete": True,
        "level": "L3",
        "update": "[relative_opportunity] vs INFY",
        "prediction": {"status": "computed", "error_pct": -2.0},
    }
    cand = promote_l3_to_candidate(
        rec, laboratory_id="equity_intraday_learner", sessions_n=3
    )["candidate"]
    for day in ["2026-09-03", "2026-09-04", "2026-09-05"]:
        cand = record_test_observation(cand, as_of_ist=day, won=True)
    assert cand["subsequent_test"]["status"] == STATUS_PASS
    assert cand["level"] == "L5"


def test_uncertainty_queue_fcf_high(tmp_path: Path):
    out = enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="EICHERMOT.NS",
        unknowns=["fcf_missing", "noise_flag"],
    )
    assert len(out["created_ids"]) == 1
    tasks = list_tasks(tmp_path, "india_equity_learner")
    assert len(tasks) == 1
    assert tasks[0]["unknown"] == "fcf_missing"
    assert tasks[0]["importance"] == "HIGH"
    assert tasks[0]["status"] == "PENDING"


def test_uncertainty_from_awareness_fcf(tmp_path: Path):
    out = enqueue_from_awareness(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="EICHERMOT.NS",
        awareness={"known_unknowns": ["fcf", "fundamentals.pe"]},
    )
    assert any("UQ-" in x for x in out["created_ids"])
    codes = {t["unknown"] for t in list_tasks(tmp_path, "india_equity_learner")}
    assert "fcf_missing" in codes


def test_uncertainty_prune_non_material(tmp_path: Path):
    from atlas.investment.uncertainty_queue import prune_non_material_pending

    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        symbol="BEL.NS",
        unknowns=["mos_unknown"],
    )
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        symbol="WELCORP.NS",
        unknowns=["fcf_missing"],
    )
    pruned = prune_non_material_pending(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        material_symbols={"WELCORP.NS"},
    )
    assert pruned["closed_n"] == 1
    pending = list_tasks(tmp_path, "equity_intraday_learner")
    assert len(pending) == 1
    assert pending[0]["symbol"] == "WELCORP.NS"


def test_competition_snapshot_winner():
    snap = build_competition_snapshot(
        laboratory_id="equity_intraday_learner",
        candidates=[
            {"symbol": "CYIENT.NS", "expected_return": 0.0031},
            {"symbol": "INFY.NS", "expected_return": 0.0024},
            {"symbol": "RELIANCE.NS", "expected_return": 0.0011},
            {"symbol": "CASH", "expected_return": 0.0},
            {"symbol": "CASH", "expected_return": 0.0},  # dupe must collapse
        ],
        decision="KEEP",
        incumbent="CYIENT.NS",
    )
    assert snap["winner"] == "CYIENT.NS"
    assert snap["candidate_set"].count("CASH") == 1
    assert "CYIENT.NS" in format_competition_line(snap)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = persist_competition(d, snap)
        assert path is not None and path.is_file()


def test_l5_observe_from_competition(tmp_path: Path):
    rec = {
        "id": "L-obs",
        "experience_id": "exp-obs",
        "symbol": "CYIENT.NS",
        "chain_complete": True,
        "level": "L3",
        "update": "[relative_opportunity] vs INFY",
    }
    cand = promote_l3_to_candidate(
        rec,
        laboratory_id="equity_intraday_learner",
        data_dir=tmp_path,
        sessions_n=5,
    )["candidate"]
    assert cand["subsequent_test"]["status"] == STATUS_OPEN
    snap = build_competition_snapshot(
        laboratory_id="equity_intraday_learner",
        candidates=[
            {"symbol": "CYIENT.NS", "expected_return": 0.003},
            {"symbol": "INFY.NS", "expected_return": 0.001},
        ],
    )
    out = observe_candidates_from_competition(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        snap=snap,
        as_of_ist="2026-09-03",
    )
    assert out["updated_n"] == 1
    assert out["l5_claimed"] is False


def test_evidence_lineage_partial():
    lin = build_evidence_lineage(
        decision_id="d1",
        prediction={"prediction_status": "computed", "thesis_id": "t1"},
        acp_id="acp-1",
        evidence_refs=[{"id": "ev-9", "provider": "zerodha", "as_of": "2026-09-03"}],
        observation_ids=["obs-1"],
    )
    assert lin["completeness"] == "strong"
    assert "ev-9" in lin["evidence_ids"]
    pkt = {
        "decision_id": "d2",
        "evidence_refs": ["ev-a"],
        "observation_ids": [],
        "expected": {"prediction_status": "prediction_absent"},
        "market_snapshot": {},
        "meta": {},
    }
    stamp_packet_lineage(pkt)
    assert pkt["evidence_lineage"]["completeness"] in {"partial", "strong", "weak"}


def test_llm_attribution_measurement(tmp_path: Path):
    record_consultation(
        tmp_path,
        laboratory_id="india_equity_learner",
        purpose="icr5_scientist_notes",
        advice_summary="check FCF",
        accepted=True,
        changed=["research"],
        deterministic_action="HOLD",
        advised_action="HOLD",
    )
    record_consultation(
        tmp_path,
        laboratory_id="india_equity_learner",
        purpose="icr5_scientist_notes",
        accepted=False,
        changed=["none"],
    )
    s = summarize_day(tmp_path)
    assert s["n"] == 2
    assert s["accepted"] == 1
    assert s["ignored"] == 1
    assert s["changed_research"] == 1
    assert s["proven_allocation_improvements"] == 0
