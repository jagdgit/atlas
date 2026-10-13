"""Decision chain block in trade emails (lineage + decision packet + prediction)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.investment.decision_chain_mail import build_decision_chain
from atlas.investment.reports import format_trade_report

IST = ZoneInfo("Asia/Kolkata")
LAB = "india_fno_learner"
SYM = "NIFTY26OCT22500PE"


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 10, 14, hh, mm, tzinfo=IST).astimezone(timezone.utc)


def _seed(tmp: Path, *, sell_at: datetime, sell_price: float, code: str, link_entry: bool = True) -> None:
    lin = tmp / "investment" / "trade_lineage" / LAB / "2026-10-14.jsonl"
    lin.parent.mkdir(parents=True)
    buy = {
        "lineage_id": "L1", "fill_trade_id": "T-BUY", "symbol": SYM, "side": "buy", "quantity": 65.0,
        "price": 200.0, "recorded_at": _at(9, 30).isoformat(), "entry_decision_id": "D-OVL",
        "overlay_decision_id": "D-OVL", "prediction_id": None,
        "order_intent": {"engine_action": "buy", "engine_decision_id": "D-ENG", "overlay_used": True,
                         "rationale_text": "v1_buy_atm_pe"},
        "lineage_incomplete": False, "integrity_issues": [],
    }
    sell = {
        "lineage_id": "L2", "fill_trade_id": "T-SELL", "symbol": SYM, "side": "sell", "quantity": 65.0,
        "price": sell_price, "recorded_at": sell_at.isoformat(), "exit_decision_id": "D-EXIT",
        "exit_reason_code": code, "entry_decision_id": "D-OVL" if link_entry else None,
        "order_intent": {}, "lineage_incomplete": False, "integrity_issues": [],
    }
    lin.write_text("\n".join(json.dumps(r) for r in (buy, sell)) + "\n", encoding="utf-8")
    pkt = tmp / "investment" / "decisions" / "by_id" / "D-OVL.json"
    pkt.parent.mkdir(parents=True)
    pkt.write_text(json.dumps({
        "reasons_for": ["v1_buy_atm_pe"], "reasons_against": [],
        "expected": {"expected_return": 0.08, "predicted_probability": 0.7, "prediction_horizon": "session_flat",
                     "er_model": "fno_lab_v1_control_signal.v1", "thesis": "SMA margin -0.01 → long ATM PE",
                     "key_evidence": ["sma_margin=-0.01", "right=PE"]},
    }), encoding="utf-8")


def _chain(tmp: Path, side: str, trade_id: str, now: datetime) -> str:
    return "\n".join(build_decision_chain(tmp, laboratory_id=LAB, symbol=SYM, side=side, trade_id=trade_id, now=now))


def test_buy_chain_shows_control_overlay_and_prediction(tmp_path: Path):
    _seed(tmp_path, sell_at=_at(11, 0), sell_price=120.0, code="premium_stop")
    text = _chain(tmp_path, "buy", "T-BUY", _at(9, 31))
    assert "Control rule: buy (decision D-ENG)" in text
    assert "Overlay: v1_buy_atm_pe (decision D-OVL)" in text
    assert "E[R] +8.0%, p=0.70, horizon session_flat" in text and "(uncalibrated)" in text
    assert "· sma_margin=-0.01" in text
    assert "Prediction id: not recorded" in text


def test_managed_exit_sell_shows_entry_outcome_and_eligibility(tmp_path: Path):
    _seed(tmp_path, sell_at=_at(11, 0), sell_price=120.0, code="premium_stop")
    text = _chain(tmp_path, "sell", "T-SELL", _at(11, 1))
    assert "Exit reason: premium_stop — premium stop hit" in text
    assert "bought 65.0 @ 200.0 at 2026-10-14 09:30 IST (decision D-OVL; linked on the sell)" in text
    assert "Held: 90 min" in text
    assert "price return -40.0% vs predicted +8.0% → direction WRONG, error -48.0%" in text
    assert "Learning: eligible (in-session exit)" in text


def test_after_close_sell_without_entry_link_is_flagged(tmp_path: Path):
    _seed(tmp_path, sell_at=_at(17, 40), sell_price=210.0, code="fno_lab_v1_experiment_close", link_entry=False)
    text = _chain(tmp_path, "sell", "T-SELL", _at(17, 41))
    assert "matched by symbol, sell carried no entry link" in text
    assert "direction RIGHT" in text
    assert "Learning: NOT eligible (exit after the NSE close" in text


def test_missing_lineage_is_said_not_invented(tmp_path: Path):
    text = _chain(tmp_path, "sell", "T-NONE", _at(11, 0))
    assert text.strip().startswith("Not recorded: no trade-lineage row for this fill")


def test_email_renders_chain_block_before_engine_detail(tmp_path: Path):
    _seed(tmp_path, sell_at=_at(11, 0), sell_price=120.0, code="underlier_reversal")
    chain = build_decision_chain(tmp_path, laboratory_id=LAB, symbol=SYM, side="sell", trade_id="T-SELL", now=_at(11, 1))
    _, body = format_trade_report(
        side="sell", symbol=SYM, quantity=65, price=120.0, laboratory_id=LAB,
        decision={"id": "D-EXIT", "action": "sell"}, decision_chain=chain,
    )
    assert "Decision chain (from stored lineage, decision packet and prediction):" in body
    assert "underlier trend turned against the option" in body
    assert body.index("Decision chain") < body.index("Decision detail:")
