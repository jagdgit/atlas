"""Hermetic tests for the MarketDataReader (Phase D · §D.6, P8/P11).

Fake Asset Store + fake artifact cache (duck-typed): a JSON bar list and a CSV feed both parse into
the same normalized bar shape; the derived-artifact cache is honored (a re-read is a cache hit);
malformed/unsupported feeds are reported (``outcome != "ok"``), never fatal.
"""

from __future__ import annotations

import json
from typing import Any

from atlas.readers.market_data import MarketDataReader


class _FakeAssets:
    def __init__(self, data: bytes, *, filename: str, symbol: str | None = None) -> None:
        self._data = data
        self._meta = {"filename": filename, "symbol": symbol}

    def get_bytes(self, asset_id: str, version: int | None = None) -> bytes:
        return self._data

    def versions(self, asset_id: str) -> list[dict[str, Any]]:
        return [{"version": 1, "metadata": self._meta}]


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict[tuple, dict[str, Any]] = {}
        self.puts = 0

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.puts += 1
        self.store[(asset_id, version, reader, reader_version)] = artifact


_BARS = [
    {"date": "2024-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
    {"date": "2024-01-02", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
]


def test_reads_json_bar_list():
    assets = _FakeAssets(json.dumps(_BARS).encode(), filename="acme.json", symbol="ACME")
    reader = MarketDataReader(assets, _FakeArtifacts())
    art = reader.read("a1")
    assert art["outcome"] == "ok"
    assert art["count"] == 2
    assert art["symbol"] == "ACME"
    assert art["bars"][0]["close"] == 10.5
    assert art["bars"][1]["high"] == 12.0


def test_reads_json_object_with_bars_key():
    payload = {"symbol": "X", "bars": _BARS}
    assets = _FakeAssets(json.dumps(payload).encode(), filename="x.json")
    art = MarketDataReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok" and art["count"] == 2


def test_reads_csv_feed():
    csv = "date,open,high,low,close,volume\n2024-01-01,10,11,9,10.5,100\n2024-01-02,10.5,12,10,11.5,120\n"
    assets = _FakeAssets(csv.encode(), filename="acme.csv")
    art = MarketDataReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok"
    assert [b["close"] for b in art["bars"]] == [10.5, 11.5]


def test_cache_hit_avoids_reparse():
    artifacts = _FakeArtifacts()
    assets = _FakeAssets(json.dumps(_BARS).encode(), filename="acme.json")
    reader = MarketDataReader(assets, artifacts)
    reader.read("a1")
    reader.read("a1")
    assert artifacts.puts == 1  # second read served from cache


def test_unsupported_extension_reported():
    assets = _FakeAssets(b"whatever", filename="acme.txt")
    art = MarketDataReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "unsupported"
    assert art["bars"] == []


def test_malformed_json_reported_not_fatal():
    assets = _FakeAssets(b"{not json", filename="acme.json")
    art = MarketDataReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "error"


def test_rows_missing_close_are_skipped():
    bars = [{"date": "d1", "open": 1}, {"date": "d2", "close": 5}]
    assets = _FakeAssets(json.dumps(bars).encode(), filename="x.json")
    art = MarketDataReader(assets, _FakeArtifacts()).read("a1")
    assert art["count"] == 1
    assert art["bars"][0]["close"] == 5.0
