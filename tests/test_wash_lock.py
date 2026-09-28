"""P0-A / OI-LAB-LOOP0 — swing wash-lock: execution invariant, not a counter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.investment.wash_lock import (
    REASON_CONCENTRATION,
    REASON_REENTRY,
    applies_to_lab,
    challenger_breaches_concentration,
    hydrate_from_fills,
    record_sale,
    reentry_blocked,
)


def test_all_in_switch_to_hblpower_is_blocked():
    # After an IDEA fill, cash ≈ ₹45.6k + IDEA proceeds ≈ ₹10k → 73 × 760 ≈ 100% of book.
    out = challenger_breaches_concentration(
        equity=55_357.0,
        cash=45_597.0,
        hold_qty=717.0,
        hold_px=13.92,
        chal_px=760.0,
        cfg={"plc_b_max_name_pct": 0.40},
    )
    assert out["blocked"] is True
    assert out["reason_code"] == REASON_CONCENTRATION
    assert out["weight"] > 0.90


def test_small_challenger_inside_cap_is_allowed():
    out = challenger_breaches_concentration(
        equity=100_000.0,
        cash=50_000.0,
        hold_qty=10.0,
        hold_px=100.0,
        chal_px=200.0,
        cfg={"plc_b_max_name_pct": 0.40},
    )
    # cash after sell = 51,000 → 255 shares × 200 = 51,000 / 100,000 = 51% still blocked
    assert out["blocked"] is True
    out2 = challenger_breaches_concentration(
        equity=100_000.0,
        cash=10_000.0,
        hold_qty=10.0,
        hold_px=100.0,
        chal_px=500.0,
        cfg={"plc_b_max_name_pct": 0.40},
    )
    # cash after = 11,000 → 22 × 500 = 11,000 / 100,000 = 11%
    assert out2["blocked"] is False
    assert out2["buy_qty"] == 22


def test_buy_sell_buy_same_day_blocked():
    """BUY → SELL (flat) → BUY same IST day must block — execution invariant."""
    state: dict = {}
    day = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    record_sale(
        state,
        "COALINDIA.NS",
        reason="sma_crossunder",
        now=day,
        remaining_qty=0.0,
    )
    hit = reentry_blocked(state, "COALINDIA.NS", now=day)
    assert hit["blocked"] is True
    assert hit["reason_code"] == REASON_REENTRY
    assert "BUY blocked" in str(hit.get("honesty") or "")
    # Different symbol still allowed
    miss = reentry_blocked(state, "HBLPOWER.NS", now=day)
    assert miss["blocked"] is False


def test_buy_sell_next_day_buy_allowed():
    state: dict = {}
    day1 = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    day2 = day1 + timedelta(days=1)
    record_sale(
        state,
        "COALINDIA.NS",
        reason="sma_crossunder",
        now=day1,
        remaining_qty=0.0,
    )
    assert reentry_blocked(state, "COALINDIA.NS", now=day1)["blocked"] is True
    assert reentry_blocked(state, "COALINDIA.NS", now=day2)["blocked"] is False


def test_partial_sell_does_not_lock_reentry():
    """BUY → partial SELL → BUY is allowed (still long after trim)."""
    state: dict = {}
    day = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    record_sale(
        state,
        "COALINDIA.NS",
        reason="plc_b_trim",
        now=day,
        remaining_qty=10.0,
    )
    assert reentry_blocked(state, "COALINDIA.NS", now=day)["blocked"] is False


def test_hydrate_from_fills_blocks_second_buy_even_if_state_empty():
    """Canonical ledger wins over a lost worker checkpoint."""
    day = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)  # ~10:30 IST
    trades = [
        {
            "symbol": "COALINDIA.NS",
            "side": "buy",
            "quantity": 19,
            "created_at": day.isoformat(),
        },
        {
            "symbol": "COALINDIA.NS",
            "side": "sell",
            "quantity": 19,
            "created_at": (day + timedelta(minutes=5)).isoformat(),
            "reason": "switch_exploratory",
        },
    ]
    state: dict = {}
    # Flat book now (after the sell); seed open_positions=[] 
    hydrate_from_fills(
        state, trades, now=day + timedelta(minutes=10), open_positions=[]
    )
    hit = reentry_blocked(state, "COALINDIA.NS", now=day + timedelta(minutes=10))
    assert hit["blocked"] is True
    assert hit["reason_code"] == REASON_REENTRY
    # Proof is blocked=True — not merely that a counter incremented.
    assert hit.get("prior_sale")


def test_hydrate_overnight_partial_sell_does_not_false_lock():
    """Partial sell of overnight inventory must not lock (still long)."""
    day = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)
    # Overnight 20 shares; today sold 5; still hold 15.
    trades = [
        {
            "symbol": "X.NS",
            "side": "sell",
            "quantity": 5,
            "created_at": day.isoformat(),
        },
    ]
    state: dict = {}
    hydrate_from_fills(
        state,
        trades,
        now=day + timedelta(minutes=10),
        open_positions=[{"symbol": "X.NS", "quantity": 15}],
    )
    assert reentry_blocked(state, "X.NS", now=day + timedelta(minutes=10))[
        "blocked"
    ] is False


def test_hydrate_partial_then_flat_locks():
    day = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)
    trades = [
        {"symbol": "X.NS", "side": "buy", "quantity": 20, "created_at": day.isoformat()},
        {
            "symbol": "X.NS",
            "side": "sell",
            "quantity": 5,
            "created_at": (day + timedelta(minutes=1)).isoformat(),
        },
        {
            "symbol": "X.NS",
            "side": "sell",
            "quantity": 15,
            "created_at": (day + timedelta(minutes=2)).isoformat(),
            "reason": "sma_crossunder",
        },
    ]
    state: dict = {}
    # After partial only — still long → not locked
    hydrate_from_fills(
        state,
        trades[:2],
        now=day + timedelta(minutes=1),
        open_positions=[{"symbol": "X.NS", "quantity": 15}],
    )
    assert reentry_blocked(state, "X.NS", now=day + timedelta(minutes=1))[
        "blocked"
    ] is False
    hydrate_from_fills(
        state, trades, now=day + timedelta(minutes=3), open_positions=[]
    )
    assert reentry_blocked(state, "X.NS", now=day + timedelta(minutes=3))[
        "blocked"
    ] is True


def test_wash_lock_is_swing_only():
    assert applies_to_lab("india_equity_learner") is True
    assert applies_to_lab("equity_intraday_learner") is False
    assert applies_to_lab("india_fno_learner") is False
