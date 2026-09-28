"""OI-LAB-LOOP0 Step 4 — yesterday's 5m window must be reloadable."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.investment.intraday_bars import (
    load_day_bars,
    load_session_index,
    persist_session_tape,
    reconstruct_from_ref,
    tape_ref_for_decision,
)
from atlas.trading.market_reader import MarketReaderService
from tests.test_lab_loop0_zerodha_bar_store import _feed, _reader

_IST = ZoneInfo("Asia/Kolkata")


def _iso(ist: str, hm: str) -> str:
    dt = datetime.fromisoformat(f"{ist}T{hm}:00").replace(tzinfo=_IST)
    return dt.isoformat()


def test_persist_splits_sessions_and_yesterday_reloads(tmp_path: Path):
    bars = [
        {"t": _iso("2026-09-16", "09:15"), "date": _iso("2026-09-16", "09:15"), "close": 21.0},
        {"t": _iso("2026-09-16", "15:25"), "date": _iso("2026-09-16", "15:25"), "close": 21.5},
        {"t": _iso("2026-09-17", "09:15"), "date": _iso("2026-09-17", "09:15"), "close": 22.0},
    ]
    out = persist_session_tape(
        tmp_path, "YESBANK.NS", bars, provider="zerodha", interval="5m"
    )
    assert out["ok"] is True
    assert out["days"] == ["2026-09-16", "2026-09-17"]
    yday = load_day_bars(tmp_path, "YESBANK.NS", ist_date="2026-09-16")
    assert [b["close"] for b in yday] == [21.0, 21.5]
    today = load_day_bars(tmp_path, "YESBANK.NS", ist_date="2026-09-17")
    assert [b["close"] for b in today] == [22.0]
    assert not (tmp_path / "market" / "bars").exists()
    idx = load_session_index(tmp_path, "2026-09-16")
    assert idx is not None
    assert "YESBANK.NS" in (idx.get("symbols") or {})


def test_decision_ref_reconstructs_window_through_bar_t(tmp_path: Path):
    bars = [
        {"t": _iso("2026-09-16", "09:15"), "date": _iso("2026-09-16", "09:15"), "close": 10.0},
        {"t": _iso("2026-09-16", "09:20"), "date": _iso("2026-09-16", "09:20"), "close": 10.5},
        {"t": _iso("2026-09-16", "09:25"), "date": _iso("2026-09-16", "09:25"), "close": 11.0},
    ]
    persist_session_tape(tmp_path, "YESBANK.NS", bars, provider="zerodha")
    ref = tape_ref_for_decision(
        tmp_path,
        "YESBANK.NS",
        bars=bars,
        cursor=1,
        provider="zerodha",
    )
    assert ref["ist_date"] == "2026-09-16"
    assert ref["cursor"] == 1
    replay = reconstruct_from_ref(tmp_path, ref)
    assert replay["ok"] is True
    assert replay["last_close"] == 10.5
    assert replay["bar_count"] == 2
    missing = reconstruct_from_ref(tmp_path, {**ref, "ist_date": "2026-09-01"})
    assert missing["ok"] is False
    assert missing["reason"] == "tape_missing"


def test_zerodha_5m_fetch_lands_on_bar_session_not_today_dump(tmp_path: Path):
    feed = _feed(tmp_path)
    reader = _reader(tmp_path, feed)
    reader.bars_for("RELIANCE.NS", provider="zerodha", limit=10, interval="5m")
    yday = load_day_bars(tmp_path, "RELIANCE.NS", ist_date="2026-09-03")
    assert yday
    replay = reconstruct_from_ref(
        tmp_path,
        {
            "symbol": "RELIANCE.NS",
            "ist_date": "2026-09-03",
            "bar_t": yday[2].get("t") if len(yday) > 2 else yday[-1].get("t"),
        },
    )
    assert replay["ok"] is True
    assert replay["bar_count"] >= 1


def test_synthetic_yahoo_timestamps_still_use_today(tmp_path: Path):
    """L5 hermetic keys (t=1000) must not be treated as 1970-01-01 sessions."""
    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=lambda url: {
            "chart": {
                "result": [
                    {
                        "timestamp": [1000, 1300, 1600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [1, 1, 1],
                                    "high": [1, 1, 1],
                                    "low": [1, 1, 1],
                                    "close": [1.0, 1.1, 1.2],
                                    "volume": [1, 1, 1],
                                }
                            ]
                        },
                    }
                ]
            }
        },
        data_dir=str(tmp_path),
    )
    out = reader.bars_for(
        "RELIANCE.NS", provider="yahoo", interval="5m", range="1d", limit=10
    )
    assert out["source"] == "yahoo_intraday"
    today = load_day_bars(tmp_path, "RELIANCE.NS")
    assert len(today) >= 3
    assert not (
        tmp_path / "market" / "bars_intraday" / "RELIANCE.NS" / "1970-01-01.json"
    ).exists()
