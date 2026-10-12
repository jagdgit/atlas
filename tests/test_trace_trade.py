"""OI-DELI0 Step 1 — unit tests for scripts/trace_trade.py (no live DB)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trace_trade as tt  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "trace" / "nifty_pe_2026_10_12"
SYN = ROOT / "tests" / "fixtures" / "trace" / "synthetic_linked"
ENTRY_ID = "70109538-b48c-4d03-a600-5e2482d606e1"
EXIT_ID = "17b5cb05-a102-40c4-b5b3-35594405f127"


def _run_fixture(fx: Path, trade_id: str = ENTRY_ID):
    sources = tt.TraceSources(
        fx / "data_dir",
        lab="india_fno_learner",
        db_dump_dir=fx / "db_dump",
    )
    try:
        return tt.build_cells(sources, trade_id)
    finally:
        sources.close()


def _by_field(cells):
    return {c.field: c for c in cells}


def test_t1_golden_nifty_gaps():
    cells, meta = _run_fixture(FIX)
    by = _by_field(cells)
    assert by["entry_decision"].status == "CONFLICT"
    assert by["entry_decision"].gap_class == "LINKAGE"
    assert by["exit_decision"].status == "MISSING"
    assert by["exit_decision"].gap_class == "LINKAGE"
    assert by["entry_pack_snapshot"].status == "MISSING"
    assert by["entry_pack_snapshot"].gap_class == "PERSISTENCE"
    assert by["underlier_session_context"].status == "OK"
    assert by["underlier_open_to_close_pct"].status == "CALCULATED"
    assert by["underlier_close_to_close_pct"].status == "CALCULATED"
    assert abs(float(by["underlier_open_to_close_pct"].value) - (-1.209)) < 0.02
    assert abs(float(by["underlier_close_to_close_pct"].value) - (-1.015)) < 0.02
    assert by["underlier_entry_to_exit_path"].status == "MISSING"
    assert by["underlier_entry_to_exit_path"].gap_class == "PERSISTENCE"
    assert by["stored_realized_return_pct"].status == "CONFLICT"
    assert by["stored_realized_return_pct"].gap_class == "COMPUTATION"
    assert by["trace_attribution_state"].value == "NOT_EVALUABLE"
    first = tt.first_blocking_dependency(cells)
    assert first["dimension"] in {"IDENTITY", "ACCOUNTING", "DECISION_LINKAGE"}
    # pairing must be OK for this fixture
    assert by["round_trip_pair"].status == "OK"
    assert meta["entry"]["id"] == ENTRY_ID
    assert meta["exit"]["id"] == EXIT_ID


def test_t2_synthetic_linkage_clears_early_dimensions():
    cells, _meta = _run_fixture(SYN)
    by = _by_field(cells)
    assert by["round_trip_pair"].status == "OK"
    assert by["entry_decision"].status == "OK"
    assert by["exit_decision"].status == "OK"
    assert by["entry_decision_packet"].status == "OK"
    assert by["stored_realized_return_pct"].status == "OK"
    assert by["entry_pack_snapshot"].status == "OK"
    first = tt.first_blocking_dependency(cells)
    # earliest critical should be after decision linkage
    assert first["dimension"] in {
        None,
        "DECISION_EVIDENCE",
        "ATTRIBUTION",
        "LEARNING",
    }


def test_t3_optional_stores_absent(tmp_path: Path):
    dump = tmp_path / "db_dump"
    dump.mkdir()
    for name in ("entry_trade.json", "exit_trade.json", "same_symbol_day.json", "entry_decision.json"):
        (dump / name).write_text((FIX / "db_dump" / name).read_text())
    (dump / "exit_decision.json").write_text("null\n")
    data = tmp_path / "data_dir"
    data.mkdir()
    sources = tt.TraceSources(data, db_dump_dir=dump)
    cells, _ = tt.build_cells(sources, ENTRY_ID)
    sources.close()
    # should not raise; many MISSING
    assert any(c.status == "MISSING" for c in cells)


def test_t4_prediction_overwrite(tmp_path: Path):
    import shutil

    shutil.copytree(FIX / "data_dir", tmp_path / "data_dir")
    shutil.copytree(FIX / "db_dump", tmp_path / "db_dump")
    pred_path = tmp_path / "data_dir/investment/fno/lab_v1_predictions/NIFTY26OCT22550PE.json"
    pred = json.loads(pred_path.read_text())
    pred["trade_id"] = "00000000-0000-0000-0000-000000000099"
    pred_path.write_text(json.dumps(pred))
    cells, _ = _run_fixture(tmp_path)
    by = _by_field(cells)
    assert by["entry_prediction"].status == "CONFLICT"
    assert by["entry_prediction"].gap_class == "PERSISTENCE"
    assert "overwritten" in by["entry_prediction"].note.lower() or "!=" in by["entry_prediction"].note


def test_t5_pack_after_entry():
    cells, _ = _run_fixture(FIX)
    by = _by_field(cells)
    assert by["entry_pack_snapshot"].status == "MISSING"
    assert "later" in by["entry_pack_snapshot"].note.lower() or "overwritten" in by["entry_pack_snapshot"].note.lower()


def test_t6_return_formula():
    cells, meta = _run_fixture(FIX)
    by = _by_field(cells)
    assert by["return_on_cost_roc_v1"].status == "CALCULATED"
    assert abs(float(by["return_on_cost_roc_v1"].value) - 29.66) < 0.05
    assert by["stored_realized_return_pct"].status == "CONFLICT"
    assert abs(float(by["stored_realized_return_pct"].value) - 22.8751) < 0.01
    assert abs(meta["accounting"]["stored_realized"] - 5099.25) < 0.01


def test_t7_readonly_and_out_inside_data_refused(tmp_path: Path):
    data = FIX / "data_dir"
    before = {p: (p.stat().st_mtime, p.stat().st_size, tt.file_meta(p)[0]) for p in data.rglob("*") if p.is_file()}
    cells, _ = _run_fixture(FIX)
    assert cells
    after = {p: (p.stat().st_mtime, p.stat().st_size, tt.file_meta(p)[0]) for p in data.rglob("*") if p.is_file()}
    assert before == after
    with pytest.raises(SystemExit):
        tt._ensure_out_outside_data(data / "out.md", data)


def test_t8_determinism():
    c1, m1 = _run_fixture(FIX)
    c2, m2 = _run_fixture(FIX)
    body1 = [(c.field, c.status, c.gap_class, json.dumps(c.value, sort_keys=True, default=str)) for c in c1]
    body2 = [(c.field, c.status, c.gap_class, json.dumps(c.value, sort_keys=True, default=str)) for c in c2]
    assert body1 == body2
    assert m1["accounting"] == m2["accounting"]


def test_t9_pairing_entry_and_exit_ids():
    cells_e, meta_e = _run_fixture(FIX, ENTRY_ID)
    cells_x, meta_x = _run_fixture(FIX, EXIT_ID)
    assert meta_e["entry"]["id"] == meta_x["entry"]["id"] == ENTRY_ID
    assert meta_e["exit"]["id"] == meta_x["exit"]["id"] == EXIT_ID


def test_t10_ambiguous_pairing():
    buy1 = {"id": "b1", "side": "buy", "quantity": 65.0, "price": 1, "fee": 0, "realized_pnl": 0, "created_at": "2026-10-12T04:00:00+00:00"}
    buy2 = {"id": "b2", "side": "buy", "quantity": 65.0, "price": 2, "fee": 0, "realized_pnl": 0, "created_at": "2026-10-12T05:00:00+00:00"}
    sell = {"id": "s1", "side": "sell", "quantity": 65.0, "price": 3, "fee": 0, "realized_pnl": 1, "created_at": "2026-10-12T06:00:00+00:00"}
    pair = tt.pair_round_trip(sell, [buy1, buy2, sell])
    assert pair["status"] == "AMBIGUOUS"
    assert set(pair["candidates"]) == {"b1", "b2"}


def test_t11_aliases_and_unknown():
    cells, _ = _run_fixture(FIX)
    by = _by_field(cells)
    assert by["underlier_session_context"].value["alias"] in {"_NSEI", "^NSEI", "NSEI"}


def test_t12_evidence_refs_have_hash_mtime():
    cells, _ = _run_fixture(FIX)
    file_sources = [s for c in cells for s in c.sources if s.kind == "file"]
    assert file_sources
    for s in file_sources:
        assert s.sha256 and len(s.sha256) == 64
        assert s.mtime_ist


def test_t13_attribution_states():
    a = tt.classify_attribution(
        has_entry_exit_underlier_path=False,
        has_iv=False,
        helped_factors=["option_premium_path"],
        narrative="premium path was the primary driver",
        false_missing_session_bar_claim=True,
    )
    assert a["state"] == "NOT_EVALUABLE"
    assert any("circular" in n for n in a["notes"])
    b = tt.classify_attribution(
        has_entry_exit_underlier_path=True,
        has_iv=False,
        helped_factors=[],
        narrative=None,
        false_missing_session_bar_claim=False,
    )
    assert b["state"] == "PARTIAL"


def test_t14_first_fix_identity_blocks():
    cells = [
        tt.Cell("IDENTITY", 1, "round_trip_pair", None, "AMBIGUOUS", note="x"),
        tt.Cell("ACCOUNTING", 7, "stored_realized_pnl", None, "MISSING", "PERSISTENCE", blocked_by=["IDENTITY.round_trip_pair"]),
    ]
    first = tt.first_blocking_dependency(cells)
    assert first["dimension"] == "IDENTITY"


def test_t15_accounting_no_double_subtract():
    entry = {"price": 100.0, "quantity": 10.0, "fee": 5.0, "realized_pnl": 0.0}
    exit_t = {"price": 110.0, "quantity": 10.0, "fee": 3.0, "realized_pnl": 97.0}  # (110-100)*10 - 3
    acct = tt.recompute_round_trip(entry, exit_t)
    assert abs(acct["check_realized_exit_fee_net"] - 97.0) < 1e-9
    assert abs(acct["round_trip_net"] - 92.0) < 1e-9  # 97 - entry fee 5
    # wrong double-subtract would be 97 - 3 - 5 = 89
    assert abs(acct["round_trip_net"] - (97.0 - 5.0)) < 1e-9


def test_t16_cli_help_and_unknown(tmp_path: Path):
    with pytest.raises(SystemExit) as ei:
        tt.main(["--help"])
    assert ei.value.code == 0
    rc = tt.main(
        [
            "--trade-id",
            "00000000-0000-0000-0000-000000000000",
            "--data-dir",
            str(tmp_path),
            "--db-dump-dir",
            str(FIX / "db_dump"),
        ]
    )
    assert rc == 2
