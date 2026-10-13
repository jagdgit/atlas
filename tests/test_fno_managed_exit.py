"""F&O Lab v1 held-option management: stop, reversal, no same-day re-entry."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.investment import fno_lab_v1 as lab_v1

IST = ZoneInfo("Asia/Kolkata")


def _held(sym: str, right: str, avg: float, qty: float = 65) -> dict:
    return {"symbol": sym, "right": right, "qty": qty, "position": {"symbol": sym, "quantity": qty, "avg_price": avg}}


def test_premium_stop_fires_at_minus_40_pct_and_never_without_a_mark():
    held = [_held("NIFTY26OCT22500PE", "PE", 249.30)]
    assert lab_v1.evaluate_held_option_exit(held, ltp_by_symbol={"NIFTY26OCT22500PE": 160.0}, sma_margin=-0.003) is None
    ex = lab_v1.evaluate_held_option_exit(held, ltp_by_symbol={"NIFTY26OCT22500PE": 149.0}, sma_margin=-0.003)
    assert ex["exit_code"] == lab_v1.EXIT_PREMIUM_STOP and ex["price"] == 149.0 and ex["qty"] == 65
    assert lab_v1.evaluate_held_option_exit(held, ltp_by_symbol={"NIFTY26OCT22500PE": None}, sma_margin=0.01) is None


def test_reversal_exits_put_on_bullish_trend_and_call_on_bearish():
    pe = [_held("NIFTY26OCT22500PE", "PE", 100.0)]
    ce = [_held("NIFTY26OCT22500CE", "CE", 100.0)]
    assert lab_v1.evaluate_held_option_exit(pe, ltp_by_symbol={"NIFTY26OCT22500PE": 95.0}, sma_margin=0.002)["exit_code"] == "underlier_reversal"
    assert lab_v1.evaluate_held_option_exit(ce, ltp_by_symbol={"NIFTY26OCT22500CE": 95.0}, sma_margin=-0.002)["exit_code"] == "underlier_reversal"
    assert lab_v1.evaluate_held_option_exit(pe, ltp_by_symbol={"NIFTY26OCT22500PE": 95.0}, sma_margin=-0.002) is None


def test_target_is_off_by_default_and_configurable():
    pe = [_held("NIFTY26OCT22500PE", "PE", 100.0)]
    ltp = {"NIFTY26OCT22500PE": 200.0}
    assert lab_v1.evaluate_held_option_exit(pe, ltp_by_symbol=ltp, sma_margin=-0.002) is None
    ex = lab_v1.evaluate_held_option_exit(pe, ltp_by_symbol=ltp, sma_margin=-0.002, policy_doc={"premium_target_pct": 0.6})
    assert ex["exit_code"] == lab_v1.EXIT_PREMIUM_TARGET


def test_option_underlier_name_handles_monthly_weekly_and_ampersand():
    assert lab_v1.option_underlier_name("NIFTY26OCT22500PE") == "NIFTY"
    assert lab_v1.option_underlier_name("BANKNIFTY26OCT55300PE") == "BANKNIFTY"
    assert lab_v1.option_underlier_name("NIFTY2610622500PE") == "NIFTY"
    assert lab_v1.option_underlier_name("M&M26OCT3000CE") == "M&M"
    assert lab_v1.option_underlier_name("RELIANCE.NS") is None


def test_managed_exit_underliers_reads_todays_lineage(tmp_path):
    root = tmp_path / "investment" / "trade_lineage" / "india_fno_learner"
    root.mkdir(parents=True)
    rows = [
        {"side": "sell", "symbol": "NIFTY26OCT22500PE", "exit_reason_code": "premium_stop"},
        {"side": "sell", "symbol": "TCS26OCT2200PE", "exit_reason_code": "fno_lab_v1_experiment_close"},
        {"side": "buy", "symbol": "INFY26OCT1040PE", "exit_reason_code": None},
    ]
    (root / "2026-10-14.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert lab_v1.managed_exit_underliers(tmp_path, ist_day="2026-10-14") == {"NIFTY"}
    assert lab_v1.managed_exit_underliers(tmp_path, ist_day="2026-10-15") == set()


def test_worker_returns_sell_for_stopped_non_atm_option():
    from atlas.workers.paper_trading import PaperTradingWorker

    class _Feed:
        def get_ltp(self, sym):
            return {"ok": True, "prices": {sym: {"last": 140.0}}}

    worker = PaperTradingWorker.__new__(PaperTradingWorker)
    worker._logger = logging.getLogger("test.fno_managed_exit")
    worker._clock = lambda: datetime(2026, 10, 14, 11, 0, tzinfo=IST)
    worker._zerodha_feed = lambda: _Feed()
    out = worker._fno_managed_exit(
        symbol="NIFTY",
        positions=[{"symbol": "NIFTY26OCT22500PE", "quantity": 65, "avg_price": 249.30}],
        sma_margin=-0.003,
        control_action="buy",
        underlying_price=22700.0,
    )
    assert out["used"] is True and out["kind"] == "sell"
    assert out["symbol"] == "NIFTY26OCT22500PE" and out["qty"] == 65.0 and out["price"] == 140.0
    assert out["exit_code"] == "premium_stop"
    assert worker._fno_managed_exit(
        symbol="BANKNIFTY",
        positions=[{"symbol": "NIFTY26OCT22500PE", "quantity": 65, "avg_price": 249.30}],
        sma_margin=-0.003,
        control_action="buy",
        underlying_price=22700.0,
    ) is None
