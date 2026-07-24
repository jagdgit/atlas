"""MarketReader adapters + Market Observer (MI.3 / OI-D1)."""

from __future__ import annotations

import pytest

from atlas.decision.rules import CapabilityGap
from atlas.trading.adapters import (
    AssetReplayAdapter,
    KeyedProviderAdapter,
    YahooFinanceAdapter,
    pct_move,
)
from atlas.trading.market_reader import MarketReaderService
from atlas.workers.base import TickContext
from atlas.workers.market_observer import MarketObserverWorker


def test_pct_move():
    bars = [{"close": 100.0}, {"close": 110.0}]
    assert pct_move(bars) == pytest.approx(10.0)


def test_asset_replay_adapter():
    class _Assets:
        def get_by_name(self, kind, name):
            assert kind == "market_data"
            if name == "demo-feed":
                return {"id": "a1", "name": name, "kind": kind}
            return None

    class _Reader:
        def read(self, asset_id):
            assert asset_id == "a1"
            return {
                "outcome": "ok",
                "bars": [
                    {"t": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
                    {"t": 2, "open": 10, "high": 12, "low": 10, "close": 12, "volume": 2},
                ],
            }

    adapter = AssetReplayAdapter(assets=_Assets(), market_data=_Reader())
    bars = adapter.fetch_bars("DEMO", asset="demo-feed")
    assert len(bars) == 2
    assert bars[-1]["close"] == 12

    with pytest.raises(CapabilityGap) as exc:
        adapter.fetch_bars("MISSING", asset="missing")
    assert "market_data:asset:missing" in exc.value.capability


def test_yahoo_disabled_raises_gap():
    adapter = YahooFinanceAdapter(enabled=False)
    with pytest.raises(CapabilityGap) as exc:
        adapter.fetch_bars("RELIANCE.NS")
    assert "yahoo" in exc.value.capability


def test_yahoo_opener_parses_chart():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1, 2],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, 11.0],
                                "high": [11.0, 12.0],
                                "low": [9.0, 10.0],
                                "close": [10.5, 11.5],
                                "volume": [100, 200],
                            }
                        ]
                    },
                }
            ]
        }
    }
    adapter = YahooFinanceAdapter(enabled=True, opener=lambda url: payload)
    bars = adapter.fetch_bars("TEST")
    assert len(bars) == 2
    assert bars[1]["close"] == 11.5


def test_keyed_provider_missing_key():
    adapter = KeyedProviderAdapter("polygon", api_key_env="ATLAS_TEST_NO_KEY_XYZ")
    with pytest.raises(CapabilityGap) as exc:
        adapter.fetch_bars("AAPL")
    assert "ATLAS_TEST_NO_KEY_XYZ" in exc.value.detail


def test_market_reader_service_asset_replay():
    class _Assets:
        def get_by_name(self, kind, name):
            return {"id": "a1", "name": name}

    class _Reader:
        def read(self, asset_id):
            return {
                "outcome": "ok",
                "bars": [{"close": 100.0}, {"close": 105.0}],
            }

    svc = MarketReaderService(
        assets=_Assets(),
        market_data=_Reader(),
        default_provider="asset_replay",
        yahoo_enabled=False,
    )
    out = svc.bars_for("DEMO", asset="demo-feed")
    assert out["provider"] == "asset_replay"
    assert out["count"] == 2
    assert out["pct_move"] == pytest.approx(5.0)
    names = {p["name"] for p in svc.list_providers()}
    assert "yahoo" in names and "polygon" in names


def test_market_observer_idle_without_symbols():
    worker = MarketObserverWorker(market_reader=MarketReaderService())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={},
            config_version=1,
            state={},
        )
    )
    assert "idle" in result.note


def test_market_observer_flags_interesting_move():
    class _Reader:
        def bars_for(self, symbol, **kwargs):
            return {
                "provider": "asset_replay",
                "symbol": symbol,
                "bars": [{"close": 100}, {"close": 120}],
                "count": 2,
                "pct_move": 20.0,
            }

    worker = MarketObserverWorker(market_reader=_Reader())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "instruments": [{"symbol": "DEMO", "asset": "demo-feed"}],
                "move_alert_pct": 5.0,
            },
            config_version=1,
            state={},
        )
    )
    assert "interesting" in result.note
    assert result.state["last_interesting"][0]["symbol"] == "DEMO"
    assert result.state["last_ok"] == 1
