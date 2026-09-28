"""OI-LAB-LOOP0 Step 2 — Zerodha fetch must persist into bar_store / bars_intraday."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas.investment.bar_store import load_symbol_doc, persist_symbol_bars, symbol_path
from atlas.investment.intraday_bars import day_path, list_tape_days, load_day_bars
from atlas.trading.adapters import ZerodhaBarsAdapter
from atlas.trading.market_reader import MarketReaderService
from atlas.investment.zerodha_feed import ZerodhaMarketFeed
from tests.test_zerodha_feed import _FakeKite


def _feed(tmp_path: Path) -> ZerodhaMarketFeed:
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=_FakeKite(),
    )
    assert feed.complete_login("req123")["ok"]
    return feed


def _reader(tmp_path: Path, feed: ZerodhaMarketFeed, *, yahoo_enabled: bool = False) -> MarketReaderService:
    svc = MarketReaderService(
        data_dir=str(tmp_path),
        yahoo_enabled=yahoo_enabled,
        prefer_durable_bars=True,
    )
    svc._adapters["zerodha"] = ZerodhaBarsAdapter(data_dir=str(tmp_path), feed=feed)
    return svc


def _session_fresh_yahoo_bars(n: int = 20) -> list[dict]:
    from atlas.investment.bar_store import last_completed_nse_session_date

    sess = last_completed_nse_session_date()
    end = datetime.combine(sess, datetime.min.time(), tzinfo=timezone.utc)
    return [
        {
            "date": (end - timedelta(days=n - 1 - i)).date().isoformat(),
            "close": 50.0 + i,
            "volume": 100,
        }
        for i in range(n)
    ]


def test_zerodha_daily_persist_stamps_bar_store(tmp_path: Path):
    feed = _feed(tmp_path)
    reader = _reader(tmp_path, feed)
    out = reader.bars_for("RELIANCE.NS", provider="zerodha", limit=40, interval="1d")
    assert out["provider"] == "zerodha"
    assert out["source"] == "zerodha_historical"
    assert out["count"] >= 1

    doc = load_symbol_doc(tmp_path, "RELIANCE.NS")
    assert doc is not None
    assert doc["provider"] == "zerodha"
    assert doc["last_write_provider"] == "zerodha"
    assert doc["bar_count"] >= 1
    assert (tmp_path / "market" / "bars" / "RELIANCE.NS.json").is_file()


def test_zerodha_5m_persists_intraday_not_daily(tmp_path: Path):
    feed = _feed(tmp_path)
    reader = _reader(tmp_path, feed)
    out = reader.bars_for("RELIANCE.NS", provider="zerodha", limit=10, interval="5m")
    assert out["provider"] == "zerodha"
    assert out["interval"] == "5m"
    days = list_tape_days(tmp_path, "RELIANCE.NS")
    assert days, "5m Zerodha bars must land on an IST session file"
    stored = load_day_bars(tmp_path, "RELIANCE.NS", ist_date=days[-1])
    assert stored
    assert day_path(tmp_path, "RELIANCE.NS", ist_date=days[-1]).is_file()
    assert symbol_path(tmp_path, "RELIANCE.NS") is None or not symbol_path(
        tmp_path, "RELIANCE.NS"
    ).is_file()


def test_yahoo_session_prefers_zerodha_and_stamps_once(tmp_path: Path):
    persist_symbol_bars(
        tmp_path, "RELIANCE.NS", _session_fresh_yahoo_bars(), provider="yahoo"
    )
    prior = load_symbol_doc(tmp_path, "RELIANCE.NS")
    assert prior["provider"] == "yahoo"

    feed = _feed(tmp_path)
    reader = _reader(tmp_path, feed)
    adapter = reader._adapters["zerodha"]
    calls = {"n": 0}
    orig = adapter.fetch_bars

    def _count(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    adapter.fetch_bars = _count  # type: ignore[method-assign]

    first = reader.bars_for("RELIANCE.NS", provider="yahoo", limit=20)
    assert first["provider"] == "zerodha"
    assert first["note"] == "zerodha_session_prefer"
    assert first["requested_provider"] == "yahoo"
    assert calls["n"] == 1

    doc = load_symbol_doc(tmp_path, "RELIANCE.NS")
    assert doc["provider"] == "zerodha"
    assert doc["last_write_provider"] == "zerodha"
    assert doc["history_provider"] == "yahoo"

    second = reader.bars_for("RELIANCE.NS", provider="yahoo", limit=20)
    assert second["provider"] == "zerodha_durable"
    assert second["note"] == "session_fresh"
    assert calls["n"] == 1


def test_yahoo_durable_without_zerodha_session_stays_yahoo(tmp_path: Path):
    persist_symbol_bars(
        tmp_path, "INFY.NS", _session_fresh_yahoo_bars(), provider="yahoo"
    )
    hits = {"n": 0}

    def opener(_url):
        hits["n"] += 1
        return {"chart": {"result": []}}

    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=opener,
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
    )
    out = reader.bars_for("INFY.NS", provider="yahoo", limit=20)
    assert out["provider"] == "yahoo_durable"
    assert hits["n"] == 0
    doc = load_symbol_doc(tmp_path, "INFY.NS")
    assert doc["provider"] == "yahoo"
    assert doc.get("last_write_provider") == "yahoo"
