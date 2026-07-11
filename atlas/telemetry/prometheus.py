"""Render the in-process metrics snapshot as Prometheus text (ADR-0054).

The MetricsRegistry stores keys as ``name|k=v,k2=v2`` (ADR-0039). This module
turns a ``snapshot()`` into the Prometheus text exposition format without adding a
client library:

    counters   -> <name> <value>            (with {labels})
    gauges     -> <name> <value>
    histograms -> <name>_count / _sum / _avg / _max / _p50 / _p95

Metric names are sanitized (``.`` and other illegal chars -> ``_``) so scrapers
accept them. This is intentionally minimal; a full client can replace it later
behind the same endpoint.
"""

from __future__ import annotations

import re
from typing import Any

_ILLEGAL = re.compile(r"[^a-zA-Z0-9_:]")


def _sanitize_name(name: str) -> str:
    clean = _ILLEGAL.sub("_", name)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean


def _split_key(key: str) -> tuple[str, dict[str, str]]:
    """Split ``name|k=v,k2=v2`` into (name, labels)."""
    if "|" not in key:
        return key, {}
    name, _, tag_str = key.partition("|")
    labels: dict[str, str] = {}
    for pair in tag_str.split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            labels[k] = v
    return name, labels


def _labels_str(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{_sanitize_name(k)}="{_escape(v)}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _line(name: str, labels: dict[str, str], value: Any) -> str:
    return f"atlas_{_sanitize_name(name)}{_labels_str(labels)} {value}"


def render_prometheus(snapshot: dict[str, Any]) -> str:
    """Return Prometheus text exposition for a MetricsRegistry snapshot."""
    lines: list[str] = []

    for key, value in sorted(snapshot.get("counters", {}).items()):
        name, labels = _split_key(key)
        lines.append(_line(name, labels, value))

    for key, value in sorted(snapshot.get("gauges", {}).items()):
        name, labels = _split_key(key)
        lines.append(_line(name, labels, value))

    for key, summary in sorted(snapshot.get("histograms", {}).items()):
        name, labels = _split_key(key)
        for stat in ("count", "sum", "avg", "max", "p50", "p95"):
            if stat in summary:
                lines.append(_line(f"{name}_{stat}", labels, summary[stat]))

    return "\n".join(lines) + "\n" if lines else "\n"
