"""O3 — a failed NFO instrument fetch never becomes a valid empty cache (futures and options)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from atlas.investment.zerodha_feed import (
    NFO_EMPTY_FAILED,
    NFO_FAILED,
    NFO_READY,
    NFO_READY_STALE,
    ZerodhaMarketFeed,
    _ist_today,
)
from tests.test_zerodha_feed import _FakeKite


class _CountingKite(_FakeKite):
    def __init__(self, *, fail_first: int = 0, empty: bool = False) -> None:
        super().__init__()
        self.nfo_calls = 0
        self.fail_first = fail_first
        self.empty = empty

    def instruments(self, exchange=None):
        if str(exchange or "").upper() == "NFO":
            self.nfo_calls += 1
            if self.nfo_calls <= self.fail_first:
                raise RuntimeError("Too many requests")
            if self.empty:
                return []
        return super().instruments(exchange)


@pytest.fixture(autouse=True)
def _no_env_token(monkeypatch):
    monkeypatch.delenv("ZERODHA_ACCESS_TOKEN", raising=False)


def _feed(tmp_path: Path, kite) -> ZerodhaMarketFeed:
    return ZerodhaMarketFeed(api_key="key", api_secret="secret", data_dir=tmp_path, client=kite)


def _futs(rows):
    return [r for r in rows if str(r.get("instrument_type")).upper() == "FUT"]


def test_pre_login_call_does_not_pin_empty_futures_for_the_day(tmp_path: Path):
    """The 2026-10-06 incident: a call before the morning login pinned [] until EOD."""
    kite = _CountingKite()
    feed = _feed(tmp_path, kite)
    assert feed.list_nfo_futures() == []
    state = feed.nfo_master_status()["futures"]
    assert state["state"] == NFO_FAILED and state["reason"] == "no_session"
    assert feed._nfo_futs is None

    assert feed.complete_login("req123")["ok"]
    rows = feed.list_nfo_futures()
    assert _futs(rows), "futures must load once the session exists"
    assert feed.nfo_master_status()["futures"]["state"] == NFO_READY
    assert feed.list_nfo_options(), "options load from the same fetch"


def test_fetch_error_is_retried_after_backoff_not_pinned(tmp_path: Path):
    kite = _CountingKite(fail_first=1)
    feed = _feed(tmp_path, kite)
    assert feed.complete_login("req123")["ok"]
    assert feed.list_nfo_futures() == []
    assert feed.nfo_master_status()["futures"]["state"] == NFO_FAILED
    assert feed.list_nfo_futures() == []
    assert kite.nfo_calls == 1, "backoff throttles the heavy instruments() call"

    feed._nfo_retry_backoff_s = 0.0
    assert _futs(feed.list_nfo_futures())
    assert kite.nfo_calls == 2
    assert feed.nfo_master_status()["futures"]["state"] == NFO_READY


def test_empty_response_with_yesterday_cache_is_stale_and_not_served(tmp_path: Path):
    cache = tmp_path / "investment" / "zerodha"
    cache.mkdir(parents=True)
    yesterday = (_ist_today() - timedelta(days=1)).isoformat()
    (cache / "nfo_fut.json").write_text(
        json.dumps(
            {
                "ist_day": yesterday,
                "count": 1,
                "rows": [{"tradingsymbol": "NIFTY26OCTFUT", "instrument_type": "FUT", "name": "NIFTY"}],
            }
        ),
        encoding="utf-8",
    )
    kite = _CountingKite(empty=True)
    feed = _feed(tmp_path, kite)
    assert feed.complete_login("req123")["ok"]
    assert feed.list_nfo_futures() == []
    state = feed.nfo_master_status()["futures"]
    assert state["state"] == NFO_READY_STALE
    assert state["stale_ist_day"] == yesterday and state["served"] is False
    persisted = json.loads((cache / "nfo_master_state.json").read_text(encoding="utf-8"))
    assert persisted["futures"]["state"] == NFO_READY_STALE


def test_empty_response_without_cache_is_empty_failed(tmp_path: Path):
    feed = _feed(tmp_path, _CountingKite(empty=True))
    assert feed.complete_login("req123")["ok"]
    assert feed.list_nfo_futures() == []
    assert feed.list_nfo_options() == []
    status = feed.nfo_master_status()
    assert status["futures"]["state"] == NFO_EMPTY_FAILED
    assert status["options"]["state"] == NFO_EMPTY_FAILED
    assert feed._nfo_futs is None and feed._nfo_opts is None


def test_login_from_another_instance_bypasses_failure_backoff(tmp_path: Path):
    """Worker feed failed (backoff armed); the operator logs in via the API's own feed instance."""
    kite = _CountingKite(fail_first=1)
    worker_feed = _feed(tmp_path, kite)
    assert worker_feed.complete_login("req123")["ok"]
    assert worker_feed.list_nfo_futures() == []
    assert worker_feed.list_nfo_futures() == []
    assert kite.nfo_calls == 1

    api_feed = _feed(tmp_path, _CountingKite())
    session = tmp_path / "investment" / "zerodha" / "session.json"
    assert api_feed.complete_login("req123")["ok"]
    doc = json.loads(session.read_text(encoding="utf-8"))
    doc["login_time"] = "2099-01-01T00:00:00+00:00"
    session.write_text(json.dumps(doc), encoding="utf-8")

    assert _futs(worker_feed.list_nfo_futures()), "a new login elsewhere retries immediately"
    assert kite.nfo_calls == 2


def _pack(rows, **kw):
    from datetime import datetime, timezone

    from atlas.investment.fno_data_pack import build_fno_data_pack

    now = datetime(2026, 10, 6, 5, 30, tzinfo=timezone.utc)
    return build_fno_data_pack(
        underlying="COALINDIA", spot=400.0, spot_as_of=now.isoformat(), instrument_rows=rows,
        expiry=None, session_open=True, now=now, **kw,
    )


_OPT_ONLY = [{"tradingsymbol": "COALINDIA26OCT400CE", "instrument_type": "CE", "name": "COALINDIA"}]


def test_pack_names_missing_futures_master_not_expiry():
    pack = _pack(_OPT_ONLY, futures_master_state="FAILED")
    assert pack["status"] == "NOT_READY"
    assert pack["reason"] == "futures_master_missing"
    assert pack["instrument_master"]["futures_rows"] == 0
    assert pack["instrument_master"]["options_rows"] == 1


def test_pack_names_stale_futures_master():
    pack = _pack(_OPT_ONLY, futures_master_state=NFO_READY_STALE)
    assert pack["reason"] == "futures_master_stale"


def test_pack_with_futures_present_keeps_existing_reasons():
    rows = _OPT_ONLY + [{"tradingsymbol": "COALINDIA26OCTFUT", "instrument_type": "FUT"}]
    pack = _pack(rows)
    assert "futures_master_missing" not in pack["reasons"]
    assert "expiry_missing" in pack["reasons"]


def test_refresh_nfo_masters_reports_both_dependencies(tmp_path: Path):
    feed = _feed(tmp_path, _CountingKite())
    assert feed.complete_login("req123")["ok"]
    status = feed.refresh_nfo_masters()
    assert status["futures"]["state"] == NFO_READY
    assert status["options"]["state"] == NFO_READY
    assert status["futures"]["count"] >= 1
