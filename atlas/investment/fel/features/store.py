"""Persist feature registry rows (genealogy on the row — not a parallel product).

Layout::
    {data}/investment/fel/features/{feature_id}@{version}.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.investment.fel.contracts import (
    DECISION_ELIGIBLE_STATUSES,
    OBSERVATION_STATUSES,
    FEL_VERSION,
    FeatureGenealogy,
    FeatureStatus,
)
from atlas.investment.fel.registry import FeatureRegistry, RegistryRecord

VERSION = "fel.1.feature_store"
STORE_REL = Path("investment") / "fel" / "features"
_log = logging.getLogger("atlas.investment.fel.features")

MERGE_KEYS = (
    "result",
    "not_useful_for",
    "tested_models",
    "usage_count",
    "predictive_score",
    "stability",
    "correlation",
    "importance",
    "last_evaluated",
    "data_quality",
    "status",
    "hypothesis_id",
    "scientist_reason",
    "lesson_eligible",
)


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-@" else "_" for c in (s or ""))[:120]


def store_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def feature_path(data_dir: str | Path, feature_id: str, version: str) -> Path:
    return store_dir(data_dir) / f"{_safe(feature_id)}@{_safe(version)}.json"


def effective_status(rec: RegistryRecord) -> str:
    extra = rec.extra if isinstance(rec.extra, dict) else {}
    raw = extra.get("status") or getattr(rec.plugin, "status", None) or "registered"
    return str(raw)


def is_decision_eligible(rec: RegistryRecord) -> bool:
    """Untested / candidate features stay out of the live decision model."""
    return effective_status(rec) in DECISION_ELIGIBLE_STATUSES


def is_lesson_eligible(rec: RegistryRecord) -> bool:
    """CLC.3 — may inform L1/L2 caution without entering live_control."""
    extra = rec.extra if isinstance(rec.extra, dict) else {}
    if extra.get("lesson_eligible") is True:
        return True
    if extra.get("lesson_eligible") is False:
        return False
    return bool(getattr(rec.plugin, "lesson_eligible", False))


def is_observation_eligible(rec: RegistryRecord) -> bool:
    """Broad observation space — keep candidates for experiments."""
    return effective_status(rec) in OBSERVATION_STATUSES


def genealogy_from_record(rec: RegistryRecord) -> FeatureGenealogy:
    plugin = rec.plugin
    extra = dict(rec.extra or {})
    status = effective_status(rec)
    return FeatureGenealogy(
        feature_id=str(getattr(plugin, "feature_id", rec.plugin_id)),
        version=str(getattr(plugin, "version", rec.version)),
        sources=list(getattr(plugin, "sources", extra.get("sources") or ("bars",))),
        formula=str(extra.get("formula") or getattr(plugin, "formula", "") or ""),
        timeframe=str(getattr(plugin, "timeframe", extra.get("timeframe") or "1d")),
        lookback=int(getattr(plugin, "lookback", extra.get("lookback") or 0) or 0),
        availability_time=str(
            extra.get("availability_time")
            or getattr(plugin, "availability_time", "session_close")
        ),
        origin=str(extra.get("origin") or getattr(plugin, "origin", "wrap")),
        hypothesis_id=extra.get("hypothesis_id") or getattr(plugin, "hypothesis_id", None),
        scientist_reason=str(
            extra.get("scientist_reason") or getattr(plugin, "scientist_reason", "") or ""
        ),
        source_concepts=list(
            extra.get("source_concepts") or getattr(plugin, "source_concepts", ()) or ()
        ),
        derived_from=list(extra.get("derived_from") or getattr(plugin, "derived_from", ()) or ()),
        tested_for=list(extra.get("tested_for") or getattr(plugin, "tested_for", ()) or ()),
        tested_models=list(extra.get("tested_models") or ()),
        result=extra.get("result"),
        not_useful_for=list(extra.get("not_useful_for") or ()),
        status=status,  # type: ignore[arg-type]
        data_quality=extra.get("data_quality"),
        usage_count=int(extra.get("usage_count") or 0),
        predictive_score=dict(extra.get("predictive_score") or {}),
        stability=extra.get("stability"),
        correlation=dict(extra.get("correlation") or {}),
        importance=dict(extra.get("importance") or {}),
        last_evaluated=extra.get("last_evaluated"),
        lesson_eligible=bool(
            extra.get("lesson_eligible")
            if extra.get("lesson_eligible") is not None
            else getattr(plugin, "lesson_eligible", False)
        ),
    )


def persist_feature_row(data_dir: str | Path | None, row: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(row, dict) or not row.get("feature_id"):
        return None
    fid = str(row["feature_id"])
    ver = str(row.get("version") or "1")
    root = store_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = feature_path(data_dir, fid, ver)
    payload = {
        "store_version": VERSION,
        "fel_version": FEL_VERSION,
        **row,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def persist_feature_registry(data_dir: str | Path | None, registry: FeatureRegistry) -> int:
    if not data_dir:
        return 0
    n = 0
    for rec in registry.list():
        row = genealogy_from_record(rec).as_dict()
        if persist_feature_row(data_dir, row) is not None:
            n += 1
    return n


def load_feature_rows(data_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not data_dir:
        return out
    root = store_dir(data_dir)
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _log.warning("skip unreadable feature row %s", path)
            continue
        if not isinstance(row, dict) or not row.get("feature_id"):
            continue
        key = f"{row['feature_id']}@{row.get('version') or '1'}"
        out[key] = row
    return out


def overlay_persisted(registry: FeatureRegistry, data_dir: str | Path | None) -> int:
    """Merge on-disk scientific memory onto in-process extras. Computers stay in code."""
    disk = load_feature_rows(data_dir)
    if not disk:
        return 0
    n = 0
    for rec in registry.list():
        row = disk.get(rec.key)
        if not row:
            continue
        for key in MERGE_KEYS:
            if key in row and row[key] is not None:
                rec.extra[key] = row[key]
        n += 1
    return n


def record_evaluation(
    data_dir: str | Path | None,
    registry: FeatureRegistry,
    feature_id: str,
    *,
    result: str | None = None,
    not_useful_for: list[str] | None = None,
    tested_model: str | None = None,
    last_evaluated: str | None = None,
    status: FeatureStatus | None = None,
) -> dict[str, Any] | None:
    rec = registry.get(feature_id)
    if rec is None:
        return None
    if result is not None:
        rec.extra["result"] = result
    if not_useful_for is not None:
        rec.extra["not_useful_for"] = list(not_useful_for)
    if tested_model:
        models = list(rec.extra.get("tested_models") or [])
        if tested_model not in models:
            models.append(tested_model)
        rec.extra["tested_models"] = models
    if last_evaluated:
        rec.extra["last_evaluated"] = last_evaluated
    if status:
        rec.extra["status"] = status
    rec.extra["usage_count"] = int(rec.extra.get("usage_count") or 0) + 1
    row = genealogy_from_record(rec).as_dict()
    persist_feature_row(data_dir, row)
    return row
