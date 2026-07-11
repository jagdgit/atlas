"""Observability for Atlas (ADR-0039): metrics, tracing, timers.

Introduced early so instrumentation is habitual rather than retrofitted. Wired at
the pipeline seams (LLM/knowledge/scheduler/agent), so ``Agent -> Knowledge ->
Embedding -> LLM`` is timed and traceable automatically. In-process for v1; an
exporter (Prometheus/OTel) reads ``get_metrics().snapshot()`` later (§18.9 F2).
"""

from __future__ import annotations

from atlas.telemetry.metrics import MetricsRegistry, get_metrics
from atlas.telemetry.prometheus import render_prometheus
from atlas.telemetry.timers import timed, timer
from atlas.telemetry.tracing import Span, current_span, start_span

__all__ = [
    "MetricsRegistry",
    "get_metrics",
    "render_prometheus",
    "timer",
    "timed",
    "Span",
    "start_span",
    "current_span",
]
