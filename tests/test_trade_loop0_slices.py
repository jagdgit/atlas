"""TRADE-LOOP0 slices B–E — UQ materiality, D/E, lifecycle, pipeline JSON."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.evidence_completeness import apply_completeness_to_uncertainty
from atlas.investment.fundamental_evidence.policy import FIELD_TO_UQ_CODE
from atlas.investment.fundamental_evidence.runner import (
    acquire_for_symbol,
    drain_uncertainty_queue,
    reconcile_non_network_uq,
)
from atlas.investment.fundamentals import get_symbol, upsert_rows
from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity
from atlas.investment.swing_pipeline import build_swing_pipeline, persist_swing_pipeline
from atlas.investment.uncertainty_queue import (
    STATUS_DONE,
    STATUS_NOT_WORTHWHILE,
    STATUS_PENDING,
    extra_material_from_lab,
    enqueue_from_unknowns,
    list_tasks,
    merge_decision_material,
    prune_non_material_pending,
)
from tests.test_laboratory_li2_providers import _fake_quote_summary


def test_field_to_uq_includes_debt():
    assert FIELD_TO_UQ_CODE["debt_to_equity"] == "debt_missing"


def test_sma_buy_not_pruned_when_next_rupee_is_cash(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER",
        unknowns=["pe_missing", "roe_missing", "debt_missing"],
    )
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WATCHLISTJUNK",
        unknowns=["pe_missing"],
    )
    material = merge_decision_material(
        destination="CASH",
        holdings=[],
        extra={"HBLPOWER"},
    )
    pruned = prune_non_material_pending(
        tmp_path,
        laboratory_id="india_equity_learner",
        material_symbols=material,
    )
    assert pruned["closed_n"] == 1
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    symbols = {t["symbol"] for t in pending}
    assert "HBLPOWER" in symbols
    assert "WATCHLISTJUNK" not in symbols
    codes = {t["unknown"] for t in pending if t["symbol"] == "HBLPOWER"}
    assert codes == {"pe_missing", "roe_missing", "debt_missing"}
    closed = list_tasks(tmp_path, "india_equity_learner", status=STATUS_NOT_WORTHWHILE)
    assert any(t["symbol"] == "WATCHLISTJUNK" for t in closed)


def test_plan_names_are_extra_material():
    extra = extra_material_from_lab(
        None,
        laboratory_id="india_equity_learner",
        daily_plan={"candidates": [{"symbol": "YESBANK"}, {"symbol": "COALINDIA"}]},
        plc_a_failed=["JUBLPHARMA"],
    )
    assert extra == {"YESBANK", "COALINDIA", "JUBLPHARMA"}


def test_debt_missing_round_trip_reaches_plc_a(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="COALINDIA.NS",
        unknowns=["debt_missing", "roe_missing"],
    )

    def opener(_url: str):
        return _fake_quote_summary(pe=12.0, fcf=1.0e9)

    out = acquire_for_symbol(
        tmp_path,
        "COALINDIA.NS",
        laboratory_id="india_equity_learner",
        required_fields=["pe", "roe", "debt_to_equity"],
        enabled=True,
        yahoo_secondary=True,
        opener=opener,
        push_to_ira=False,
        nse_enabled=False,
    )
    assert out["ok"] is True
    fields = {a["field"] for a in out.get("acquired") or []}
    assert "debt_to_equity" in fields
    row = get_symbol(tmp_path, "COALINDIA.NS") or {}
    assert row.get("debt_to_equity") is not None
    sanity = evaluate_fundamental_sanity(row, sector="Mining")
    assert "debt_to_equity" not in (sanity.get("missing") or [])
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    assert not any(
        t.get("unknown") == "debt_missing" and "COALINDIA" in str(t.get("symbol"))
        for t in pending
    )


def test_completeness_emits_debt_missing(tmp_path: Path):
    doc = {
        "laboratory_id": "india_equity_learner",
        "symbol": "HBLPOWER",
        "acquisition_codes": ["pe_missing", "roe_missing", "debt_missing"],
    }
    uq = apply_completeness_to_uncertainty(tmp_path, doc)
    assert uq["ok"] is True
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    codes = {t["unknown"] for t in pending if t["symbol"] == "HBLPOWER"}
    assert "debt_missing" in codes
    assert "pe_missing" in codes


def test_identity_available_closes_identity_unknown(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="TATACHEM",
        unknowns=["identity_unknown", "mos_unknown"],
    )

    class _Research:
        def awareness(self, symbol, program_id=None):
            return {"identity": "AVAILABLE"}

    out = reconcile_non_network_uq(
        tmp_path,
        laboratory_id="india_equity_learner",
        research=_Research(),
    )
    assert out["closed_ids"]
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    ident = [
        t for t in pending if t.get("unknown") == "identity_unknown"
    ]
    assert ident == []
    mos = [
        t
        for t in list_tasks(tmp_path, "india_equity_learner")
        if t.get("unknown") == "mos_unknown"
    ]
    assert mos
    assert mos[0].get("provider") == "ira_valuation"
    assert "IRA-computed" in str(mos[0].get("last_error") or "")
    drain = drain_uncertainty_queue(
        tmp_path, laboratory_id="india_equity_learner", enabled=False
    )
    assert drain["queued"] == 0


def test_uq_attempt_diagnostics_on_make():
    from atlas.investment.uncertainty_queue import make_acquisition_task

    t = make_acquisition_task(
        laboratory_id="india_equity_learner",
        symbol="YESBANK",
        unknown_code="pe_missing",
    )
    assert t["attempt_count"] == 0
    assert t["last_error"] is None


def test_swing_pipeline_counts_plc_a_incomplete(tmp_path: Path):
    packets = [
        {
            "symbol": "HBLPOWER",
            "kind": "buy",
            "strategy_tag": "sma_cross_rsi",
            "reasons_against": ["fundamentals_incomplete"],
            "plc_a": {"missing": ["pe", "roe", "debt_to_equity"]},
        },
        {
            "symbol": "IDEA",
            "kind": "hold",
            "strategy_tag": "research_forced_hold",
            "reasons_against": ["thesis_watch_insufficient"],
        },
        {
            "symbol": "WELCORP",
            "kind": "hold",
            "strategy_tag": "lab_policy",
            "reasons_against": ["lab_policy AVOID"],
        },
    ]
    doc = build_swing_pipeline(
        tmp_path,
        laboratory_id="india_equity_learner",
        universe_n=190,
        sma_symbols=["HBLPOWER", "IDEA", "WELCORP"],
        packets=packets,
        fills_n=0,
        as_of_ist="2026-09-18",
    )
    assert doc["counts"]["plc_a_incomplete"] == 1
    assert doc["counts"]["research_hold"] == 1
    assert doc["counts"]["lab_policy_avoid"] == 1
    assert doc["paper_fills"] == 0
    path = persist_swing_pipeline(tmp_path, doc)
    assert path is not None and path.is_file()


def test_drain_does_not_send_mos_to_yahoo(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="TATACHEM",
        unknowns=["mos_unknown"],
    )
    out = drain_uncertainty_queue(
        tmp_path,
        laboratory_id="india_equity_learner",
        enabled=True,
        opener=lambda _u: _fake_quote_summary(),
        push_to_ira=False,
    )
    assert out["queued"] == 0
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    assert any(t.get("unknown") == "mos_unknown" for t in pending)
