"""Hermetic tests for the JobPostingsReader (Phase D · §D.8, P8/P11)."""

from __future__ import annotations

import json
from typing import Any

from atlas.readers.job_postings import JobPostingsReader


class _FakeAssets:
    def __init__(self, data: bytes, *, filename: str = "jobs.json") -> None:
        self._data = data
        self._meta = {"filename": filename}

    def get_bytes(self, asset_id: str, version: int | None = None) -> bytes:
        return self._data

    def versions(self, asset_id: str) -> list[dict[str, Any]]:
        return [{"version": 1, "metadata": self._meta}]


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict = {}
        self.puts = 0

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.puts += 1
        self.store[(asset_id, version, reader, reader_version)] = artifact


_JOBS = [
    {"id": "1", "title": "Python Dev", "company": "Acme", "location": "Berlin",
     "skills": ["python", "fastapi"], "salary": 100000, "url": "https://x/1"},
    {"job_id": "2", "role": "Java Dev", "employer": "Beta", "city": "Remote",
     "requirements": "java, spring", "compensation": 90000},
    {"title": "No ID — skipped"},
]


def test_reads_json_list():
    art = JobPostingsReader(
        _FakeAssets(json.dumps(_JOBS).encode()), _FakeArtifacts()
    ).read("a1")
    assert art["outcome"] == "ok"
    assert art["count"] == 2
    assert art["postings"][0]["id"] == "1"
    assert art["postings"][0]["skills"] == ["python", "fastapi"]
    assert art["postings"][1]["id"] == "2"
    assert "java" in art["postings"][1]["skills"]


def test_reads_wrapped_postings_key():
    payload = {"postings": _JOBS[:1]}
    art = JobPostingsReader(
        _FakeAssets(json.dumps(payload).encode()), _FakeArtifacts()
    ).read("a1")
    assert art["count"] == 1


def test_cache_hit():
    artifacts = _FakeArtifacts()
    reader = JobPostingsReader(_FakeAssets(json.dumps(_JOBS).encode()), artifacts)
    reader.read("a1")
    reader.read("a1")
    assert artifacts.puts == 1


def test_malformed_reported():
    art = JobPostingsReader(_FakeAssets(b"{not json"), _FakeArtifacts()).read("a1")
    assert art["outcome"] == "error"


def test_unsupported_extension():
    art = JobPostingsReader(
        _FakeAssets(b"x", filename="jobs.csv"), _FakeArtifacts()
    ).read("a1")
    assert art["outcome"] == "unsupported"
