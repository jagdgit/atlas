"""F&O shadow trades — counterfactual outcomes for capital-blocked signals."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from atlas.investment import fno_shadow

LAB = "india_fno_learner"
IST = ZoneInfo("Asia/Kolkata")


def _at(hh: int, mm: int, day: int = 14) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=IST)


def _contract(sym: str, right: str) -> dict:
    return {"ok": True, "tradingsymbol": sym, "lot_size": 65, "expiry": "2026-10-28", "strike": 22500, "right": right}


def _enter(tmp: Path, *, margin: float = -0.004, reason: str = "capital_budget_max_open", when=None, und="NIFTY"):
    return fno_shadow.record_shadow_entry(
        tmp,
        laboratory_id=LAB,
        underlying=und,
        control_action="buy",
        sma_margin=margin,
        rsi=44.0,
        spot=22480.0,
        ce=_contract(f"{und}26OCT22500CE", "CE"),
        pe=_contract(f"{und}26OCT22500PE", "PE"),
        ce_ltp=120.0,
        pe_ltp=100.0,
        block_reason=reason,
        now=when or _at(10, 5),
    )


def test_blocked_bearish_signal_records_one_pe_shadow_per_underlier(tmp_path):
    out = _enter(tmp_path)
    assert out["ok"] is True
    assert out["right"] == "PE" and out["entry_premium"] == 100.0 and out["qty"] == 65
    assert out["counterfactual"] is True
    assert out["prediction"]["calibration_status"] == "uncalibrated_default"
    again = _enter(tmp_path, when=_at(10, 10))
    assert again == {"ok": False, "reason": "already_open_for_underlier"}
    assert _enter(tmp_path, und="BANKNIFTY")["ok"] is True


def test_only_capital_or_cash_blocks_in_session_are_shadowed(tmp_path):
    assert _enter(tmp_path, reason="hold_aligned_option")["reason"] == "block_not_shadowable"
    assert _enter(tmp_path, reason="insufficient cash for premium 6500.00; cash=10.00")["ok"] is True
    assert _enter(tmp_path, und="TCS", when=_at(16, 0))["reason"] == "outside_session"
    assert _enter(tmp_path, und="INFY", margin=0.0)["reason"] == "no_direction"


def test_in_session_close_is_evaluable_and_after_close_is_not(tmp_path):
    _enter(tmp_path)
    _enter(tmp_path, und="BANKNIFTY")
    assert fno_shadow.close_due_shadows(tmp_path, laboratory_id=LAB, ltp_fn=lambda s: 130.0, now=_at(15, 10)) == []
    closed = fno_shadow.close_due_shadows(
        tmp_path,
        laboratory_id=LAB,
        ltp_fn=lambda s: 130.0 if s.startswith("NIFTY") else None,
        now=_at(15, 22),
    )
    assert len(closed) == 1
    row = closed[0]
    assert row["status"] == "CLOSED" and row["learning_eligibility"]["eligible"] is True
    assert row["outcome"]["pnl_inr"] == 1950.0
    assert row["outcome"]["return_pct_on_premium"] == 30.0
    late = fno_shadow.close_due_shadows(tmp_path, laboratory_id=LAB, ltp_fn=lambda s: 90.0, now=_at(17, 35))
    assert [r["status"] for r in late] == ["NOT_EVALUABLE"]
    assert late[0]["learning_eligibility"]["reasons"] == ["exit_after_session_close"]
    eligible = fno_shadow.load_shadow_outcomes(tmp_path, LAB)
    assert [o["entry"]["underlying"] for o in eligible] == ["NIFTY"]
    assert len(fno_shadow.load_shadow_outcomes(tmp_path, LAB, eligible_only=False)) == 2
    summary = fno_shadow.summarize_shadow_day(tmp_path, LAB, "2026-10-14")
    assert summary["opened"] == 2 and summary["closed_evaluable"] == 1 and summary["still_open"] == 0


def test_previous_day_open_shadow_is_marked_missed(tmp_path):
    _enter(tmp_path, when=_at(10, 5, day=14))
    rows = fno_shadow.close_due_shadows(tmp_path, laboratory_id=LAB, ltp_fn=lambda s: 150.0, now=_at(9, 0, day=15))
    assert [r["learning_eligibility"]["reasons"] for r in rows] == [["missed_session_close"]]
    assert fno_shadow.load_shadow_outcomes(tmp_path, LAB) == []




@pytest.mark.parametrize("pack_status,expect_shadow", [("READY", True), ("NOT_READY", False)])
def test_worker_overlay_records_shadow_when_capital_budget_blocks(
    tmp_path, monkeypatch, pack_status, expect_shadow
):
    import logging
    from types import SimpleNamespace

    from atlas.investment import fno_contract, fno_data_pack, fno_lab_v1
    from atlas.workers.paper_trading import PaperTradingWorker

    monkeypatch.setattr(fno_data_pack, "build_fno_data_pack", lambda **k: {"status": pack_status, "underlying": "NIFTY"})
    monkeypatch.setattr(fno_data_pack, "persist_fno_data_pack", lambda *a, **k: None)
    monkeypatch.setattr(fno_data_pack, "apply_pack_to_overlay", lambda overlay, pack: overlay)

    monkeypatch.setattr(
        "atlas.config.get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data=str(tmp_path)))
    )
    monkeypatch.setattr(fno_lab_v1, "is_eligible_underlier", lambda *a, **k: True)
    bundle = {
        "ok": True,
        "atm_strike": 22500,
        "ce": _contract("NIFTY26OCT22500CE", "CE"),
        "pe": _contract("NIFTY26OCT22500PE", "PE"),
        "fut": {"ok": False},
    }
    monkeypatch.setattr(fno_contract, "resolve_phase2_bundle", lambda *a, **k: bundle)
    monkeypatch.setattr(fno_contract, "persist_phase2_bundle", lambda *a, **k: None)
    monkeypatch.setattr(fno_contract, "fno_control_action", lambda **k: "buy")

    class _Feed:
        def get_ltp(self, sym):
            px = {"NIFTY26OCT22500CE": 120.0, "NIFTY26OCT22500PE": 100.0}.get(sym, 22480.0)
            return {"ok": True, "prices": {sym: {"last": px}}}

        def list_nfo_futures(self):
            return []

        def list_nfo_options(self):
            return []

    worker = PaperTradingWorker.__new__(PaperTradingWorker)
    worker._logger = logging.getLogger("test.fno_shadow")
    worker._clock = lambda: _at(10, 5)
    worker._zerodha_feed = lambda: _Feed()
    open_opts = [
        {"symbol": "BANKNIFTY26OCT55300PE", "quantity": 30, "avg_cost": 600.0},
        {"symbol": "FINNIFTY26OCT25050PE", "quantity": 60, "avg_cost": 400.0},
    ]
    overlay = worker._fno_atm_overlay(
        symbol="NIFTY",
        price=22480.0,
        held=0.0,
        snapshot={"positions": open_opts, "cash": 200000.0, "net_contributed_capital": 100000.0},
        indicators={"sma_fast": 22400.0, "sma_slow": 22500.0, "rsi": 44.0, "price": 22480.0},
        control_action="buy",
        laboratory_id=LAB,
    )
    assert overlay["used"] is False
    assert overlay["reason"] == "capital_budget_max_open"
    rows = fno_shadow.open_shadows(tmp_path, LAB, "2026-10-14")
    if expect_shadow:
        assert overlay.get("shadow_id")
        assert [(r["symbol"], r["right"], r["entry_premium"]) for r in rows] == [
            ("NIFTY26OCT22500PE", "PE", 100.0)
        ]
    else:
        assert not overlay.get("shadow_id") and rows == []


def test_shadows_write_only_their_own_store(tmp_path):
    _enter(tmp_path)
    fno_shadow.close_due_shadows(tmp_path, laboratory_id=LAB, ltp_fn=lambda s: 110.0, now=_at(15, 25))
    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["investment/fno/shadow/india_fno_learner/2026-10-14.jsonl"]
