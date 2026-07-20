"""Hermetic tests for AdvisoryFeedReader (Phase D · §D.9)."""

from __future__ import annotations

import json
from typing import Any

from atlas.readers.advisory_feed import AdvisoryFeedReader


class _FakeAssets:
    def __init__(self, data: bytes, *, filename: str = "feed.json") -> None:
        self._data = data
        self._meta = {"filename": filename}

    def get_bytes(self, asset_id, version=None) -> bytes:
        return self._data

    def versions(self, asset_id):
        return [{"version": 1, "metadata": self._meta}]


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict = {}
        self.puts = 0

    def get(self, *key):
        return self.store.get(key)

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.puts += 1
        self.store[(asset_id, version, reader, reader_version)] = artifact


_ITEMS = [
    {"id": "CVE-1", "title": "RCE in openssl", "severity": "critical", "package": "openssl",
     "cve": "CVE-1", "url": "https://nvd/1"},
    {"advisory_id": "B-1", "name": "Breaking fastapi API", "severity_level": "medium",
     "type": "breaking_change", "component": "fastapi"},
    {"title": "missing id — skip"},
]


def test_reads_list_and_aliases():
    art = AdvisoryFeedReader(_FakeAssets(json.dumps(_ITEMS).encode()), _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok" and art["count"] == 2
    assert art["advisories"][0]["kind"] == "cve"
    assert art["advisories"][1]["package"] == "fastapi"


def test_wrapped_key_and_cache():
    artifacts = _FakeArtifacts()
    reader = AdvisoryFeedReader(
        _FakeAssets(json.dumps({"advisories": _ITEMS[:1]}).encode()), artifacts
    )
    reader.read("a1")
    reader.read("a1")
    assert artifacts.puts == 1


def test_malformed_and_unsupported():
    assert AdvisoryFeedReader(_FakeAssets(b"{x"), _FakeArtifacts()).read("a1")["outcome"] == "error"
    assert AdvisoryFeedReader(
        _FakeAssets(b"x", filename="f.csv"), _FakeArtifacts()
    ).read("a1")["outcome"] == "unsupported"
