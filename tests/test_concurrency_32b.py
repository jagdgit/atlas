"""Tests for Stage 3.2b in-process concurrency (no Celery)."""

from __future__ import annotations

import threading
import time

from atlas.evidence.models import Source
from atlas.net import OUTCOME_OK, FetchResult
from atlas.research.acquire import Librarian
from atlas.research.concurrency import clamp_workers, map_parallel


def test_clamp_workers_never_exceeds_global():
    assert clamp_workers(8, global_max=4) == 4
    assert clamp_workers(0, global_max=4) == 1
    assert clamp_workers(2, global_max=4) == 2


def test_map_parallel_preserves_input_order():
    def slow_square(n: int) -> int:
        # Larger inputs finish first if unordered; ordered must still return 1,4,9…
        time.sleep(0.03 * (4 - n))
        return n * n

    out = map_parallel(slow_square, [1, 2, 3], max_workers=3, ordered=True)
    assert out == [1, 4, 9]


def test_map_parallel_serial_when_one_worker():
    seen: list[int] = []

    def mark(n: int) -> int:
        seen.append(n)
        return n

    assert map_parallel(mark, [3, 1, 2], max_workers=1, ordered=True) == [3, 1, 2]
    assert seen == [3, 1, 2]


def test_map_parallel_isolates_worker_failures():
    # One item raising must NOT abort the batch — siblings still return (D: fault
    # isolation). Regression guard for the acquire batch-discard bug (2026-07-18).
    def fn(x: int) -> int:
        if x == 3:
            raise ValueError("bad item")
        return x * 2

    parallel = map_parallel(fn, [1, 2, 3, 4], max_workers=2, ordered=True)
    assert sorted(parallel) == [2, 4, 8]  # 3 dropped; 1,2,4 survive

    serial = map_parallel(fn, [1, 2, 3, 4], max_workers=1, ordered=True)
    assert serial == [2, 4, 8]


def test_librarian_parallel_acquire_orders_by_source_id():
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}

    class SlowFetcher:
        def get(self, url):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            try:
                time.sleep(0.05)
                body = f"<html><body>Abstract: value for {url}</body></html>"
                return FetchResult(
                    url, OUTCOME_OK, content_type="text/html",
                    text=body, content=body.encode(),
                )
            finally:
                with lock:
                    active["n"] -= 1

    sources = [
        Source(id="c", url="https://ex.com/c", title="C", evidence_level=2),
        Source(id="a", url="https://ex.com/a", title="A", evidence_level=2),
        Source(id="b", url="https://ex.com/b", title="B", evidence_level=2),
    ]
    lib = Librarian(
        SlowFetcher(),
        prefer_ar5iv=False,
        max_workers=3,
        global_max_workers=4,
    )
    result = lib.acquire(sources)
    assert result.stats["read"] == 3
    ids = [d.source_id for d in result.documents]
    assert ids == sorted(ids)  # deterministic source_id order
    assert active["peak"] >= 2  # overlapped work
