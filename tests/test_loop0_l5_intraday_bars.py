"""LOOP0 L5 — 5-minute bars for the equity intraday lab (hermetic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.investment.intraday_bars import (
    MAX_SYMBOLS,
    VALUATION_BASIS,
    clamp_intraday_universe,
    is_intraday_lab,
    load_day_bars,
    persist_day_bars,
)
from atlas.investment.lab_book_reset import void_book_to_starting_cash
from atlas.investment.portfolios import default_decision_config
from atlas.investment.session_notes import classify_action
from atlas.trading.market_reader import MarketReaderService
from atlas.trading.portfolio import PortfolioService
from atlas.workers.paper_trading import skip_cash_alts_for_lab

from tests.test_trading_portfolio import InMemorySimRepo


def _chart(timestamps, closes):
    n = len(timestamps)
    return {
        "chart": {
            "result": [
                {
                    "timestamp": list(timestamps),
                    "indicators": {
                        "quote": [
                            {
                                "open": list(closes),
                                "high": list(closes),
                                "low": list(closes),
                                "close": list(closes),
                                "volume": [1] * n,
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_is_intraday_lab_and_skip_alts():
    assert is_intraday_lab({}, "equity_intraday_learner")
    assert not is_intraday_lab({}, "india_equity_learner")
    assert skip_cash_alts_for_lab({}, portfolio_key="equity_intraday_learner")
    assert not skip_cash_alts_for_lab({}, portfolio_key="india_equity_learner")
    assert classify_action("next_alt: skipped (intraday_yahoo_budget)") == "intraday_yahoo_budget"


def test_default_intraday_auto_max_is_three():
    cfg = default_decision_config(
        {
            "portfolio_key": "equity_intraday_learner",
            "asset_class": "cash_equity",
            "persona": {"capital": 50000, "allowed_assets": ["cash_equity"]},
        }
    )
    assert cfg["auto_max_instruments"] == MAX_SYMBOLS
    assert cfg["market_session"] == "nse_equity"


def test_clamp_open_book_first():
    rows = [{"symbol": f"S{i}.NS"} for i in range(8)]
    out = clamp_intraday_universe(rows, open_symbols={"S7.NS"}, max_n=3)
    assert [r["symbol"] for r in out] == ["S7.NS", "S0.NS", "S1.NS"]


def test_persist_5m_does_not_touch_daily_store(tmp_path: Path):
    persist_day_bars(
        tmp_path,
        "RELIANCE.NS",
        [{"t": 1_000, "close": 10.0}, {"t": 1_300, "close": 10.5}],
        ist_date="2026-08-18",
    )
    bars = load_day_bars(tmp_path, "RELIANCE.NS", ist_date="2026-08-18")
    assert [b["t"] for b in bars] == [1000, 1300]
    assert not (tmp_path / "market" / "bars").exists()
    assert (tmp_path / "market" / "bars_intraday").is_dir()


def test_market_reader_5m_uses_intraday_store(tmp_path: Path):
    urls: list[str] = []

    def opener(url: str):
        urls.append(url)
        return _chart([1_000, 1_300, 1_600], [100.0, 101.0, 102.0])

    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=opener,
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
    )
    out = reader.bars_for(
        "RELIANCE.NS", provider="yahoo", interval="5m", range="1d", limit=10
    )
    assert out["interval"] == "5m"
    assert out["source"] == "yahoo_intraday"
    assert "interval=5m" in urls[0]
    assert "range=1d" in urls[0]
    assert (tmp_path / "market" / "bars").exists() is False or not any(
        (tmp_path / "market" / "bars").glob("*.json")
    )
    stored = load_day_bars(tmp_path, "RELIANCE.NS")
    assert len(stored) >= 3
    # TTL cache: second call must not hit Yahoo again
    out2 = reader.bars_for(
        "RELIANCE.NS", provider="yahoo", interval="5m", range="1d", limit=10
    )
    assert out2["note"] == "intraday_cache"
    assert len(urls) == 1
    assert VALUATION_BASIS == "yahoo 5m session bars"


def test_5m_cooldown_returns_persisted_stale(tmp_path: Path, monkeypatch):
    persist_day_bars(
        tmp_path,
        "TCS.NS",
        [{"t": 2_000, "close": 50.0}],
        ist_date="2026-08-18",
    )
    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=lambda url: (_ for _ in ()).throw(RuntimeError("no net")),
        data_dir=str(tmp_path),
    )
    monkeypatch.setattr(reader, "_yahoo_cooldown_s", lambda: 90.0)
    monkeypatch.setattr(reader, "_may_network_refresh", lambda: False)
    # Force IST date file: persist used 2026-08-18; load_day_bars defaults to today.
    # Re-persist onto today's IST date so stale load finds it.
    persist_day_bars(tmp_path, "TCS.NS", [{"t": 2_000, "close": 50.0}])
    out = reader.bars_for("TCS.NS", provider="yahoo", interval="5m", range="1d")
    assert out["source"] == "bars_intraday_stale"
    assert "yahoo_cooldown" in (out.get("note") or "")
    assert out["bars"][-1]["close"] == 50.0


def test_void_book_restores_starting_cash():
    repo = InMemorySimRepo()
    svc = PortfolioService(repo)
    p = svc.ensure_portfolio(mission_id="m-intraday", name="equity_intraday_learner", starting_cash=50_000)
    svc.apply_trade(p["id"], symbol="CIPLA.NS", side="buy", quantity=10, price=1400.0)
    assert float(svc.snapshot(p["id"])["cash"]) < 50_000
    out = void_book_to_starting_cash(
        repo,
        p["id"],
        note="L5 void — daily-bar fills were not true intraday",
        mission_id="m-intraday",
    )
    assert out["ok"] is True
    snap = svc.snapshot(p["id"])
    assert snap["cash"] == pytest.approx(50_000)
    assert snap["positions"] == []
    assert repo.count_trades(p["id"]) == 0
    assert repo.list_positions(p["id"]) == []
