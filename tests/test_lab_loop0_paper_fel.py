"""OI-LAB-LOOP0 Step 7 — paper experiences become a FEL dataset and belief."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.investment.fel.experiments.dispatch import process_one
from atlas.investment.fel.experiments.paper_round_trip import (
    KIND,
    MIN_SAMPLE,
    enqueue_if_sample_grew,
    evaluate_vs_cash,
    experiences_to_dataset,
    hypothesis_id_for,
    load_round_trip_experiences,
    run_paper_round_trip,
)
from atlas.investment.fel.experiments.store import load_experiment
from atlas.investment.fel.promotion import LIVE_CONTROL
from atlas.investment.hypothesis_learning import get_hypothesis
from atlas.investment.laboratory import LaboratoryContaminationError
from atlas.investment.learning_objects import record_from_trade_close
from atlas.investment.lab_experience import record_blocked_buy


def _close(tmp_path: Path, *, symbol: str, pnl: float, trade_id: str, rsi: float = 55.0):
    return record_from_trade_close(
        tmp_path,
        symbol=symbol,
        trade={
            "id": trade_id,
            "side": "sell",
            "quantity": 2,
            "price": 100.0,
            "fee": 1.0,
            "realized_pnl": pnl,
            "buy_price": 100.0 - (pnl + 1.0) / 2,
        },
        laboratory_id="equity_intraday_learner",
        strategy_tag="eod_flatten",
        indicators={"rsi": rsi, "sma_fast": 101.0, "sma_slow": 99.0},
    )


def test_blocked_buy_and_fno_do_not_enter_equity_dataset(tmp_path: Path):
    _close(tmp_path, symbol="ASTRAL.NS", pnl=-5.0, trade_id="t1")
    record_blocked_buy(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        symbol="YESBANK.NS",
        strategy_tag="plc_a_hold",
        reason="YESBANK.NS: plc_a_hold (pe)",
    )
    exps = load_round_trip_experiences(tmp_path, "equity_intraday_learner")
    assert len(exps) == 1
    assert exps[0]["instrument"]["symbol"] == "ASTRAL.NS"
    mixed = list(exps) + [
        {
            "laboratory_id": "equity_intraday_learner",
            "experience_type": "round_trip",
            "reward": {"status": "computed", "value": 1.0, "return_pct": 0.1},
            "features": {},
            "instrument": {"symbol": "NIFTY", "nfo_tradingsymbol": "NIFTYNEARFUT"},
            "lab_fields": {"fno_contract": {"tradingsymbol": "NIFTYNEARFUT"}},
        }
    ]
    with pytest.raises(LaboratoryContaminationError):
        experiences_to_dataset(mixed, laboratory_id="equity_intraday_learner")


def test_thin_sample_is_invalid_and_never_live(tmp_path: Path):
    _close(tmp_path, symbol="ASTRAL.NS", pnl=-5.0, trade_id="t-thin")
    doc = run_paper_round_trip(tmp_path, laboratory_id="equity_intraday_learner")
    assert doc["result"] == "invalid"
    assert "insufficient_sample" in doc["reason"]
    assert doc["promotion"] == "never"
    assert doc["promotion"] != LIVE_CONTROL
    assert doc["mutates_strategy"] is False
    hyp = get_hypothesis(
        tmp_path, hypothesis_id_for("equity_intraday_learner"), laboratory_id="equity_intraday_learner"
    )
    assert hyp is not None
    assert hyp["status"] == "inconclusive"


def test_losing_book_rejects_hypothesis_as_durable_finding(tmp_path: Path):
    for i in range(MIN_SAMPLE):
        _close(tmp_path, symbol="ASTRAL.NS", pnl=-10.0 - i, trade_id=f"t-loss-{i}")
    queued = enqueue_if_sample_grew(tmp_path, laboratory_id="equity_intraday_learner")
    assert queued["ok"] is True
    out = process_one(str(tmp_path))
    assert out["status"] == "COMPLETED"
    assert out["summary"]["result"] == "worse"
    assert out["summary"]["promotion"] == "never"
    doc = load_experiment(
        tmp_path,
        "E-paper-round-trip-equity_intraday_learner",
        laboratory_id="equity_intraday_learner",
    )
    assert doc is not None
    assert doc["belief"]["note"] == "this hypothesis did not survive"
    assert doc["hypothesis"]["status"] == "rejected"
    finding = (
        tmp_path
        / "investment"
        / "fel"
        / "findings"
        / "equity_intraday_learner"
        / "E-paper-round-trip-equity_intraday_learner.json"
    )
    assert finding.is_file()
    text = finding.read_text(encoding="utf-8")
    assert "this hypothesis did not survive" in text or "did_not_survive" in text
    assert "not_vector_memory" in text
    ds = tmp_path / "investment" / "fel" / "datasets" / "equity_intraday_learner"
    assert any(p.suffix == ".jsonl" for p in ds.glob("*.jsonl"))


def test_positive_mean_still_not_live_control(tmp_path: Path):
    for i in range(MIN_SAMPLE):
        _close(tmp_path, symbol="ASTRAL.NS", pnl=8.0 + i, trade_id=f"t-win-{i}")
    ev = evaluate_vs_cash(
        experiences_to_dataset(
            load_round_trip_experiences(tmp_path, "equity_intraday_learner"),
            laboratory_id="equity_intraday_learner",
        )
    )
    assert ev["result"] == "no_significant"
    assert ev["promotion"] in {"never", "candidate"}
    assert ev["promotion"] != LIVE_CONTROL
    assert ev["mutates_strategy"] is False


def test_enqueue_idempotent_until_sample_grows(tmp_path: Path):
    for i in range(MIN_SAMPLE):
        _close(tmp_path, symbol="ASTRAL.NS", pnl=-4.0, trade_id=f"t-a-{i}")
    a = enqueue_if_sample_grew(tmp_path, laboratory_id="equity_intraday_learner")
    process_one(str(tmp_path))
    b = enqueue_if_sample_grew(tmp_path, laboratory_id="equity_intraday_learner")
    assert b.get("skipped") is True
    _close(tmp_path, symbol="ASTRAL.NS", pnl=-4.0, trade_id="t-a-extra")
    c = enqueue_if_sample_grew(tmp_path, laboratory_id="equity_intraday_learner")
    assert c.get("skipped") is not True
    assert c["item"]["status"] == "QUEUED"
    assert c["item"]["kind"] == KIND
