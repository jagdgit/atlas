"""Resumable + checksummed download tests (Phase 0 · §2.8, P4).

Hermetic: the transport is an injected fake ``opener`` (no network), so we exercise the
Range-resume, server-ignores-range restart, 416-complete, checksum verify, atomic rename,
and retry-exhaustion paths deterministically.
"""

from __future__ import annotations

import hashlib

import pytest

from atlas.net.download import DownloadError, resumable_download

NO_SLEEP = lambda _s: None  # noqa: E731 - tiny test shim


class FakeResp:
    def __init__(self, status_code, headers, chunks, *, drop_at=None):
        self.status_code = status_code
        self.headers = headers
        self._chunks = chunks
        self._drop_at = drop_at

    def iter_bytes(self, chunk_size):  # noqa: ARG002 - chunk_size irrelevant for fake
        sent = 0
        for chunk in self._chunks:
            if self._drop_at is not None and sent >= self._drop_at:
                raise ConnectionError("stream dropped")
            yield chunk
            sent += len(chunk)


def _chunks(body: bytes, size: int = 16) -> list[bytes]:
    return [body[i : i + size] for i in range(0, len(body), size)] or [b""]


def make_opener(data: bytes, *, drop_first_at=None, ignore_range=False, unsatisfiable=False):
    state = {"calls": 0}

    def opener(url, start):  # noqa: ARG001 - url unused by the fake
        state["calls"] += 1
        drop = drop_first_at if state["calls"] == 1 else None
        if start > 0 and unsatisfiable:
            return FakeResp(416, {}, [])
        if start == 0 or ignore_range:
            headers = {"content-length": str(len(data))}
            return FakeResp(200, headers, _chunks(data), drop_at=drop)
        body = data[start:]
        headers = {
            "content-range": f"bytes {start}-{len(data) - 1}/{len(data)}",
            "content-length": str(len(body)),
        }
        return FakeResp(206, headers, _chunks(body), drop_at=drop)

    return opener, state


def test_full_download_verifies_checksum(tmp_path):
    data = b"atlas" * 100
    dest = tmp_path / "out.bin"
    opener, _ = make_opener(data)
    result = resumable_download(
        "http://x/f", dest, opener=opener, expected_sha256=hashlib.sha256(data).hexdigest()
    )
    assert dest.read_bytes() == data
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.size == len(data)
    assert result.resumed is False
    assert not (tmp_path / "out.bin.part").exists()  # committed via rename


def test_checksum_mismatch_raises_and_leaves_no_dest(tmp_path):
    data = b"hello world"
    dest = tmp_path / "out.bin"
    opener, _ = make_opener(data)
    with pytest.raises(DownloadError, match="checksum mismatch"):
        resumable_download("http://x/f", dest, opener=opener, expected_sha256="deadbeef")
    assert not dest.exists()


def test_resumes_after_dropped_stream(tmp_path):
    data = bytes(range(256))  # 256 unique bytes
    dest = tmp_path / "out.bin"
    opener, state = make_opener(data, drop_first_at=48)
    result = resumable_download("http://x/f", dest, opener=opener, sleep=NO_SLEEP)
    assert dest.read_bytes() == data
    assert result.resumed is True
    assert state["calls"] == 2  # first dropped, second resumed via Range


def test_server_ignores_range_restarts_cleanly(tmp_path):
    data = b"complete-body-xyz"
    dest = tmp_path / "out.bin"
    part = tmp_path / "out.bin.part"
    part.write_bytes(b"garbage-partial")  # stale partial from a prior boot
    opener, _ = make_opener(data, ignore_range=True)
    result = resumable_download("http://x/f", dest, opener=opener, sleep=NO_SLEEP)
    assert dest.read_bytes() == data  # restarted, not appended to garbage
    assert result.size == len(data)


def test_416_treats_existing_part_as_complete(tmp_path):
    data = b"already-have-all-of-this"
    dest = tmp_path / "out.bin"
    (tmp_path / "out.bin.part").write_bytes(data)  # full file already downloaded
    opener, state = make_opener(data, unsatisfiable=True)
    result = resumable_download(
        "http://x/f", dest, opener=opener, expected_sha256=hashlib.sha256(data).hexdigest()
    )
    assert dest.read_bytes() == data
    assert result.resumed is True


def test_retries_exhausted_raises(tmp_path):
    dest = tmp_path / "out.bin"

    def opener(url, start):  # noqa: ARG001
        raise ConnectionError("network down")

    with pytest.raises(DownloadError, match="failed after"):
        resumable_download("http://x/f", dest, opener=opener, max_attempts=2, sleep=NO_SLEEP)
    assert not dest.exists()
