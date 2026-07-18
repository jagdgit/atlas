"""Bounded in-process worker helpers (Stage 3.2b).

Uses ``ThreadPoolExecutor`` inside a research job — not Celery. The durable Job
Engine / scheduler already queues *jobs*; these pools overlap document work
*within* one research step under operator ``resources.*`` caps.

Hard rules (D32.3 / A32.16):
- Never exceed ``max_worker_threads`` / pool caps from config/env.
- Full pools → work queues inside the executor (slower), never fail the job.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def clamp_workers(
    requested: int,
    *,
    global_max: int,
    fallback: int = 1,
    queue_depth: int | None = None,
    work_count: int | None = None,
) -> int:
    """Adaptive pool size: caps + actual queued work (D32.12)."""
    req = int(requested or 0)
    cap = int(global_max or 0)
    if cap <= 0:
        cap = max(fallback, req or fallback)
    if req <= 0:
        req = fallback
    limits = [req, cap]
    if queue_depth is not None:
        limits.append(max(fallback, int(queue_depth)))
    if work_count is not None:
        limits.append(max(fallback, int(work_count)))
    return max(fallback, min(limits))


def map_parallel(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int,
    ordered: bool = True,
    logger: logging.Logger | None = None,
) -> list[R]:
    """Run ``fn`` over ``items`` with a bounded thread pool.

    When ``ordered`` is True, results are returned in **input order** (deterministic),
    even though execution overlaps. ``max_workers <= 1`` runs serially.

    Fault isolation (D: one bad item ≠ batch failure): a worker that raises is
    logged and its slot dropped, so a single failure can never discard the results
    of its siblings. Callers get every successful result; failures surface via the
    optional ``logger``. This prevents regressions where one document's reader/
    extractor exception silently wiped out an entire acquisition round.
    """
    seq = list(items)
    if not seq:
        return []
    workers = clamp_workers(max_workers, global_max=max_workers, fallback=1)
    if workers <= 1 or len(seq) == 1:
        out: list[R] = []
        for item in seq:
            try:
                out.append(fn(item))
            except Exception:  # noqa: BLE001 - isolate per-item failure
                if logger is not None:
                    logger.exception("map_parallel item failed; skipping")
        return out

    results: list[R | None] = [None] * len(seq)
    with ThreadPoolExecutor(max_workers=min(workers, len(seq))) as pool:
        futures = {pool.submit(fn, item): idx for idx, item in enumerate(seq)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception:  # noqa: BLE001 - isolate per-item failure
                if logger is not None:
                    logger.exception("map_parallel worker failed; skipping")
                results[idx] = None
    return [r for r in results if r is not None]  # type: ignore[misc]
