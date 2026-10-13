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

from atlas.investment.cognitive.stats import benjamini_hochberg, fisher_exact

VERSION = "cognitive.pattern.v2"
KIND = "CANDIDATE_PATTERN"
STORE_REL = Path("investment") / "cognitive" / "patterns"

STATUS_CANDIDATE = "HYPOTHESIS_CANDIDATE"
STATUS_INSUFFICIENT = "INSUFFICIENT_SAMPLE"
STATUS_POST_HOC = "POST_HOC_ONLY"

# Operator-set gate (plan §7.3): record the question at n>=3 per group, but a pattern
# that thin can never support a verdict.
MIN_GROUP_N = 3
# Screening, not proof: a split is worth asking about when chance alone would
# produce it less than this often (two-sided exact test). The verdict comes later
# from episodes recorded after the question, at a much stricter level.
SCREEN_P = 0.25
# Gaps smaller than this are not worth a question even if the sample is large.
MIN_EFFECT = 0.15
# Trades on one day share that day's market move; a group drawn from a single
# session is "that day", not the feature. Each compared group needs this many.
MIN_SESSIONS = 2

# Episode fields that may be grouped on. Each entry is (dimension, extractor path).
# Adding a dimension here is how Atlas gets a wider search space — not by naming a
# conclusion. Bucket edges are fixed in code, never fitted to the sample.
DIMENSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("option_type", ("option_type",)),
    ("underlying_type", ("features", "underlying_type")),
    ("control_action", ("features", "control_action")),
    ("signal", ("features", "signal")),
    ("expected_direction", ("prediction", "expected_direction")),
    ("er_model", ("prediction", "er_model")),
    ("prediction_horizon", ("prediction", "prediction_horizon")),
    ("sma_margin_sign", ("_derived", "sma_margin_sign")),
    ("sma_margin_strength", ("_derived", "sma_margin_strength")),
    ("entry_time_bucket", ("_derived", "entry_time_bucket")),
    ("entry_weekday", ("_derived", "entry_weekday")),
    ("dte_bucket", ("_derived", "dte_bucket")),
    ("iv_bucket", ("_derived", "iv_bucket")),
    ("moneyness_bucket", ("_derived", "moneyness_bucket")),
    ("theta_share_bucket", ("_derived", "theta_share_bucket")),
    ("holding_bucket", ("_derived", "holding_bucket")),
    ("underlier_direction", ("_derived", "underlier_direction")),
)

# Known only after the trade. They describe what happened and may be reported,
# but a hypothesis on them can't be acted on at entry and its test is circular
# (the underlier's direction nearly decides whether the option's call came true).
POST_HOC_DIMENSIONS = frozenset({"holding_bucket", "underlier_direction"})
DECIDE_TIME_DIMENSIONS = tuple(d for d, _ in DIMENSIONS if d not in POST_HOC_DIMENSIONS)

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


def _num(row: dict[str, Any], *path: str) -> float | None:
    try:
        val = _dig(row, path)
        return None if val is None else float(val)
    except (TypeError, ValueError):
        return None


def _bucket(value: float | None, edges: tuple[float, ...], labels: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def _entry_ist(row: dict[str, Any]) -> datetime | None:
    raw = _dig(row, ("fill", "entry_at")) or _dig(row, ("entry", "at"))
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(_IST)


def _entry_time_bucket(row: dict[str, Any]) -> str | None:
    mins = _num(row, "features", "minutes_since_open")
    if mins is None:
        ist = _entry_ist(row)
        if ist is None:
            return None
        mins = (ist.hour * 60 + ist.minute) - (9 * 60 + 15)
    return _bucket(mins, (75.0, 225.0), ("0915_1030", "1030_1300", "1300_close"))


def _entry_weekday(row: dict[str, Any]) -> str | None:
    day = _num(row, "features", "day_of_week")
    if day is None:
        ist = _entry_ist(row)
        if ist is None:
            return None
        day = float(ist.weekday())
    names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    idx = int(day)
    return names[idx] if 0 <= idx < 7 else None


def _theta_share(row: dict[str, Any]) -> float | None:
    theta = _num(row, "features", "theta_per_day")
    premium = _num(row, "fill", "entry_premium") or _num(row, "entry", "price")
    if theta is None or not premium:
        return None
    return abs(theta) / premium


def _derive(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    margin = _num(row, "features", "sma_margin")
    moneyness = _num(row, "features", "moneyness")
    enriched["_derived"] = {
        "holding_bucket": _holding_bucket(row),
        "sma_margin_sign": _sma_margin_sign(row),
        "sma_margin_strength": _bucket(
            None if margin is None else abs(margin), (0.01, 0.03), ("under_1pct", "1_to_3pct", "over_3pct")
        ),
        "entry_time_bucket": _entry_time_bucket(row),
        "entry_weekday": _entry_weekday(row),
        "dte_bucket": _bucket(_num(row, "features", "dte_days"), (3.0, 8.0), ("0_to_2d", "3_to_7d", "8d_plus")),
        "iv_bucket": _bucket(_num(row, "features", "iv"), (0.15, 0.25), ("under_15", "15_to_25", "over_25")),
        "moneyness_bucket": _bucket(
            None if moneyness is None else abs(moneyness), (0.005, 0.02), ("atm", "near", "far")
        ),
        "theta_share_bucket": _bucket(_theta_share(row), (0.05, 0.15), ("under_5pct", "5_to_15pct", "over_15pct")),
        "underlier_direction": _underlier_direction(row),
    }
    return enriched


def confounds_for(rows: list[dict[str, Any]] | None, dimension: str) -> list[str]:
    """Other dimensions that split these episodes exactly as ``dimension`` does."""
    partitions: dict[str, frozenset[frozenset[str]]] = {}
    for dim, path in DIMENSIONS:
        members: dict[str, set[str]] = {}
        for row in rows or []:
            if not isinstance(row, dict) or _outcome_hit(row) is None:
                continue
            value = _dig(_derive(row), path)
            if value in (None, ""):
                continue
            members.setdefault(str(value), set()).add(str(row.get("experience_id") or ""))
        if len(members) >= 2:
            partitions[dim] = frozenset(frozenset(v) for v in members.values())
    mine = partitions.get(dimension)
    return sorted(d for d, part in partitions.items() if d != dimension and part == mine) if mine else []


def dimension_table(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, dict[str, int]]]:
    """Per dimension: {group: {n, hits}} over episodes with a resolved outcome."""
    table: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        hit = _outcome_hit(row)
        if hit is None:
            continue
        enriched = _derive(row)
        for dimension, path in DIMENSIONS:
            value = _dig(enriched, path)
            if value in (None, ""):
                continue
            g = table.setdefault(dimension, {}).setdefault(str(value), {"n": 0, "hits": 0})
            g["n"] += 1
            g["hits"] += 1 if hit else 0
    return table


def session_of(row: dict[str, Any]) -> str:
    """The trading day an episode belongs to."""
    ist = _entry_ist(row)
    return ist.date().isoformat() if ist else str(row.get("as_of_ist") or "")


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
        sessions: dict[str, set[str]] = {}
        for row, hit in usable:
            value = _dig(row, path)
            if value in (None, ""):
                continue
            key = str(value)
            g = groups.setdefault(key, {"n": 0, "hits": 0})
            g["n"] += 1
            g["hits"] += 1 if hit else 0
            members.setdefault(key, []).append(str(row.get("experience_id") or ""))
            sessions.setdefault(key, set()).add(session_of(row))
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
        # Compare groups big enough to carry a rate when there are two of them;
        # otherwise the contrast is recorded as a thin question.
        sized = [kv for kv in rates if detail[kv[0]]["n"] >= min_group_n]
        pool = sized if len(sized) >= 2 else rates
        pool.sort(key=lambda kv: kv[1], reverse=True)
        best, worst = pool[0], pool[-1]
        delta = round(float(best[1]) - float(worst[1]), 4)
        if delta < MIN_EFFECT:
            continue

        thin = [k for k in (best[0], worst[0]) if detail[k]["n"] < min_group_n]
        single_session = [k for k in (best[0], worst[0]) if len(sessions.get(k) or ()) < MIN_SESSIONS]
        thin = sorted(set(thin) | set(single_session))
        p_value = round(
            fisher_exact(
                detail[best[0]]["hits"], detail[best[0]]["n"],
                detail[worst[0]]["hits"], detail[worst[0]]["n"],
            ),
            4,
        )
        if dimension in POST_HOC_DIMENSIONS:
            status = STATUS_POST_HOC
        elif thin:
            status = STATUS_INSUFFICIENT
        else:
            status = STATUS_CANDIDATE
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
                "p_value": p_value,
                "thin_groups": thin,
                "single_session_groups": single_session,
                "group_sessions": {k: len(v) for k, v in sessions.items()},
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

    # The more splits scanned, the more look uneven by chance: a candidate must
    # survive false-discovery control across every sized contrast in this scan.
    tested = [p for p in patterns if p["status"] == STATUS_CANDIDATE]
    survives = benjamini_hochberg([float(p["p_value"]) for p in tested], SCREEN_P)
    kept = [p for p in patterns if p["status"] != STATUS_CANDIDATE]
    for pattern, ok in zip(tested, survives):
        pattern["survives_fdr"] = bool(ok)
        if ok:
            kept.append(pattern)
    patterns = kept

    _mark_confounds(patterns)
    # One cycle asks one question. Spend it on a split this sample can separate.
    # A split tied to other dimensions is the same claim twice, so it ranks behind
    # one that is not; then the least likely to be chance goes first.
    patterns.sort(
        key=lambda p: (
            p["status"] != STATUS_CANDIDATE,
            bool(p.get("confounded_with")),
            float(p.get("p_value") if p.get("p_value") is not None else 1.0),
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
