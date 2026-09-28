"""Experiment records — json under {data}/investment/fel/experiments/{lab}/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.laboratory import DEFAULT_SWING_LAB, normalize_laboratory_id

STORE_REL = Path("investment") / "fel" / "experiments"


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def persist_experiment(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = normalize_laboratory_id(
        laboratory_id=doc.get("laboratory_id") or DEFAULT_SWING_LAB
    )
    root = Path(data_dir) / STORE_REL / _safe(lab)
    root.mkdir(parents=True, exist_ok=True)
    eid = _safe(str(doc.get("experiment_id") or uuid4()))
    path = root / f"{eid}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_experiment(
    data_dir: str | Path | None,
    experiment_id: str,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir or not experiment_id:
        return None
    lab = normalize_laboratory_id(
        laboratory_id=laboratory_id or DEFAULT_SWING_LAB
    )
    path = Path(data_dir) / STORE_REL / _safe(lab) / f"{_safe(experiment_id)}.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return row if isinstance(row, dict) else None
