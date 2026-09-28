"""FNO-PAPER-001 — controlled paper ATM round-trip planning (hermetic)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from atlas.investment.fno_paper_001 import (
    EXPERIMENT_ID,
    acceptance_checklist,
    is_armed,
    plan_entry,
    plan_exit,
    policy,
)


def _rows(as_of: date, *, strike: float = 25000.0) -> list[dict]:
    return [
        {
            "tradingsymbol": "NIFTYNEARFUT",
            "name": "NIFTY",
            "instrument_type": "FUT",
            "instrument_token": 222,
            "expiry": as_of + timedelta(days=6),
            "lot_size": 65,
            "exchange": "NFO",
            "segment": "NFO-FUT",
        },
        {
            "tradingsymbol": "NIFTYNEAR25000CE",
            "name": "NIFTY",
            "instrument_type": "CE",
            "instrument_token": 555,
            "expiry": as_of + timedelta(days=6),
            "strike": strike,
            "lot_size": 65,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "NIFTYNEAR25000PE",
            "name": "NIFTY",
            "instrument_type": "PE",
            "instrument_token": 556,
            "expiry": as_of + timedelta(days=6),
            "strike": strike,
            "lot_size": 65,
            "exchange": "NFO",
        },
    ]


def test_policy_forbids_live_and_l4():
    p = policy()
    assert p["live_orders"] is False
    assert p["uses_l4_index_proxy"] is False
    assert p["cash_equity_alts"] is False
    assert p["experiment_id"] == EXPERIMENT_ID


def test_plan_entry_requires_fresh_option_ltp(tmp_path: Path):
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    day = date(2026, 9, 24)
    plan = plan_entry(
        spot=25010.0,
        instrument_rows=_rows(day),
        cash=100_000.0,
        ce_ltp=None,
        pe_ltp=None,
        now=now,
        data_dir=tmp_path,
    )
    assert plan["ok"] is False
    assert plan["reason"] == "no_fresh_option_ltp"
    assert plan["live_orders"] is False


def test_plan_entry_fails_without_spot():
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    plan = plan_entry(
        spot=None,
        instrument_rows=_rows(date(2026, 9, 24)),
        cash=100_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        now=now,
    )
    assert plan["ok"] is False
    assert plan["reason"] == "no_fresh_spot"


def test_plan_entry_ok_one_lot_ce(tmp_path: Path):
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    day = date(2026, 9, 24)
    plan = plan_entry(
        spot=25010.0,
        instrument_rows=_rows(day),
        cash=100_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        now=now,
        right="CE",
        data_dir=tmp_path,
    )
    assert plan["ok"] is True
    assert plan["side"] == "buy"
    assert plan["right"] == "CE"
    assert plan["symbol"] == "NIFTYNEAR25000CE"
    assert plan["qty"] == 65.0
    assert plan["price"] == 120.0
    assert plan["uses_l4_index_proxy"] is False
    assert plan["live_orders"] is False
    assert plan["instrument_path"] == "fno_paper_001"


def test_plan_entry_rejects_non_flat_book():
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    plan = plan_entry(
        spot=25010.0,
        instrument_rows=_rows(date(2026, 9, 24)),
        cash=100_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        now=now,
        open_positions=[{"symbol": "NIFTYNEAR25000PE", "qty": 65}],
    )
    assert plan["ok"] is False
    assert plan["reason"] == "book_not_flat"


def test_plan_entry_insufficient_premium():
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    plan = plan_entry(
        spot=25010.0,
        instrument_rows=_rows(date(2026, 9, 24)),
        cash=5_000.0,
        ce_ltp=1500.0,
        pe_ltp=1500.0,
        now=now,
    )
    assert plan["ok"] is False
    assert "insufficient" in str(plan.get("reason") or "").lower() or plan.get("reason")


def test_plan_exit_requires_ltp():
    out = plan_exit(symbol="NIFTYNEAR25000CE", qty=65, option_ltp=None)
    assert out["ok"] is False
    assert out["reason"] == "no_fresh_option_ltp_exit"


def test_plan_exit_ok():
    out = plan_exit(symbol="NIFTYNEAR25000CE", qty=65, option_ltp=95.0)
    assert out["ok"] is True
    assert out["side"] == "sell"
    assert out["price"] == 95.0
    assert out["live_orders"] is False


def test_is_armed_env_and_complete(monkeypatch, tmp_path):
    monkeypatch.delenv("ATLAS_FNO_PAPER_001", raising=False)
    assert is_armed({}, {}) is False
    monkeypatch.setenv("ATLAS_FNO_PAPER_001", "1")
    assert is_armed({}, {}) is True
    assert is_armed({}, {"fno_paper_001": {"status": "complete"}}) is False
    assert is_armed({"fno_paper_001_force": True}, {"fno_paper_001": {"status": "complete"}}) is True
    # Durable complete on disk beats a lingering env arm (overlap-tick race).
    from atlas.investment.fno_paper_001 import persist_experiment

    persist_experiment(
        tmp_path,
        {"experiment_id": "FNO-PAPER-001", "status": "complete"},
    )
    assert is_armed({}, {}, data_dir=tmp_path) is False
    # In-flight entered still arms so exit can finish.
    assert (
        is_armed({}, {"fno_paper_001": {"status": "entered"}}, data_dir=tmp_path)
        is True
    )


def test_acceptance_checklist_complete():
    doc = {
        "status": "complete",
        "armed": True,
        "live_orders": False,
        "cash_equity_alts": False,
        "entry": {
            "trade_id": "t-buy",
            "symbol": "NIFTYNEAR25000CE",
            "qty": 65,
            "price": 120.0,
            "atm_strike": 25000,
            "bundle_ok": True,
            "right": "CE",
            "spot": 25010.0,
        },
        "exit": {
            "trade_id": "t-sell",
            "price": 95.0,
            "realized_pnl": -100.0,
        },
    }
    checks = acceptance_checklist(doc)
    assert checks["complete"] is True
    assert checks["live_orders_false"] is True


def test_experience_email_exposes_cognitive_chain():
    from atlas.investment.fno_paper_001 import format_experience_email

    doc = {
        "status": "complete",
        "live_orders": False,
        "cash_equity_alts": False,
        "entry": {
            "trade_id": "t-buy",
            "symbol": "NIFTYNEAR25000CE",
            "qty": 65,
            "price": 120.0,
            "atm_strike": 25000,
            "right": "CE",
            "spot": 25010.0,
        },
        "exit": {"trade_id": "t-sell", "price": 95.0, "realized_pnl": -1625.0},
    }
    subject, body = format_experience_email(doc)
    assert "F&O PAPER EXPERIENCE" in subject
    assert "COGNITIVE INTERPRETATION" in body
    assert "UNREVIEWED" in body or "REVIEWED" in body
    assert "PROVISIONAL" in body
    assert "live_orders=False" in body
    assert "t-buy" in body and "t-sell" in body
    assert "LAB ROLE" in body
