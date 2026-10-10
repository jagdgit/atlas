"""P3 — F&O planned_symbols honesty + nine-line lab contract."""

from __future__ import annotations

import pytest

from atlas.investment.lab_status_contract import (
    assert_fno_planned_symbols_honest,
    sanitize_fno_planned_symbols,
)
from atlas.investment.trading_kpis import build_trading_kpis


def test_fno_cash_watchlist_is_rejected():
    cleaned = sanitize_fno_planned_symbols(
        ["HFCL.NS", "IDEA.NS", "SUNTV.NS", "TRENT.NS", "ICICIGI.NS"],
        laboratory_id="india_fno_learner",
    )
    assert cleaned["planned_symbols"] == []
    assert cleaned["planned_symbols_status"] == "contaminated_cash_watchlist"
    with pytest.raises(AssertionError):
        assert_fno_planned_symbols_honest(
            ["HFCL.NS", "IDEA.NS"], laboratory_id="india_fno_learner"
        )


def test_fno_option_contracts_pass():
    cleaned = sanitize_fno_planned_symbols(
        ["WIPRO26OCT160CE", "WIPRO26OCT160PE"],
        laboratory_id="india_fno_learner",
    )
    assert cleaned["planned_symbols_status"] == "ok"
    assert "WIPRO26OCT160CE" in cleaned["planned_symbols"]
    assert_fno_planned_symbols_honest(
        cleaned["planned_symbols"], laboratory_id="india_fno_learner"
    )


def test_equity_lab_keeps_ns_names():
    cleaned = sanitize_fno_planned_symbols(
        ["HBLPOWER.NS", "SUNTV.NS"], laboratory_id="india_equity_learner"
    )
    assert cleaned["planned_symbols"] == ["HBLPOWER.NS", "SUNTV.NS"]


def test_build_trading_kpis_strips_fno_contamination():
    kpis = build_trading_kpis(
        portfolio={"portfolio_key": "india_fno_learner", "cash": 1, "positions": []},
        plan={
            "portfolio_key": "india_fno_learner",
            "candidates": [
                {"symbol": "HFCL.NS"},
                {"symbol": "IDEA.NS"},
                {"symbol": "TRENT.NS"},
            ],
        },
        session_note={"portfolio_key": "india_fno_learner"},
        ist_date="2026-10-09",
    )
    assert kpis["planned_symbols"] == []
    assert kpis["planned_symbols_status"] == "contaminated_cash_watchlist"
    assert kpis["candidates_planned"] == 0
