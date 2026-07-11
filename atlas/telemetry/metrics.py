"""In-process metrics (ADR-0039).

Counters, gauges, and histograms held in memory with no external dependency. A
real exporter (Prometheus/OTel) can be added later by reading ``snapshot()``; the
call sites (``incr``/``gauge``/``observe``) stay unchanged (§18.9 F2).

Thread-safe: the scheduler runs worker threads, so updates take a lock.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


def _key(name: str, labels: dict[str, Any]) -> str:
    if not labels:
        return name
    tags = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}|{tags}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def incr(self, name: str, value: float = 1.0, **labels: Any) -> None:
        with self._lock:
            self._counters[_key(name, labels)] += value

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self._gauges[_key(name, labels)] = value

    def observe(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self._histograms[_key(name, labels)].append(value)

    def snapshot(self) -> dict[str, Any]:
        """Return a plain-dict copy of all metrics (safe to serialize/log)."""
        with self._lock:
            hist = {
                key: _summarize(samples)
                for key, samples in self._histograms.items()
            }
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": hist,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


def _summarize(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"count": 0}
    ordered = sorted(samples)
    count = len(ordered)
    return {
        "count": count,
        "sum": sum(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "avg": sum(ordered) / count,
        "p50": ordered[int(0.5 * (count - 1))],
        "p95": ordered[int(0.95 * (count - 1))],
    }


_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    """Return the process-wide metrics registry."""
    return _metrics
