"""CF.1 / OI-CF0 — Counterfactual Learning hermetic tests."""

from __future__ import annotations

from atlas.investment.counterfactual_learning import (
    close_on_bars,
    evaluate_due_cfs,
    format_counterfactual_section,
    pick_top_alternative,
    schedule_cf,
)


def test_pick_top_alternative_excludes_self():
    ranked = [
        {"symbol": "EICHERMOT.NS", "rank": 1},
        {"symbol": "APOLLOHOSP.NS", "rank": 2},
    ]
    alt = pick_top_alternative("EICHERMOT.NS", ranked=ranked)
    assert alt is not None
    assert alt["symbol"] == "APOLLOHOSP.NS"


def test_schedule_and_evaluate_beat_alt(tmp_path):
    prices = {
        ("EICHERMOT.NS", "2026-07-01"): 100.0,
        ("EICHERMOT.NS", "2026-07-31"): 108.0,  # +8%
        ("^NSEI", "2026-07-01"): 1000.0,
        ("^NSEI", "2026-07-31"): 1020.0,  # +2%
        ("APOLLOHOSP.NS", "2026-07-01"): 200.0,
        ("APOLLOHOSP.NS", "2026-07-31"): 210.0,  # +5%
    }

    def price_fn(sym: str, day: str) -> float | None:
        return prices.get((sym, day[:10]))

    row = schedule_cf(
        tmp_path,
        decision_id="dec-1",
        symbol="EICHERMOT.NS",
        entry_price=100.0,
        entry_ist="2026-07-01",
        laboratory_id="india_equity_learner",
        alt={"symbol": "APOLLOHOSP.NS", "rank": 2},
    )
    assert row is not None
    assert row["horizons"][0]["horizon_d"] == 30
    assert row["horizons"][0]["due_ist"] == "2026-07-31"

    out = evaluate_due_cfs(
        tmp_path,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-07-31",
        price_fn=price_fn,
    )
    assert out["completed"] == 1
    h = out["rows"][0]["horizons"][0]
    assert h["status"] == "done"
    assert h["actual_return"] == 8.0
    assert h["alt_return"] == 5.0
    assert h["index_return"] == 2.0
    assert h["verdict"] == "beat"  # 8 > 5

    lines = format_counterfactual_section(out["rows"])
    assert any("beat" in x for x in lines)


def test_evaluate_missing_prices_unknown(tmp_path):
    schedule_cf(
        tmp_path,
        decision_id="dec-2",
        symbol="TCS.NS",
        entry_price=50.0,
        entry_ist="2026-07-01",
        laboratory_id="lab",
        alt={"symbol": "INFY.NS", "rank": 1},
    )

    def price_fn(sym: str, day: str) -> float | None:
        return None

    out = evaluate_due_cfs(
        tmp_path,
        laboratory_id="lab",
        as_of_ist="2026-08-01",
        price_fn=price_fn,
    )
    assert out["missing_prices"] >= 1
    h = out["rows"][0]["horizons"][0]
    assert h["status"] == "missing_prices"
    assert h["verdict"] == "unknown"


def test_close_on_bars_picks_on_or_before():
    bars = [
        {"date": "2026-07-01", "close": 10.0},
        {"date": "2026-07-03", "close": 12.0},
        {"date": "2026-07-05", "close": 11.0},
    ]
    assert close_on_bars(bars, "2026-07-04") == 12.0
    assert close_on_bars(bars, "2026-06-30") is None


def test_schedule_skips_invalid_buy(tmp_path):
    assert schedule_cf(tmp_path, decision_id="x", symbol="A", entry_price=None) is None
    assert (
        schedule_cf(
            tmp_path, decision_id="x", symbol="A", action="sell", entry_price=10.0
        )
        is None
    )
