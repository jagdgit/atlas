"""Lightweight tracing (ADR-0039).

A span is a named, timed unit of work with a parent, so one request can be
followed across ``Agent -> Knowledge -> Embedding -> LLM``. Spans nest via a
``ContextVar`` (works across threads because each thread gets its own context).
No exporter yet; spans annotate the current context and record their duration to
metrics, and can be persisted to ``audit``/``analytics`` later.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

_current_span: contextvars.ContextVar["Span | None"] = contextvars.ContextVar(
    "atlas_current_span", default=None
)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str | None
    start: float
    attributes: dict[str, Any] = field(default_factory=dict)
    end: float | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return (self.end - self.start) * 1000.0

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value


def current_span() -> Span | None:
    return _current_span.get()


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Span]:
    parent = _current_span.get()
    span = Span(
        name=name,
        trace_id=parent.trace_id if parent else uuid.uuid4().hex,
        span_id=uuid.uuid4().hex,
        parent_id=parent.span_id if parent else None,
        start=time.perf_counter(),
        attributes=dict(attributes),
    )
    token = _current_span.set(span)
    try:
        yield span
    finally:
        span.end = time.perf_counter()
        _current_span.reset(token)
