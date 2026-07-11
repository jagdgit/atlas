"""Timing helpers (ADR-0039).

``timer`` (context manager) and ``timed`` (decorator) measure elapsed time and
record it to the metrics registry as ``<name>.duration_ms``. If a span is active,
the duration is also attached to it, so timing shows up in both aggregate metrics
and per-request traces. Timing never changes behaviour and never raises.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

from atlas.telemetry.metrics import MetricsRegistry, get_metrics
from atlas.telemetry.tracing import current_span

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def timer(
    name: str, *, metrics: MetricsRegistry | None = None, **labels: Any
) -> Iterator[None]:
    registry = metrics or get_metrics()
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        registry.observe(f"{name}.duration_ms", elapsed_ms, **labels)
        span = current_span()
        if span is not None:
            span.set(f"{name}.duration_ms", round(elapsed_ms, 3))


def timed(name: str | None = None, **labels: Any) -> Callable[[F], F]:
    """Decorator form of :func:`timer`; defaults the metric to the qualified name."""

    def decorate(fn: F) -> F:
        metric_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with timer(metric_name, **labels):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
