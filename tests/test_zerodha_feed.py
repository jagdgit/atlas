"""OI-ZERODHA0 — Zerodha Kite Connect market feed (quotes only)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atlas.investment.market_data_service import MarketDataService
from atlas.investment.zerodha_feed import ZerodhaMarketFeed


class _FakeKite:
    def __init__(self) -> None:
        self.access_token = None
        self._session_calls = 0

    def login_url(self) -> str:
        return "https://kite.zerodha.com/connect/login?api_key=test&v=3"

    def set_access_token(self, token: str) -> None:
        self.access_token = token

    def generate_session(self, request_token: str, api_secret: str) -> dict:
        self._session_calls += 1
        assert request_token == "req123"
        assert api_secret == "secret"
        return {"access_token": "acc-day", "user_id": "AB1234"}

    def ltp(self, instruments):
        out = {}
        for inst in instruments:
            out[inst] = {"last_price": 100.5, "instrument_token": 1}
        return out

    def quote(self, instruments):
        out = {}
        for inst in instruments:
            out[inst] = {
                "last_price": 101.0,
                "volume": 10,
                "ohlc": {"open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0},
            }
        return out

    def instruments(self, exchange=None):
        ex = str(exchange or "NSE").upper()
        if ex == "NFO":
            from datetime import date, timedelta

            as_of = date.today()
            def _fut(tsym, name, days, token, lot=25):
                return {
                    "tradingsymbol": tsym,
                    "name": name,
                    "instrument_type": "FUT",
                    "instrument_token": token,
                    "expiry": as_of + timedelta(days=days),
                    "lot_size": lot,
                    "exchange": "NFO",
                    "segment": "NFO-FUT",
                }

            return [
                _fut("NIFTY16SEP26FUT", "NIFTY", -1, 11001),  # expired relative if days=-1
                {
                    "tradingsymbol": "NIFTY23SEP26FUT",
                    "name": "NIFTY",
                    "instrument_type": "FUT",
                    "instrument_token": 22002,
                    "expiry": as_of + timedelta(days=6),
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-FUT",
                },
                {
                    "tradingsymbol": "NIFTY30SEP26FUT",
                    "name": "NIFTY",
                    "instrument_type": "FUT",
                    "instrument_token": 33003,
                    "expiry": as_of + timedelta(days=13),
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-FUT",
                },
                {
                    "tradingsymbol": "BANKNIFTY30SEP26FUT",
                    "name": "NIFTY BANK",
                    "instrument_type": "FUT",
                    "instrument_token": 44004,
                    "expiry": as_of + timedelta(days=13),
                    "lot_size": 15,
                    "exchange": "NFO",
                    "segment": "NFO-FUT",
                },
                {
                    "tradingsymbol": "NIFTY30SEP2625000CE",
                    "name": "NIFTY",
                    "instrument_type": "CE",
                    "instrument_token": 55005,
                    "expiry": as_of + timedelta(days=13),
                    "strike": 25000,
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-OPT",
                },
                {
                    "tradingsymbol": "NIFTY23SEP2625000CE",
                    "name": "NIFTY",
                    "instrument_type": "CE",
                    "instrument_token": 55015,
                    "expiry": as_of + timedelta(days=6),
                    "strike": 25000,
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-OPT",
                },
                {
                    "tradingsymbol": "NIFTY23SEP2625000PE",
                    "name": "NIFTY",
                    "instrument_type": "PE",
                    "instrument_token": 55016,
                    "expiry": as_of + timedelta(days=6),
                    "strike": 25000,
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-OPT",
                },
                {
                    "tradingsymbol": "NIFTY23SEP2624950CE",
                    "name": "NIFTY",
                    "instrument_type": "CE",
                    "instrument_token": 55017,
                    "expiry": as_of + timedelta(days=6),
                    "strike": 24950,
                    "lot_size": 25,
                    "exchange": "NFO",
                    "segment": "NFO-OPT",
                },
                {
                    "tradingsymbol": "BANKNIFTY30SEP2655000CE",
                    "name": "NIFTY BANK",
                    "instrument_type": "CE",
                    "instrument_token": 66006,
                    "expiry": as_of + timedelta(days=6),
                    "strike": 55000,
                    "lot_size": 15,
                    "exchange": "NFO",
                    "segment": "NFO-OPT",
                },
            ]
        # Enough rows for MDPH instrument-master validity (>100)
        rows = []
        for i, sym in enumerate(
            ["RELIANCE", "INFY", "TCS", "SBIN", "HDFCBANK"] + [f"SYM{i}" for i in range(1200)]
        ):
            rows.append(
                {
                    "tradingsymbol": sym,
                    "instrument_token": 1000 + i,
                    "instrument_type": "EQ",
                    "segment": "NSE",
                    "exchange": exchange or "NSE",
                }
            )
        return rows

    def historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
        from datetime import datetime, timedelta, timezone

        if interval in {"day", "daily"}:
            end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            out = []
            for i in range(60):
                ts = end - timedelta(days=59 - i)
                px = 100.0 + i
                out.append(
                    {
                        "date": ts,
                        "open": px,
                        "high": px + 1,
                        "low": px - 1,
                        "close": px + 0.5,
                        "volume": 1000 + i,
                    }
                )
            return out

        base = datetime(2026, 9, 3, 9, 15)
        out = []
        for i in range(30):
            ts = base + timedelta(minutes=5 * i)
            px = 100.0 + i
            out.append(
                {
                    "date": ts,
                    "open": px,
                    "high": px + 1,
                    "low": px - 1,
                    "close": px + 0.5,
                    "volume": 1000 + i,
                }
            )
        return out


def test_format_instrument():
    assert ZerodhaMarketFeed.format_instrument("RELIANCE.NS") == "NSE:RELIANCE"
    assert ZerodhaMarketFeed.format_instrument("TCS.BO") == "BSE:TCS"
    assert ZerodhaMarketFeed.format_symbol("INFY.NS") == "INFY"


def test_login_and_ltp(tmp_path: Path):
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=kite,
    )
    assert feed.is_configured
    assert not feed.has_session

    url = feed.login_url()
    assert url["ok"] is True
    assert "kite.zerodha.com" in url["login_url"]

    done = feed.complete_login("req123")
    assert done["ok"] is True
    assert done["user_id"] == "AB1234"
    assert feed.has_session
    sess_path = tmp_path / "investment" / "zerodha" / "session.json"
    assert sess_path.is_file()

    ltp = feed.get_ltp(["RELIANCE.NS", "INFY.NS"])
    assert ltp["ok"] is True
    assert ltp["prices"]["RELIANCE.NS"]["last"] == 100.5
    assert ltp["prices"]["RELIANCE.NS"]["source"] == "zerodha"

    q = feed.get_quote("RELIANCE.NS")
    assert q["ok"] is True
    assert q["mark"]["last"] == 101.0
    assert q["mark"]["high"] == 102.0


def test_session_required_without_token():
    feed = ZerodhaMarketFeed(api_key="k", api_secret="s", client=_FakeKite())
    # Fake client is set but no access token / session day → has_session False
    # Reset client path: construct without client so require_session gates
    feed2 = ZerodhaMarketFeed(api_key="k", api_secret="s")
    out = feed2.get_ltp("RELIANCE.NS")
    assert out["ok"] is False
    assert out["error"] in {"zerodha_session_required", "kiteconnect_unavailable"}


def test_market_data_service_prefers_zerodha(tmp_path: Path):
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        access_token="acc",
        data_dir=tmp_path,
        client=kite,
    )
    mds = MarketDataService(
        data_dir=tmp_path,
        zerodha_feed=feed,
        prefer_zerodha=True,
        audit=False,
    )
    out = mds.mark_for_symbol("RELIANCE.NS", allow_network=True)
    assert out["ok"] is True
    assert out["source"] == "zerodha"
    assert out["mark"]["last"] == 100.5

    st = mds.status()
    assert st["prefer_zerodha"] is True
    assert st["zerodha"]["configured"] is True


def test_root_forwards_zerodha_request_token(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    from atlas.api.app import create_app
    from tests.test_api import API_KEY, FakeApplication

    monkeypatch.setenv("ZERODHA_API_KEY", "key")
    monkeypatch.setenv("ZERODHA_API_SECRET", "secret")

    app_obj = FakeApplication((API_KEY,))
    app_obj.config.api.ui_enabled = True
    # Point data path at tmp so session writes stay hermetic
    app_obj.config.paths.data = str(tmp_path)

    client = TestClient(create_app(app_obj))
    # Without token → UI
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/ui" in (r.headers.get("location") or "")

    # With token → callback
    r2 = client.get(
        "/?request_token=req123&action=login",
        follow_redirects=False,
    )
    assert r2.status_code in (302, 307)
    loc = r2.headers.get("location") or ""
    assert "/zerodha/callback" in loc
    assert "request_token=req123" in loc


def test_zerodha_callback_exchanges_token(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    from atlas.api.app import create_app
    from tests.test_api import API_KEY, FakeApplication

    monkeypatch.setenv("ZERODHA_API_KEY", "key")
    monkeypatch.setenv("ZERODHA_API_SECRET", "secret")

    fake = _FakeKite()

    def _fake_from_env(*, data_dir=None):
        return ZerodhaMarketFeed(
            api_key="key",
            api_secret="secret",
            data_dir=data_dir or tmp_path,
            client=fake,
        )

    monkeypatch.setattr(
        "atlas.investment.zerodha_feed.ZerodhaMarketFeed.from_env",
        _fake_from_env,
    )

    app_obj = FakeApplication((API_KEY,))
    app_obj.config.api.ui_enabled = True
    app_obj.config.paths.data = str(tmp_path)
    client = TestClient(create_app(app_obj))

    resp = client.get("/zerodha/callback?request_token=req123&action=login")
    assert resp.status_code == 200
    assert b"session active" in resp.content.lower()
    assert (tmp_path / "investment" / "zerodha" / "session.json").is_file()


def test_clear_session(tmp_path: Path):
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=kite,
    )
    assert feed.complete_login("req123")["ok"]
    assert feed.has_session
    cleared = feed.clear_session()
    assert cleared["ok"] is True
    assert cleared["cleared"] is True
    assert not feed.has_session
    assert not (tmp_path / "investment" / "zerodha" / "session.json").exists()


def test_force_login_route_clears_and_redirects(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    from atlas.api.app import create_app
    from tests.test_api import API_KEY, FakeApplication

    monkeypatch.setenv("ZERODHA_API_KEY", "key")
    monkeypatch.setenv("ZERODHA_API_SECRET", "secret")
    fake = _FakeKite()

    def _fake_from_env(*, data_dir=None):
        return ZerodhaMarketFeed(
            api_key="key",
            api_secret="secret",
            data_dir=data_dir or tmp_path,
            client=fake,
        )

    monkeypatch.setattr(
        "atlas.investment.zerodha_feed.ZerodhaMarketFeed.from_env",
        _fake_from_env,
    )
    app_obj = FakeApplication((API_KEY,))
    app_obj.config.api.ui_enabled = True
    app_obj.config.paths.data = str(tmp_path)
    client = TestClient(create_app(app_obj))
    # establish session
    assert client.get("/zerodha/callback?request_token=req123&action=login").status_code == 200
    assert (tmp_path / "investment" / "zerodha" / "session.json").is_file()
    resp = client.get("/zerodha/force-login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "kite.zerodha.com" in (resp.headers.get("location") or "")
    assert not (tmp_path / "investment" / "zerodha" / "session.json").exists()
