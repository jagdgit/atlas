"""OI-MDPH0 — Market Data Provider Health state machine + live_required gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import atlas.investment.market_data_provider_health as mdph
from atlas.investment.lab_contracts import live_required
from atlas.investment.zerodha_feed import ZerodhaMarketFeed
from tests.test_zerodha_feed import _FakeKite


def _feed(tmp_path: Path, *, with_session: bool = True) -> ZerodhaMarketFeed:
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=kite,
    )
    if with_session:
        assert feed.complete_login("req123")["ok"]
    return feed


def setup_function() -> None:
    mdph.reset_probe_state_for_tests()


def test_live_required_intraday_and_fno():
    assert live_required("equity_intraday_learner") is True
    assert live_required("india_fno_learner") is True
    assert live_required("india_equity_learner") is False
    assert live_required("x", cfg={"live_required": True}) is True
    assert live_required("equity_intraday_learner", cfg={"live_required": False}) is False


def test_freshness_fresh_and_stale():
    now = datetime.now(timezone.utc)
    fresh, age = mdph.freshness_of(as_of=now.isoformat(), max_age_ms=60_000)
    assert fresh == mdph.FRESH
    assert age is not None and age < 60_000

    old = (now - timedelta(minutes=10)).isoformat()
    stale, age2 = mdph.freshness_of(as_of=old, max_age_ms=60_000)
    assert stale == mdph.STALE
    assert age2 is not None and age2 > 60_000

    unk, _ = mdph.freshness_of(as_of=None, received_at=None)
    assert unk == mdph.UNKNOWN


def test_login_required_without_session(tmp_path: Path):
    feed = _feed(tmp_path, with_session=False)
    doc = mdph.evaluate_zerodha_health(tmp_path, feed=feed, probe=True)
    assert doc["status"] == mdph.STATUS_LOGIN_REQUIRED
    assert doc["live_trading_allowed"] is False
    assert doc["cta"] == "/zerodha/login"
    assert doc["reason_code"] == mdph.REASON_PROVIDER_LOGIN_REQUIRED
    nev = mdph.not_evaluable_payload(doc)
    assert nev["decision_status"] == mdph.DECISION_NOT_EVALUABLE
    assert nev["class"] == "operational"


def test_ready_after_login_and_probe(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    doc = mdph.evaluate_zerodha_health(
        tmp_path,
        feed=feed,
        probe=True,
        refresh_instruments=True,
        force_reprobe=True,
    )
    assert doc["status"] == mdph.STATUS_READY
    assert doc["ltp_probe"] == "PASS"
    assert doc["live_trading_allowed"] is True
    assert doc["instrument_master"] == mdph.INSTRUMENT_VALID
    assert doc["last_ltp_price"] == 100.5


def test_status_read_does_not_degrade_ready(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    ready = mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, refresh_instruments=True, force_reprobe=True
    )
    assert ready["status"] == mdph.STATUS_READY

    # Cheap status poll must not flip READY → DEGRADED
    again = mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=False, refresh_instruments=False
    )
    assert again["status"] == mdph.STATUS_READY
    assert again["live_trading_allowed"] is True


def test_token_exception_clears_session_to_login_required(tmp_path: Path, monkeypatch):
    """Bad/expired access_token must not stay token_valid=True forever."""
    feed = _feed(tmp_path, with_session=True)
    mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, refresh_instruments=True, force_reprobe=True
    )
    assert feed.has_session is True

    def _auth_dead(symbol="RELIANCE.NS"):
        return {
            "ok": False,
            "error": "TokenException: Incorrect `api_key` or `access_token`.",
            "received_at": mdph._now_iso(),
            "symbol": symbol,
        }

    monkeypatch.setattr(mdph, "probe_ltp", _auth_dead)
    mdph.reset_probe_state_for_tests()
    mdph._last_reprobe_mono = 0.0  # noqa: SLF001
    doc = mdph.evaluate_zerodha_health(tmp_path, feed=feed, probe=True, force_reprobe=True)
    assert doc["status"] == mdph.STATUS_LOGIN_REQUIRED
    assert doc["token_valid"] is False
    assert doc["live_trading_allowed"] is False
    assert doc["cta"] == "/zerodha/login"
    assert feed.has_session is False


def test_degraded_on_ltp_fail_then_recover(tmp_path: Path, monkeypatch):
    feed = _feed(tmp_path, with_session=True)
    mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, refresh_instruments=True, force_reprobe=True
    )

    def _boom(symbol="RELIANCE.NS"):
        return {"ok": False, "error": "network_blip", "received_at": mdph._now_iso(), "symbol": symbol}

    monkeypatch.setattr(mdph, "probe_ltp", _boom)
    mdph.reset_probe_state_for_tests()
    # Force past reprobe interval
    mdph._last_reprobe_mono = 0.0  # noqa: SLF001

    bad = mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, force_reprobe=True
    )
    assert bad["status"] == mdph.STATUS_DEGRADED
    assert bad["live_trading_allowed"] is False
    assert bad["reason_code"] == mdph.REASON_PROVIDER_DEGRADED

    # Recovery: restore real probe
    monkeypatch.undo()
    mdph.reset_probe_state_for_tests()
    # Need majority PASS when recovering from DEGRADED — run 3 probes
    for _ in range(3):
        mdph._last_reprobe_mono = 0.0  # noqa: SLF001
        doc = mdph.evaluate_zerodha_health(
            tmp_path, feed=feed, probe=True, force_reprobe=True
        )
    assert doc["status"] == mdph.STATUS_READY
    assert doc["live_trading_allowed"] is True


def test_observation_provenance_shape():
    prov = mdph.observation_provenance(
        provider_status=mdph.STATUS_READY,
        symbol="RELIANCE.NS",
        price=100.5,
        as_of=datetime.now(timezone.utc).isoformat(),
        instrument_token=738561,
        instrument_dump_date="2026-09-03",
    )
    assert prov["source_provider"] == "zerodha"
    assert prov["freshness"] == mdph.FRESH
    assert prov["instrument_token"] == 738561
    assert "received_at" in prov


def test_mark_for_symbol_includes_provenance(tmp_path: Path):
    from atlas.investment.market_data_service import MarketDataService

    feed = _feed(tmp_path, with_session=True)
    mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, refresh_instruments=True, force_reprobe=True
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
    prov = out.get("observation_provenance") or {}
    assert prov.get("source_provider") == "zerodha"
    assert prov.get("freshness") in {mdph.FRESH, mdph.STALE, mdph.UNKNOWN}


def test_paper_gate_pauses_live_required(tmp_path: Path):
    """Live-required path emits operational NOT_EVALUABLE when LOGIN_REQUIRED."""
    from atlas.workers.base import TickResult

    feed = _feed(tmp_path, with_session=False)
    health = mdph.evaluate_zerodha_health(tmp_path, feed=feed, probe=True)
    assert live_required("equity_intraday_learner") is True
    assert not mdph.live_trading_allowed(health)
    nev = mdph.not_evaluable_payload(health)
    note = (
        f"NOT_EVALUABLE:{nev.get('reason_code')} "
        f"live_required lab paused (Zerodha {health.get('status')}). "
        f"Authenticate: {health.get('cta')}"
    )
    assert nev["reason_code"] == mdph.REASON_PROVIDER_LOGIN_REQUIRED
    assert "PROVIDER_LOGIN_REQUIRED" in note
    tr = TickResult(state={"mdph": nev}, note=note)
    assert "NOT_EVALUABLE" in tr.note


def test_zerodha_status_endpoint_returns_mdph(monkeypatch, tmp_path: Path):
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

    st = client.get("/zerodha/status")
    assert st.status_code == 200
    body = st.json()
    assert body["status"] == mdph.STATUS_LOGIN_REQUIRED
    assert body["live_trading_allowed"] is False

    cb = client.get("/zerodha/callback?request_token=req123&action=login")
    assert cb.status_code == 200
    assert b"READY" in cb.content or b"session active" in cb.content.lower()

    st2 = client.get("/zerodha/status")
    assert st2.json().get("status") in {mdph.STATUS_READY, mdph.STATUS_DEGRADED}


def test_historical_bars_and_zerodha_adapter(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    out = feed.get_historical_bars("RELIANCE.NS", interval="5m", limit=10)
    assert out["ok"] is True
    assert len(out["bars"]) == 10
    assert out["bars"][-1]["source"] == "zerodha"

    from atlas.trading.adapters import ZerodhaBarsAdapter

    bars = ZerodhaBarsAdapter(feed=feed).fetch_bars("RELIANCE.NS", limit=5, interval="5m")
    assert len(bars) == 5


def test_silent_yahoo_blocked_recorded(tmp_path: Path):
    mdph.record_mdph_event(
        tmp_path,
        "silent_yahoo_blocked",
        portfolio_key="equity_intraday_learner",
        symbol="CYIENT.NS",
    )
    assert mdph.observation_silent_sub_count(tmp_path) == 1
    assert (tmp_path / "investment" / "market_data_provider" / "observation.jsonl").is_file()


def test_reconcile_operating_state(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    report = mdph.reconcile_operating_state(tmp_path, feed=feed)
    assert report["provider_status"] == mdph.STATUS_READY
    assert report["live_trading_allowed"] is True
    assert (tmp_path / "investment" / "market_data_provider" / "last_reconcile.json").is_file()


def test_live_required_defaults_to_zerodha_provider():
    from atlas.investment.portfolios import default_decision_config, enrich_decision_config_from_book

    book = {
        "portfolio_key": "equity_intraday_learner",
        "asset_class": "cash_equity",
        "persona": {"capital": 50_000},
    }
    cfg = default_decision_config(book)
    assert cfg["live_provider"] == "zerodha"

    enriched = enrich_decision_config_from_book(
        {"portfolio_key": "equity_intraday_learner", "live_provider": "yahoo"},
        book,
    )
    assert enriched["live_provider"] == "zerodha"


def test_phase2_observation_report(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    health = mdph.evaluate_zerodha_health(
        tmp_path, feed=feed, probe=True, refresh_instruments=True, force_reprobe=True
    )
    report = mdph.build_phase2_observation_report(tmp_path, health=health)
    assert report["kind"] == "MDPH_PHASE2_REPORT"
    assert report["phase2"]["sessions_observed"] >= 1
    assert report["phase2"]["invariant_ok"] is True
    assert report["invariants"]["silent_yahoo_ok"] is True
    assert (tmp_path / "investment" / "market_data_provider" / "phase2_verify.json").is_file()

    board = mdph.investment_l5_scoreboard(tmp_path)
    assert board["ok"] is True
    assert board["target"] == 5
    assert board["have"] == 0  # honest empty


def test_hist_probe_on_force_reprobe(tmp_path: Path):
    feed = _feed(tmp_path, with_session=True)
    doc = mdph.evaluate_zerodha_health(
        tmp_path,
        feed=feed,
        probe=True,
        refresh_instruments=True,
        force_reprobe=True,
    )
    assert doc["status"] == mdph.STATUS_READY
    assert doc.get("hist_probe") == "PASS"
    assert int(doc.get("hist_bar_count") or 0) >= 1
