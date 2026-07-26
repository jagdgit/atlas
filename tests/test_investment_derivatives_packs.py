"""IL.11 follow-on — ready futures/options packs (hermetic)."""

from __future__ import annotations

from datetime import date, timedelta

from atlas.investment.packs import list_packs, resolve_pack
from atlas.investment.packs.derivatives import FuturesPack, OptionsPack, default_lot_size
from atlas.trading.broker_profiles import compute_fees, get_broker_profile


def test_list_packs_marks_fno_ready():
    packs = {p["id"]: p for p in list_packs()}
    assert packs["futures"]["ready"] is True
    assert packs["options"]["ready"] is True
    assert packs["commodity"]["ready"] is False
    assert packs["crypto"]["ready"] is False


def test_nifty_default_lot_size():
    assert default_lot_size("NIFTY-FUT") == 25
    assert default_lot_size("RELIANCE-FUT") == 1
    assert default_lot_size("X", context={"lot_size": 50}) == 50


def test_futures_rejects_non_lot_multiple():
    pack = FuturesPack()
    bad = pack.validate_order(
        side="buy",
        symbol="NIFTY-FUT",
        quantity=10,
        price=22000.0,
        context={"cash": 1_000_000},
    )
    assert bad.ok is False
    assert "lot_size=25" in bad.reason


def test_futures_margin_gate():
    pack = FuturesPack()
    # 25 units * 22000 * 12% ≈ 66_000 required
    blocked = pack.validate_order(
        side="buy",
        symbol="NIFTY-FUT",
        quantity=25,
        price=22000.0,
        context={"cash": 10_000, "margin_fraction": 0.12},
    )
    assert blocked.ok is False
    assert "insufficient margin" in blocked.reason

    ok = pack.validate_order(
        side="buy",
        symbol="NIFTY-FUT",
        quantity=25,
        price=22000.0,
        context={"cash": 100_000, "margin_fraction": 0.12},
    )
    assert ok.ok is True


def test_futures_closing_skips_margin():
    pack = FuturesPack()
    ok = pack.validate_order(
        side="sell",
        symbol="NIFTY-FUT",
        quantity=25,
        price=22000.0,
        context={"cash": 0, "position_qty": 25},
    )
    assert ok.ok is True


def test_futures_expired_contract_blocked():
    pack = FuturesPack()
    past = (date.today() - timedelta(days=3)).isoformat()
    bad = pack.validate_order(
        side="buy",
        symbol="NIFTY-FUT",
        quantity=25,
        price=22000.0,
        context={"cash": 1_000_000, "expiry": past},
    )
    assert bad.ok is False
    assert "expired" in bad.reason


def test_futures_fee_overlay_lowers_stt_vs_equity_profile():
    pack = FuturesPack()
    equity = compute_fees(get_broker_profile("zerodha"), side="sell", quantity=25, price=100.0)
    overlaid = pack.fee_overlay(
        equity, side="sell", symbol="NIFTY-FUT", quantity=25, price=100.0
    )
    assert overlaid.stamp == 0.0
    assert overlaid.stt < equity.stt
    assert overlaid.stt == round(2500.0 * 0.0002, 4)


def test_options_write_requires_margin():
    pack = OptionsPack()
    bad = pack.validate_order(
        side="sell",
        symbol="NIFTY-CE",
        quantity=25,
        price=120.0,
        context={"cash": 100, "position_qty": 0, "underlying_price": 22000},
    )
    assert bad.ok is False
    assert "write" in bad.reason.lower() or "margin" in bad.reason.lower()


def test_options_long_premium_cash_gate():
    pack = OptionsPack()
    bad = pack.validate_order(
        side="buy",
        symbol="NIFTY-CE",
        quantity=25,
        price=120.0,
        context={"cash": 100, "position_qty": 0},
    )
    assert bad.ok is False
    assert "premium" in bad.reason.lower()


def test_resolve_pack_fno_ready():
    assert resolve_pack("futures").ready is True
    assert resolve_pack("options").ready is True
    assert resolve_pack("commodity").ready is False
