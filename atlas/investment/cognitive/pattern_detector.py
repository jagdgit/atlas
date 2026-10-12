"""Cognitive Loop C3a — find candidate patterns in closed-loop episodes.

Scans *declared dimensions* of the canonical closed-loop dataset and reports where
outcomes split unevenly. It does not know which dimension matters: no option type,
underlying, direction or model name is privileged anywhere in this module. If the
CE/PE asymmetry is real, it has to fall out of the same generic scan as everything
else — naming it here would be us having the insight, not Atlas.

Output is always a CANDIDATE_PATTERN with ``status=HYPOTHESIS_CANDIDATE`` or
``INSUFFICIENT_SAMPLE``. Never a lesson, never a learning, never a verdict.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.pattern.v1"
KIND = "CANDIDATE_PATTERN"
STORE_REL = Path("investment") / "cognitive" / "patterns"

STATUS_CANDIDATE = "HYPOTHESIS_CANDIDATE"
STATUS_INSUFFICIENT = "INSUFFICIENT_SAMPLE"

# Operator-set gate (plan §7.3): record the question at n>=3 per group, but a pattern
# that thin can never support a verdict.
MIN_GROUP_N = 3
# Below this, the split is not worth asking about at all.
MIN_SPLIT_DELTA = 0.5

# Episode fields that may be grouped on. Each entry is (dimension, extractor path).
# Adding a dimension here is how Atlas gets a wider search space — not by naming a
# conclusion.
DIMENSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("option_type", ("option_type",)),
    ("underlying_type", ("features", "underlying_type")),
    ("control_action", ("features", "control_action")),
    ("signal", ("features", "signal")),
    ("expected_direction", ("prediction", "expected_direction")),
    ("er_model", ("prediction", "er_model")),
    ("prediction_horizon", ("prediction", "prediction_horizon")),
    ("sma_margin_sign", ("_derived", "sma_margin_sign")),
    ("holding_bucket", ("_derived", "holding_bucket")),
    ("underlier_direction", ("_derived", "underlier_direction")),
)

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.pattern_detector")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _dig(row: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = row
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _holding_bucket(row: dict[str, Any]) -> str | None:
    mins = row.get("holding_minutes")
    if mins is None:
        start = _dig(row, ("fill", "entry_at")) or _dig(row, ("entry", "at"))
        end = _dig(row, ("fill", "exit_at")) or _dig(row, ("exit", "at"))
        if not start or not end:
            return None
        try:
            delta = datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
        except (TypeError, ValueError):
            return None
        mins = delta.total_seconds() / 60.0
    try:
        m = float(mins)
    except (TypeError, ValueError):
        return None
    if m < 60:
        return "under_1h"
    if m < 240:
        return "1h_to_4h"
    return "over_4h"


def _sma_margin_sign(row: dict[str, Any]) -> str | None:
    val = _dig(row, ("features", "sma_margin"))
    try:
        m = float(val)
    except (TypeError, ValueError):
        return None
    return "positive" if m > 0 else ("negative" if m < 0 else "flat")


def _underlier_direction(row: dict[str, Any]) -> str | None:
    val = _dig(row, ("underlier_movement", "price_change_pct"))
    if val is None:
        val = _dig(row, ("underlier_movement", "session", "return_pct"))
    try:
        pct = float(val)
    except (TypeError, ValueError):
        return None
    return "up" if pct > 0 else ("down" if pct < 0 else "flat")


def _derive(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    enriched["_derived"] = {
        "holding_bucket": _holding_bucket(row),
        "sma_margin_sign": _sma_margin_sign(row),
        "underlier_direction": _underlier_direction(row),
    }
    return enriched


def _outcome_hit(row: dict[str, Any]) -> bool | None:
    """Did the episode's own stated prediction come true? Not 'did it make money'."""
    err = row.get("prediction_error") if isinstance(row.get("prediction_error"), dict) else {}
    match = str(err.get("direction_match") or "").lower()
    if match == "matched":
        return True
    if match == "missed":
        return False
    return None


def detect_patterns(
    rows: list[dict[str, Any]] | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    min_group_n: int = MIN_GROUP_N,
) -> list[dict[str, Any]]:
    """Group episodes by each declared dimension and report uneven hit rates."""
    episodes = [r for r in (rows or []) if isinstance(r, dict)]
    scored = [(_derive(r), _outcome_hit(r)) for r in episodes]
    usable = [(r, hit) for r, hit in scored if hit is not None]
    day = as_of_ist or ist_today()

    patterns: list[dict[str, Any]] = []
    for dimension, path in DIMENSIONS:
        groups: dict[str, dict[str, int]] = {}
        members: dict[str, list[str]] = {}
        for row, hit in usable:
            value = _dig(row, path)
            if value in (None, ""):
                continue
            key = str(value)
            g = groups.setdefault(key, {"n": 0, "hits": 0})
            g["n"] += 1
            g["hits"] += 1 if hit else 0
            members.setdefault(key, []).append(str(row.get("experience_id") or ""))
        if len(groups) < 2:
            # One group is not a contrast — nothing to ask.
            continue

        detail = {
            key: {
                "n": g["n"],
                "hits": g["hits"],
                "hit_rate": round(g["hits"] / g["n"], 4) if g["n"] else None,
            }
            for key, g in groups.items()
        }
        rates = [(k, v["hit_rate"]) for k, v in detail.items() if v["hit_rate"] is not None]
        if len(rates) < 2:
            continue
        rates.sort(key=lambda kv: kv[1], reverse=True)
        best, worst = rates[0], rates[-1]
        delta = round(float(best[1]) - float(worst[1]), 4)
        if delta < MIN_SPLIT_DELTA:
            continue

        thin = [k for k, v in detail.items() if v["n"] < min_group_n]
        status = STATUS_INSUFFICIENT if thin else STATUS_CANDIDATE
        patterns.append(
            {
                "version": VERSION,
                "kind": KIND,
                "status": status,
                "laboratory_id": str(laboratory_id or ""),
                "as_of_ist": day,
                "dimension": dimension,
                "groups": detail,
                "n_total": sum(v["n"] for v in detail.values()),
                "high_group": best[0],
                "low_group": worst[0],
                "split_delta": delta,
                "thin_groups": thin,
                "min_group_n": int(min_group_n),
                "_partition": frozenset(
                    frozenset(ids) for ids in members.values()
                ),
                "source_experience_ids": [
                    str(r.get("experience_id"))
                    for r, _ in usable
                    if r.get("experience_id")
                ],
                "observation": (
                    f"Grouping {len(usable)} closed episodes by {dimension}: "
                    f"{best[0]} hit {detail[best[0]]['hits']}/{detail[best[0]]['n']}, "
                    f"{worst[0]} hit {detail[worst[0]]['hits']}/{detail[worst[0]]['n']}."
                ),
                "honesty": (
                    "Candidate pattern only. Direction-match split on a single day is "
                    "not an effect. "
                    + (
                        f"Groups below n={min_group_n} ({', '.join(thin)}) cannot support "
                        "a verdict — the question is recorded, the answer is not."
                        if thin
                        else "Sample clears the recording gate; it still needs an "
                        "independent test before any verdict."
                    )
                ),
            }
        )

    _mark_confounds(patterns)
    # One cycle asks one question. Spend it on a split this sample can separate.
    # A larger gap that is tied to other dimensions is the same claim twice, so it
    # ranks behind a smaller gap that is not.
    patterns.sort(
        key=lambda p: (
            p["status"] != STATUS_CANDIDATE,
            bool(p.get("confounded_with")),
            -float(p.get("split_delta") or 0),
        )
    )
    return patterns


def _mark_confounds(patterns: list[dict[str, Any]]) -> None:
    """Dimensions that split the same episodes the same way are indistinguishable.

    With CE always bought on a positive control margin, 'CE is better' and 'positive
    margin is better' are one claim wearing two names. Saying which is which needs a
    sample where they come apart, so each pattern names the others it is tied to
    instead of pretending to be the explanation.
    """
    for pattern in patterns:
        signature = pattern.get("_partition")
        tied = [
            other["dimension"]
            for other in patterns
            if other is not pattern and other.get("_partition") == signature
        ]
        pattern["confounded_with"] = tied
        if tied:
            pattern["honesty"] += (
                f" Indistinguishable from {', '.join(tied)} in this sample — these "
                "dimensions split the same episodes identically, so this one is not "
                "singled out as the cause."
            )
    for pattern in patterns:
        pattern.pop("_partition", None)


def persist_patterns(
    data_dir: str | Path | None,
    patterns: list[dict[str, Any]] | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    rows = [p for p in (patterns or []) if isinstance(p, dict)]
    day = as_of_ist or ist_today()
    try:
        path = Path(data_dir) / STORE_REL / str(laboratory_id) / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "path": str(path), "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("pattern persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_patterns(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    path = (
        Path(data_dir)
        / STORE_REL
        / str(laboratory_id)
        / f"{as_of_ist or ist_today()}.jsonl"
    )
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows
