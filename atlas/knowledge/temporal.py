"""Temporal Knowledge helpers (OI-F2).

Classify findings as historical / current / predicted using existing
``valid_from`` / ``valid_until``, status, and optional provenance stamps.
No new Knowledge DB — freshness stays orthogonal (a current fact can still be aging).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TRUTH_HISTORICAL = "historical"
TRUTH_CURRENT = "current"
TRUTH_PREDICTED = "predicted"

_PREDICTED_CLAIM_TYPES = frozenset({"forecast", "prediction", "predicted"})
_HISTORICAL_STATUSES = frozenset({"superseded", "deprecated", "archived"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _explicit_truth_kind(finding: dict[str, Any]) -> str | None:
    prov = finding.get("provenance") if isinstance(finding.get("provenance"), dict) else {}
    quality = finding.get("quality") if isinstance(finding.get("quality"), dict) else {}
    temporal = quality.get("temporal") if isinstance(quality.get("temporal"), dict) else {}
    for raw in (
        finding.get("truth_kind"),
        prov.get("truth_kind"),
        temporal.get("truth_kind"),
    ):
        kind = str(raw or "").strip().lower()
        if kind in {TRUTH_HISTORICAL, TRUTH_CURRENT, TRUTH_PREDICTED}:
            return kind
    claim = str(finding.get("claim_type") or "").strip().lower()
    if claim in _PREDICTED_CLAIM_TYPES:
        return TRUTH_PREDICTED
    return None


def truth_kind(finding: dict[str, Any], *, now: datetime | None = None) -> str:
    """Classify a finding as historical, current, or predicted."""
    explicit = _explicit_truth_kind(finding)
    if explicit is not None:
        return explicit

    clock = now or _utcnow()
    status = str(finding.get("status") or "").strip().lower()
    if status in _HISTORICAL_STATUSES:
        return TRUTH_HISTORICAL

    valid_until = _as_dt(finding.get("valid_until"))
    if valid_until is not None and valid_until < clock:
        return TRUTH_HISTORICAL

    valid_from = _as_dt(finding.get("valid_from"))
    if valid_from is not None and valid_from > clock:
        return TRUTH_PREDICTED

    return TRUTH_CURRENT


def stamp_validity(
    data: dict[str, Any],
    *,
    valid_from: Any = None,
    valid_until: Any = None,
    truth_kind_value: str | None = None,
) -> dict[str, Any]:
    """Return a shallow-copied finding dict with validity window (+ optional truth stamp)."""
    out = dict(data)
    if valid_from is not None:
        dt = _as_dt(valid_from)
        out["valid_from"] = dt.isoformat() if dt else valid_from
    if valid_until is not None:
        dt = _as_dt(valid_until)
        out["valid_until"] = dt.isoformat() if dt else valid_until
    if truth_kind_value:
        kind = str(truth_kind_value).strip().lower()
        if kind in {TRUTH_HISTORICAL, TRUTH_CURRENT, TRUTH_PREDICTED}:
            prov = dict(out.get("provenance") or {}) if isinstance(out.get("provenance"), dict) else {}
            prov["truth_kind"] = kind
            out["provenance"] = prov
            out["truth_kind"] = kind
    return out


def stamp_prediction(
    data: dict[str, Any],
    *,
    horizon_until: Any,
    valid_from: Any = None,
) -> dict[str, Any]:
    """Mark a finding as predicted with a horizon end (and optional start)."""
    stamped = stamp_validity(
        data,
        valid_from=valid_from if valid_from is not None else _utcnow().isoformat(),
        valid_until=horizon_until,
        truth_kind_value=TRUTH_PREDICTED,
    )
    if not stamped.get("claim_type") or stamped.get("claim_type") == "prose":
        stamped["claim_type"] = "forecast"
    return stamped


def partition_by_truth(
    findings: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        TRUTH_HISTORICAL: [],
        TRUTH_CURRENT: [],
        TRUTH_PREDICTED: [],
    }
    for row in findings:
        if not isinstance(row, dict):
            continue
        kind = truth_kind(row, now=now)
        buckets.setdefault(kind, []).append(row)
    return buckets


def is_operative_fact(finding: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True when the finding is current truth (not predicted, not historical)."""
    return truth_kind(finding, now=now) == TRUTH_CURRENT


def annotate_finding_item(finding: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """MCA-facing projection fields for a finding row."""
    return {
        "truth_kind": truth_kind(finding, now=now),
        "freshness": finding.get("freshness"),
        "valid_from": finding.get("valid_from"),
        "valid_until": finding.get("valid_until"),
    }
