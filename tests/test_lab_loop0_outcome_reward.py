"""OI-LAB-LOOP0 Step 6 — closed round-trip outcome + versioned reward."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.lab_experience import (
    ACTION_BLOCKED_BUY,
    ACTION_ROUND_TRIP,
    LIFECYCLE_OUTCOME,
    LIFECYCLE_REWARD,
    REWARD_VERSION,
    attach_round_trip_l10,
    build_blocked_buy_experience,
    compute_reward,
    compute_round_trip_outcome,
    record_blocked_buy,
)
from atlas.investment.learning_objects import (
    load_learning_events,
    record_from_trade_close,
    summarize_learning_day,
)

_DAY = "2026-09-17"
_L10 = (
    "laboratory_id",
    "as_of_ist",
    "instrument",
    "state",
    "features",
    "action",
    "entry",
    "exit",
    "pnl",
    "costs",
    "reward",
    "regime",
    "strategy_version",
)


def _trade(**extra):
    row = {
        "id": "t-astral-close",
        "side": "sell",
        "quantity": 5,
        "price": 1540.0,
        "fee": 2.5,
        "fees": {"brokerage": 2.5},
        "realized_pnl": -19.7,
        "buy_price": 1543.44,
        "bought_at": "2026-09-17T03:50:00+00:00",
        "sold_at": "2026-09-17T09:50:00+00:00",
        "buy_trade_id": "t-astral-open",
    }
    row.update(extra)
    return row


def test_reward_matches_book_pnl_not_a_second_model():
    oc = compute_round_trip_outcome(_trade())
    assert oc["realized_pnl"] == -19.7
    assert oc["entry_price"] == 1543.44
    assert oc["exit_price"] == 1540.0
    reward = compute_reward(oc)
    assert reward is not None
    assert reward["version"] == REWARD_VERSION
    assert reward["status"] == "computed"
    assert reward["value"] == -19.7
    assert reward["sign"] == "negative"
    assert reward["mutates_strategy"] is False


def test_reward_inferred_entry_uses_ledger_identity():
    oc = compute_round_trip_outcome(
        {
            "quantity": 5,
            "price": 1540.0,
            "fee": 2.5,
            "realized_pnl": -19.7,
        }
    )
    # avg = exit - (pnl + fee) / qty
    assert oc["entry_price"] == round(1540.0 - (-19.7 + 2.5) / 5, 6)
    assert compute_reward(oc)["value"] == -19.7


def test_blocked_buy_has_no_reward():
    assert compute_reward({"realized_pnl": 12.0}, experience_type=ACTION_BLOCKED_BUY) is None
    assert compute_reward({"realized_pnl": 12.0}, not_a_trade=True) is None
    exp = build_blocked_buy_experience(
        laboratory_id="india_equity_learner",
        symbol="YESBANK.NS",
        strategy_tag="plc_a_hold",
        reason="YESBANK.NS: plc_a_hold (pe)",
        as_of_ist=_DAY,
    )
    assert exp["reward"] is None
    assert exp["pnl"] is None


def test_missing_pnl_does_not_invent_reward():
    oc = compute_round_trip_outcome({"quantity": 2, "price": 100.0, "fee": 1.0})
    reward = compute_reward(oc)
    assert reward["status"] == "unknown"
    assert reward["value"] is None


def test_close_writes_l10_outcome_reward_and_lineage(tmp_path: Path):
    pkt = {
        "id": "d-astral-1",
        "decision_id": "d-astral-1",
        "action": "sell",
        "symbol": "ASTRAL.NS",
        "strategy_tag": "eod_flatten",
        "expected": {"expected_return": 0.01, "expected_direction": "up"},
        "observation_ids": ["obs-1"],
        "market_snapshot": {
            "intraday_tape": {"ist_date": _DAY, "interval": "5m", "bar_count": 48},
        },
        "meta": {"indicators": {"rsi": 61.0, "sma_fast": 1541.0, "sma_slow": 1538.0}},
    }
    out = record_from_trade_close(
        tmp_path,
        symbol="ASTRAL.NS",
        trade=_trade(),
        laboratory_id="equity_intraday_learner",
        packet=pkt,
        strategy_tag="eod_flatten",
        indicators={"rsi": 61.0, "sma_fast": 1541.0, "sma_slow": 1538.0},
    )
    assert out.get("ok") is True
    assert out.get("skipped") is False
    rows = [
        r
        for r in load_learning_events(tmp_path, "equity_intraday_learner")
        if r.get("kind") == "EXPERIENCE"
    ]
    assert len(rows) == 1
    exp = rows[0]
    for key in _L10:
        assert key in exp
    assert exp["experience_type"] == ACTION_ROUND_TRIP
    assert exp["lifecycle"] == LIFECYCLE_REWARD
    assert exp["pnl"] == -19.7
    assert exp["entry"]["price"] == 1543.44
    assert exp["exit"]["price"] == 1540.0
    assert exp["costs"]["fee"] == 2.5
    assert exp["reward"]["value"] == -19.7
    assert exp["reward"]["mutates_strategy"] is False
    assert exp["strategy_version"]
    assert exp["features"]["rsi"] == 61.0
    assert exp["evidence_lineage"]["decision_id"] == "d-astral-1"
    assert exp["lab_fields"]["intraday_tape"]["interval"] == "5m"

    dup = record_from_trade_close(
        tmp_path,
        symbol="ASTRAL.NS",
        trade=_trade(),
        laboratory_id="equity_intraday_learner",
        packet=pkt,
        strategy_tag="eod_flatten",
    )
    assert dup.get("skipped") is True
    experiences = [
        r
        for r in load_learning_events(tmp_path, "equity_intraday_learner")
        if r.get("kind") == "EXPERIENCE"
    ]
    assert len(experiences) == 1


def test_summarize_counts_useful_round_trips_not_blocked_buys(tmp_path: Path):
    record_from_trade_close(
        tmp_path,
        symbol="ASTRAL.NS",
        trade=_trade(),
        laboratory_id="equity_intraday_learner",
        strategy_tag="eod_flatten",
    )
    record_blocked_buy(
        tmp_path,
        laboratory_id="equity_intraday_learner",
        symbol="YESBANK.NS",
        strategy_tag="pack_block",
        reason="YESBANK.NS: pack_block (qty)",
    )
    rows = load_learning_events(tmp_path, "equity_intraday_learner")
    summary = summarize_learning_day(rows)
    assert summary["blocked_buys"] == 1
    assert summary["rewards_computed"] == 1
    assert summary["useful_experiences"] == 1


def test_attach_unknown_pnl_stays_outcome_not_reward():
    exp = attach_round_trip_l10(
        {"kind": "EXPERIENCE", "event_kind": "exit"},
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        trade={"side": "sell", "quantity": 1, "price": 1400.0},
        as_of_ist=_DAY,
    )
    assert exp["lifecycle"] == LIFECYCLE_OUTCOME
    assert exp["reward"]["status"] == "unknown"
    assert exp["reward"]["value"] is None
