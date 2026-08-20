"""LOOP0 L4 — NIFTY index-proxy paper lot (honest label, margin not notional)."""

from __future__ import annotations

import pytest

from atlas.investment.index_proxy_lot import (
    KPI_LABEL,
    MARGIN_FRACTION,
    VALUATION_BASIS,
    close_cash_credit,
    is_fno_lab,
    is_nifty_underlier,
    laboratory_kpi_label,
    lot_units,
    margin_required,
    open_cash_debit,
    rewrite_snapshot,
    size_one_lot,
    underlier_family,
    uses_index_proxy_collateral,
)
from atlas.investment.plc_buy_gates import plc_a_enabled
from atlas.investment.session_notes import classify_action
from atlas.investment.trading_kpis import build_trading_kpis, format_kpi_section
from atlas.trading.portfolio import PortfolioError, PortfolioService

from tests.test_trading_portfolio import InMemorySimRepo


def test_nifty_lot_is_25_even_on_yahoo_underlier():
    assert lot_units("NIFTY") == 25
    assert lot_units("^NSEI") == 25
    assert lot_units("NIFTY-FUT") == 25
    assert lot_units("BANKNIFTY") == 15
    assert is_nifty_underlier("NIFTY")
    assert is_nifty_underlier("^NSEI")
    assert underlier_family("BANKNIFTY") == "banknifty"
    assert not is_nifty_underlier("RELIANCE.NS")


def test_fno_lab_detection_and_plc_a_off():
    assert is_fno_lab({}, "india_fno_learner")
    assert is_fno_lab({"asset_class": "futures"}, "default")
    assert not is_fno_lab({}, "india_equity_learner")
    assert plc_a_enabled({}, "india_fno_learner") is False


def test_size_one_lot_passes_margin_on_100k_cash():
    sized = size_one_lot(symbol="NIFTY", price=24154.0, cash=100_000.0, held=0.0)
    assert sized["ok"] is True
    assert sized["qty"] == 25.0
    assert sized["lot_size"] == 25
    assert sized["margin"] == pytest.approx(margin_required(25, 24154.0))
    assert sized["margin"] < 100_000.0
    assert sized["strategy_tag"] == "index_proxy_lot"


def test_size_one_lot_blocks_thin_cash():
    sized = size_one_lot(symbol="NIFTY", price=24154.0, cash=1_000.0, held=0.0)
    assert sized["ok"] is False
    assert "insufficient margin" in sized["reason"]
    assert sized["strategy_tag"] == "margin"


def test_size_one_lot_max_one_open():
    sized = size_one_lot(symbol="NIFTY", price=24154.0, cash=100_000.0, held=25.0)
    assert sized["ok"] is False
    assert sized["reason"].startswith("already_open")


def test_collateral_only_for_whole_lots():
    assert uses_index_proxy_collateral("NIFTY", 25) is True
    assert uses_index_proxy_collateral("NIFTY", 1) is False
    assert uses_index_proxy_collateral("CIPLA.NS", 13) is False


def test_honesty_labels_are_not_live_futures():
    assert VALUATION_BASIS == "index_proxy daily underlier"
    assert laboratory_kpi_label() == "NIFTY index-proxy laboratory performance"
    assert "F&O performance" not in KPI_LABEL
    assert "live futures" not in VALUATION_BASIS


def test_classify_margin_idle_reason():
    assert classify_action(
        "NIFTY: margin (insufficient margin: need ~72462.00 (12% of notional 603850.00); cash=1000.00)"
    ) == "margin"


def test_paper_book_debits_margin_not_notional():
    svc = PortfolioService(InMemorySimRepo())
    p = svc.ensure_portfolio(mission_id=None, starting_cash=100_000.0)
    px = 24154.0
    qty = 25.0
    svc.apply_trade(p["id"], symbol="NIFTY", side="buy", quantity=qty, price=px)
    posted = open_cash_debit(qty, px)
    snap = svc.snapshot(p["id"], prices={"NIFTY": px})
    assert snap["cash"] == pytest.approx(100_000.0 - posted)
    # Equity stays ~ starting (cash + posted margin + 0 variation)
    assert snap["equity"] == pytest.approx(100_000.0)
    assert snap["valuation_basis"] == VALUATION_BASIS
    assert snap["holdings_value"] == pytest.approx(posted)
    # Full notional must not be booked as cash-equity holdings
    assert snap["holdings_value"] < qty * px * 0.5


def test_index_proxy_mark_and_close():
    svc = PortfolioService(InMemorySimRepo())
    p = svc.ensure_portfolio(mission_id=None, starting_cash=100_000.0)
    entry = 24154.0
    exit_px = 24200.0
    qty = 25.0
    svc.apply_trade(p["id"], symbol="NIFTY", side="buy", quantity=qty, price=entry)
    snap = svc.snapshot(p["id"], prices={"NIFTY": exit_px})
    variation = (exit_px - entry) * qty
    assert snap["unrealized_pnl"] == pytest.approx(variation)
    assert snap["equity"] == pytest.approx(100_000.0 + variation)
    trade = svc.apply_trade(p["id"], symbol="NIFTY", side="sell", quantity=qty, price=exit_px)
    assert trade["realized_pnl"] == pytest.approx(variation)
    closed = svc.snapshot(p["id"])
    assert svc.position(p["id"], "NIFTY") is None
    assert closed["cash"] == pytest.approx(100_000.0 + variation)
    assert closed["equity"] == pytest.approx(100_000.0 + variation)


def test_index_proxy_rejected_when_margin_exceeds_cash():
    svc = PortfolioService(InMemorySimRepo())
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1_000.0)
    with pytest.raises(PortfolioError):
        svc.apply_trade(p["id"], symbol="NIFTY", side="buy", quantity=25, price=24154.0)


def test_cash_equity_unchanged():
    svc = PortfolioService(InMemorySimRepo())
    p = svc.ensure_portfolio(mission_id=None, starting_cash=1000.0)
    svc.apply_trade(p["id"], symbol="ACME", side="buy", quantity=10, price=20.0)
    snap = svc.snapshot(p["id"], prices={"ACME": 20.0})
    assert snap["cash"] == 800.0
    assert snap["equity"] == 1000.0


def test_rewrite_snapshot_idempotent():
    snap = {
        "cash": 27_538.0,
        "starting_cash": 100_000.0,
        "positions": [
            {
                "symbol": "NIFTY",
                "quantity": 25.0,
                "avg_price": 24154.0,
                "mark": 24154.0,
                "value": 27_538.0,
                "unrealized_pnl": 0.0,
            }
        ],
    }
    once = rewrite_snapshot(snap)
    twice = rewrite_snapshot(once)
    assert once["equity"] == pytest.approx(twice["equity"])
    assert once["valuation_basis"] == VALUATION_BASIS


def test_kpi_section_uses_laboratory_name():
    kpis = build_trading_kpis(
        portfolio={
            "portfolio_key": "india_fno_learner",
            "cash": 100_000,
            "equity": 100_000,
            "valuation_basis": VALUATION_BASIS,
        }
    )
    assert kpis["kpi_label"] == KPI_LABEL
    text = "\n".join(format_kpi_section(kpis))
    assert KPI_LABEL in text
    assert "F&O performance" not in text


def test_close_credit_returns_margin_plus_variation():
    qty, entry, exit_px = 25.0, 24154.0, 24200.0
    credit = close_cash_credit(qty, entry, exit_px)
    assert credit == pytest.approx(
        open_cash_debit(qty, entry) + (exit_px - entry) * qty
    )
    assert MARGIN_FRACTION == 0.12
