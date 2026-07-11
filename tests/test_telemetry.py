"""Tests for telemetry: metrics, timers, tracing (ADR-0039)."""

from __future__ import annotations

import time

from atlas.telemetry import (
    MetricsRegistry,
    current_span,
    get_metrics,
    start_span,
    timed,
    timer,
)


def test_metrics_counters_gauges_histograms():
    m = MetricsRegistry()
    m.incr("tasks", task_type="embed")
    m.incr("tasks", 2, task_type="embed")
    m.gauge("workers", 4)
    m.observe("latency", 10.0)
    m.observe("latency", 20.0)
    snap = m.snapshot()
    assert snap["counters"]["tasks|task_type=embed"] == 3
    assert snap["gauges"]["workers"] == 4
    assert snap["histograms"]["latency"]["count"] == 2
    assert snap["histograms"]["latency"]["avg"] == 15.0


def test_timer_records_duration_to_registry():
    m = MetricsRegistry()
    with timer("work", metrics=m):
        time.sleep(0.005)
    hist = m.snapshot()["histograms"]
    assert "work.duration_ms" in hist
    assert hist["work.duration_ms"]["count"] == 1
    assert hist["work.duration_ms"]["max"] >= 5.0


def test_timed_decorator_uses_global_registry():
    get_metrics().reset()

    @timed("decorated.fn")
    def slow(x):
        return x * 2

    assert slow(3) == 6
    hist = get_metrics().snapshot()["histograms"]
    assert hist["decorated.fn.duration_ms"]["count"] == 1


def test_spans_nest_and_share_trace_id():
    assert current_span() is None
    with start_span("outer") as outer:
        assert current_span() is outer
        with start_span("inner") as inner:
            assert inner.parent_id == outer.span_id
            assert inner.trace_id == outer.trace_id
            assert current_span() is inner
        assert current_span() is outer
    assert current_span() is None
    assert outer.duration_ms is not None


def test_timer_annotates_active_span():
    m = MetricsRegistry()
    with start_span("req") as span:
        with timer("step", metrics=m):
            pass
    assert "step.duration_ms" in span.attributes
