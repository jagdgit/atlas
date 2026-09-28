"""NOW #3 — intraday overnight integrity (overnight_positions=0)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.investment.intraday_integrity import (
    VERSION,
    build_integrity_doc,
    format_intraday_integrity_evening_lines,
    load_integrity,
    record_intraday_integrity,
)
from atlas.investment.plc_exits import evaluate_plc_b_exits, plc_b_enabled

_IST = ZoneInfo("Asia/Kolkata")


def test_integrity_flat_ok_when_must_flat():
    doc = build_integrity_doc(
        laboratory_id="equity_intraday_learner",
        as_of_ist="2026-08-21",
        positions=[],
        must_be_flat=True,
        flatten_outcomes=[{"symbol": "DEVYANI.NS", "qty": 10}],
        flatten_session="2026-08-21",
    )
    assert doc["version"] == VERSION
    assert doc["overnight_positions"] == 0
    assert doc["overnight_positions_ok"] is True
    assert doc["status"] == "flat_ok"


def test_integrity_detects_overnight_carry():
    doc = build_integrity_doc(
        laboratory_id="equity_intraday_learner",
        positions=[{"symbol": "ASTRAL.NS", "quantity": 5}],
        must_be_flat=True,
    )
    assert doc["overnight_positions"] == 1
    assert doc["overnight_positions_ok"] is False
    assert doc["status"] == "overnight_carry"
    assert "ASTRAL.NS" in doc["open_symbols"]


def test_integrity_rth_not_binding():
    doc = build_integrity_doc(
        laboratory_id="equity_intraday_learner",
        positions=[{"symbol": "IDEA.NS", "quantity": 100}],
        must_be_flat=False,
    )
    assert doc["overnight_positions"] == 1
    assert doc["overnight_positions_ok"] is None
    assert doc["status"] == "session_open"


def test_record_and_evening(tmp_path):
    record_intraday_integrity(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        positions=[],
        must_be_flat=True,
        flatten_outcomes=[{"symbol": "X", "qty": 1}],
        flatten_session="2026-08-21",
        as_of_ist="2026-08-21",
    )
    loaded = load_integrity(
        tmp_path, laboratory_id="equity_intraday_learner", as_of_ist="2026-08-21"
    )
    assert loaded is not None
    assert loaded["overnight_positions_ok"] is True
    text = "\n".join(
        format_intraday_integrity_evening_lines(tmp_path, as_of_ist="2026-08-21")
    )
    assert "overnight_positions=0" in text
    assert "✅" in text


def test_fno_still_skips_concentration_after_intraday_work():
    # Regression guard — F&O isolation must stay while we densify intraday.
    assert plc_b_enabled({}, "india_fno_learner") is False
    prop = evaluate_plc_b_exits(
        symbol="NIFTY",
        price=24000.0,
        held=25.0,
        equity=100000.0,
        cfg={"plc_b_max_name_pct": 0.4, "plc_b_stop_loss_pct": 0.99},
    )
    if prop is not None:
        assert prop["exit_code"] != "concentration"
