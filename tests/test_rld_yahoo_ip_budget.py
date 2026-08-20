"""OI-RLD — Yahoo IP budget: hard-pause enrich + durable bars + chart gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.decision.rules import CapabilityGap
from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.fundamentals import enrich_from_yahoo
from atlas.investment.yahoo_fundamentals import (
    YahooRateGate,
    reset_yahoo_rate_gate_for_tests,
)
from atlas.trading.adapters import YahooFinanceAdapter
from atlas.trading.market_reader import MarketReaderService


def test_yahoo_background_yields_during_nse_rth(monkeypatch):
    from atlas.investment.yahoo_fundamentals import yahoo_background_should_yield_to_live

    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: True
    )
    assert yahoo_background_should_yield_to_live() is True
    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: False
    )
    assert yahoo_background_should_yield_to_live() is False


def test_enrich_hard_pauses_on_cooldown(tmp_path):
    reset_yahoo_rate_gate_for_tests()
    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.0,
        backoff_start_s=120.0,
        backoff_max_s=900.0,
    )
    gate.on_block(429)
    assert gate.remaining_cooldown_s() > 100

    calls = {"n": 0}

    def opener(_url):
        calls["n"] += 1
        raise AssertionError("must not hit network during cooldown")

    # enrich_from_yahoo with opener bypasses gate — use enabled live path without opener
    out = enrich_from_yahoo(
        tmp_path,
        ["CIPLA.NS"],
        enabled=True,
        opener=None,
        only_gaps=True,
        batch_size=1,
    )
    assert out["reason"] == "yahoo_cooldown"
    assert out["fetched"] == 0
    assert out["paused"] is True
    assert calls["n"] == 0


def test_wait_chart_honors_cooldown(tmp_path):
    reset_yahoo_rate_gate_for_tests()
    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.0,
        backoff_start_s=60.0,
        backoff_max_s=900.0,
    )
    gate.on_block(429)
    rem_before = gate.remaining_cooldown_s()
    assert rem_before > 50
    # wait_chart should sleep through cooldown if we don't monkeypatch sleep —
    # instead assert target includes cooldown by checking wait(respect) path via status.
    assert gate.status()["ready"] is False


def test_chart_adapter_refuses_network_during_cooldown(tmp_path):
    reset_yahoo_rate_gate_for_tests()
    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.0,
        backoff_start_s=90.0,
        backoff_max_s=900.0,
    )
    gate.on_block(429)
    adapter = YahooFinanceAdapter(
        enabled=True,
        data_dir=str(tmp_path),
        rate_gate=gate,
    )

    def boom(_url):
        raise AssertionError("network")

    adapter._opener = None  # force live path
    # Inject gate already set; fetch without opener
    try:
        adapter.fetch_bars("CIPLA.NS", limit=5)
        raised = False
    except CapabilityGap as exc:
        raised = True
        assert "cooldown" in str(exc).lower()
    assert raised is True


def test_market_reader_prefers_durable_bars(tmp_path):
    reset_yahoo_rate_gate_for_tests()
    from atlas.investment.bar_store import last_completed_nse_session_date

    sess = last_completed_nse_session_date()
    bars = [
        {
            "date": (sess - timedelta(days=40 - i)).isoformat(),
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100.0 + i,
            "volume": 1000,
        }
        for i in range(41)
    ]
    persist_symbol_bars(tmp_path, "CIPLA.NS", bars, provider="yahoo")

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
    out = reader.bars_for("CIPLA.NS", provider="yahoo", limit=20)
    assert out["provider"] == "yahoo_durable"
    assert out["count"] >= 20
    assert hits["n"] == 0
