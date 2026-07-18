"""Resumable, checksummed downloads (Phase 0 · §2.8, P4).

Design-for-failure for large fetches (asset ingestion in Phase B): a download that is
interrupted by a power/internet outage **resumes** from the partial ``.part`` file via an
HTTP ``Range`` request instead of starting over, and the finished file is verified against
an expected SHA-256 before being atomically moved into place. Nothing is ever left in a
half-written state at ``dest`` — the rename is the commit point.

The transport is injectable (``opener(url, start_byte) -> response``) so this is tested
without real network I/O. The default opener uses ``httpx`` with a ``Range`` header.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

# opener(url, start_byte) -> response with .status_code, .headers, and either
# .iter_bytes(chunk) or .content
Opener = Callable[[str, int], Any]


class DownloadError(Exception):
    """A download failed permanently (retries exhausted or checksum mismatch)."""


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size: int
    sha256: str
    resumed: bool
    attempts: int


def resumable_download(
    url: str,
    dest: Path | str,
    *,
    opener: Opener | None = None,
    expected_sha256: str | None = None,
    chunk_size: int = 65536,
    max_attempts: int = 5,
    backoff_base: float = 1.0,
    backoff_cap: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    logger: logging.Logger | None = None,
) -> DownloadResult:
    """Download ``url`` to ``dest``, resuming a partial ``dest.part`` if present.

    Raises :class:`DownloadError` when the retry budget is exhausted or the finished
    file's checksum does not match ``expected_sha256``.
    """
    log = logger or logging.getLogger("atlas.net.download")
    fetch = opener or _default_opener()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    errors = 0
    resumed = False
    attempts = 0

    def _retry(reason: str) -> None:
        nonlocal errors
        errors += 1
        if errors > max_attempts:
            raise DownloadError(f"download failed after {max_attempts} attempts: {url} ({reason})")
        log.warning("download %s: %s — retry %d/%d", url, reason, errors, max_attempts)
        sleep(min(backoff_base * (2 ** (errors - 1)), backoff_cap))

    while True:
        attempts += 1
        have = part.stat().st_size if part.exists() else 0
        if have > 0:
            resumed = True

        try:
            resp = fetch(url, have)
        except Exception as exc:  # noqa: BLE001 - transport errors are retryable
            _retry(f"transport error: {type(exc).__name__}: {exc}")
            continue

        status = int(getattr(resp, "status_code", 0))
        if status == 416 and have > 0:
            break  # range beyond EOF => already have the whole file; verify below
        if status == 200:
            mode, have = "wb", 0  # server ignored Range: restart cleanly
        elif status == 206:
            mode = "ab"
        else:
            _retry(f"HTTP {status}")
            continue

        total = _parse_total(resp, have)
        try:
            with open(part, mode) as fh:
                for block in _iter(resp, chunk_size):
                    fh.write(block)
        except Exception as exc:  # noqa: BLE001 - stream can drop mid-transfer
            _retry(f"stream interrupted: {type(exc).__name__}: {exc}")
            continue

        size = part.stat().st_size
        if total is None or size >= total:
            break
        if size <= have:  # no forward progress — don't spin forever
            _retry(f"no progress ({size} bytes)")

    digest = _sha256_file(part)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise DownloadError(
            f"checksum mismatch for {url}: expected {expected_sha256}, got {digest}"
        )
    os.replace(part, dest)
    return DownloadResult(
        path=dest, size=dest.stat().st_size, sha256=digest, resumed=resumed, attempts=attempts
    )


# --- helpers ------------------------------------------------------------


def _iter(resp: Any, chunk_size: int) -> Iterable[bytes]:
    iter_bytes = getattr(resp, "iter_bytes", None)
    if callable(iter_bytes):
        yield from iter_bytes(chunk_size)
        return
    content = bytes(getattr(resp, "content", b"") or b"")
    for i in range(0, len(content), chunk_size):
        yield content[i : i + chunk_size]


def _parse_total(resp: Any, have: int) -> int | None:
    headers = getattr(resp, "headers", {}) or {}
    content_range = _hget(headers, "content-range")
    if content_range and "/" in content_range:
        tail = content_range.rsplit("/", 1)[-1].strip()
        if tail.isdigit():
            return int(tail)
    content_length = _hget(headers, "content-length")
    if content_length is not None and str(content_length).isdigit():
        # 200: have==0 → total == length. 206: total == start + remaining length.
        return have + int(content_length)
    return None


def _hget(headers: Any, key: str) -> Any:
    try:
        value = headers.get(key)
    except AttributeError:
        value = None
    if value is not None:
        return value
    try:
        for k, v in headers.items():
            if str(k).lower() == key:
                return v
    except AttributeError:
        pass
    return None


def _sha256_file(path: Path, chunk_size: int = 1_048_576) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _default_opener(timeout: float = 30.0) -> Opener:
    def opener(url: str, start: int) -> Any:
        import httpx

        headers = {"Range": f"bytes={start}-"} if start > 0 else {}
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            # Materialize before the client closes; _iter falls back to .content.
            _ = resp.content
            return resp

    return opener
