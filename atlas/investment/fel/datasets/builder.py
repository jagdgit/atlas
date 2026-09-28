"""FEL.2 — point-in-time dataset builder.

as-of × symbol × features + target. Features see only bars with date ≤ as-of.
Targets may use future closes (labels, not features). jsonl under data_dir;
no new DB. Lab-stamped; mixing laboratories raises contamination.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from atlas.investment.bar_store import load_bars
from atlas.investment.fel.contracts import FEL_VERSION, FeatureMatrix
from atlas.investment.fel.features.store import is_observation_eligible
from atlas.investment.fel.registry import FelRegistries, default_fel
from atlas.investment.laboratory import (
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
    normalize_laboratory_id,
)

VERSION = "fel.2.pit"
STORE_REL = Path("investment") / "fel" / "datasets"
_log = logging.getLogger("atlas.investment.fel.datasets")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def bars_as_of(bars: Iterable[dict[str, Any]] | None, as_of: str) -> list[dict[str, Any]]:
    """Keep only bars whose session date is knowable at ``as_of`` (inclusive)."""
    cutoff = str(as_of or "")
    out: list[dict[str, Any]] = []
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        day = str(bar.get("date") or "")
        if day and day <= cutoff:
            out.append(bar)
    out.sort(key=lambda b: str(b.get("date") or ""))
    return out


def forward_return(
    bars: list[dict[str, Any]],
    as_of: str,
    *,
    horizon: int = 5,
) -> float | None:
    """Label: close[as_of + horizon] / close[as_of] - 1. None if either close missing."""
    dated = [b for b in bars if isinstance(b, dict) and b.get("date") and b.get("close") is not None]
    dated.sort(key=lambda b: str(b["date"]))
    idx = None
    for i, bar in enumerate(dated):
        if str(bar["date"]) == str(as_of):
            idx = i
            break
    if idx is None:
        return None
    later = idx + int(horizon)
    if later >= len(dated):
        return None
    try:
        start = float(dated[idx]["close"])
        end = float(dated[later]["close"])
    except (TypeError, ValueError):
        return None
    if start == 0:
        return None
    return end / start - 1.0


def _pit_context(
    bars: list[dict[str, Any]],
    *,
    benchmark_bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "bars": bars,
        "closes": [b.get("close") for b in bars if b.get("close") is not None],
        "volumes": [b.get("volume") for b in bars if b.get("volume") is not None],
        "benchmark_bars": list(benchmark_bars or []),
        "benchmark_closes": [
            b.get("close") for b in (benchmark_bars or []) if b.get("close") is not None
        ],
    }


def compute_features_as_of(
    fel: FelRegistries,
    bars: list[dict[str, Any]],
    as_of: str,
    *,
    feature_ids: list[str] | None = None,
    benchmark_bars: list[dict[str, Any]] | None = None,
    observation_only: bool = True,
) -> dict[str, Any]:
    pit_bars = bars_as_of(bars, as_of)
    bench = bars_as_of(benchmark_bars, as_of) if benchmark_bars is not None else []
    ctx = _pit_context(pit_bars, benchmark_bars=bench)
    recs = fel.features.list(include_retired=False)
    if feature_ids:
        want = set(feature_ids)
        recs = [r for r in recs if r.plugin_id in want]
    if observation_only:
        recs = [r for r in recs if is_observation_eligible(r)]
    values: dict[str, Any] = {}
    for rec in recs:
        try:
            values[rec.plugin_id] = rec.plugin.compute(ctx)
        except Exception:  # noqa: BLE001 - one bad computer must not poison the row
            _log.exception("feature %s compute failed", rec.plugin_id)
            values[rec.plugin_id] = None
    return values


def build_pit_dataset(
    data_dir: str | Path | None,
    *,
    symbols: list[str],
    as_of_dates: list[str],
    laboratory_id: str | None = None,
    feature_ids: list[str] | None = None,
    target_horizon: int = 5,
    benchmark_symbol: str | None = None,
    fel: FelRegistries | None = None,
) -> dict[str, Any]:
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    labs_seen = {lab}
    bundle = fel or default_fel()
    bench_all = load_bars(data_dir, benchmark_symbol) if benchmark_symbol and data_dir else []
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        bars = load_bars(data_dir, symbol) if data_dir else []
        for as_of in as_of_dates:
            feats = compute_features_as_of(
                bundle,
                bars,
                as_of,
                feature_ids=feature_ids,
                benchmark_bars=bench_all,
            )
            rows.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "laboratory_id": lab,
                    "features": feats,
                    "target": {
                        "target_id": "fwd_ret_5d" if int(target_horizon) == 5 else f"fwd_ret_{target_horizon}d",
                        "horizon": int(target_horizon),
                        "value": forward_return(bars, as_of, horizon=target_horizon),
                    },
                    "availability_time": "session_close",
                }
            )
    if len(labs_seen) != 1:
        raise LaboratoryContaminationError("PIT dataset mixed laboratories")
    return {
        "dataset_id": str(uuid4()),
        "version": VERSION,
        "fel_version": FEL_VERSION,
        "laboratory_id": lab,
        "decision_type": "buy_name",
        "symbols": list(symbols),
        "as_of_dates": list(as_of_dates),
        "feature_ids": feature_ids
        or [r.plugin_id for r in bundle.features.list() if is_observation_eligible(r)],
        "target_id": "fwd_ret_5d" if int(target_horizon) == 5 else f"fwd_ret_{target_horizon}d",
        "n_rows": len(rows),
        "built_at": _now_iso(),
        "rows": rows,
    }


def persist_pit_dataset(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = normalize_laboratory_id(
        laboratory_id=doc.get("laboratory_id") or DEFAULT_SWING_LAB
    )
    root = Path(data_dir) / STORE_REL / _safe(lab)
    root.mkdir(parents=True, exist_ok=True)
    dsid = _safe(str(doc.get("dataset_id") or uuid4()))
    path = root / f"{dsid}.jsonl"
    header = {k: v for k, v in doc.items() if k != "rows"}
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "dataset", **header}) + "\n")
        for row in doc.get("rows") or []:
            if extract_row_lab(row) not in (None, lab):
                raise LaboratoryContaminationError(
                    f"row laboratory {extract_row_lab(row)} != dataset {lab}"
                )
            fh.write(json.dumps({"kind": "row", **row}) + "\n")
    return path


def extract_row_lab(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    v = row.get("laboratory_id")
    return str(v).strip() if v else None


def load_pit_dataset(
    data_dir: str | Path | None,
    dataset_id: str,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir or not dataset_id:
        return None
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    path = Path(data_dir) / STORE_REL / _safe(lab) / f"{_safe(dataset_id)}.jsonl"
    if not path.is_file():
        return None
    header: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                kind = obj.get("kind")
                body = {k: v for k, v in obj.items() if k != "kind"}
                if kind == "dataset":
                    header = body
                elif kind == "row":
                    rows.append(body)
                elif header is None:
                    header = body
                else:
                    rows.append(body)
    except (OSError, json.JSONDecodeError):
        return None
    if not header:
        return None
    header["rows"] = rows
    header["n_rows"] = len(rows)
    return header


def assert_lab_hermetic(doc: dict[str, Any]) -> str:
    lab = normalize_laboratory_id(laboratory_id=doc.get("laboratory_id") or DEFAULT_SWING_LAB)
    for row in doc.get("rows") or []:
        other = extract_row_lab(row)
        if other and other != lab:
            raise LaboratoryContaminationError(
                f"PIT row laboratory {other} != dataset {lab}"
            )
    return lab


def pit_to_matrix(doc: dict[str, Any], *, feature_ids: list[str] | None = None) -> FeatureMatrix:
    assert_lab_hermetic(doc)
    ids = list(feature_ids or doc.get("feature_ids") or [])
    rows: list[dict[str, Any]] = []
    for row in doc.get("rows") or []:
        feats = row.get("features") if isinstance(row.get("features"), dict) else {}
        item = {
            "symbol": row.get("symbol"),
            "as_of": row.get("as_of"),
            "laboratory_id": row.get("laboratory_id"),
            "target": (row.get("target") or {}).get("value")
            if isinstance(row.get("target"), dict)
            else None,
        }
        for fid in ids:
            item[fid] = feats.get(fid)
        rows.append(item)
    return FeatureMatrix(
        rows=rows,
        meta={
            "dataset_id": doc.get("dataset_id"),
            "laboratory_id": doc.get("laboratory_id"),
            "feature_ids": ids,
        },
    )
