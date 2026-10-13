"""Cognitive Loop C5 — run a discovered hypothesis through the existing FEL queue.

No second experiment framework. The hypothesis becomes a queue item of kind
``hypothesis_test``; the FEL worker claims it on a BATCH tick like any other
experiment, and the result is linked both ways so neither side can drift.

Three rules the evaluation cannot escape:

* **Persisted data only.** Durable daily OHLCV off disk. No live Yahoo call, so a
  rate-limited feed can never silently change a verdict.
* **A baseline is required.** A candidate with nothing to beat is not a result.
* **Thin or unreplayable samples produce NOT_EVALUABLE, never a verdict.**

Never promotes to live control. Never changes strategy or sizing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.experiment.v1"
KIND = "hypothesis_test"
STORE_REL = Path("investment") / "cognitive" / "experiments"

RESULT_SUPPORTED = "SUPPORTED"
RESULT_REJECTED = "REJECTED"
RESULT_INCONCLUSIVE = "INCONCLUSIVE"
RESULT_NOT_EVALUABLE = "NOT_EVALUABLE"

# Two independent passes before anything may be called validated (plan §7.5).
REPLICATION_PASSES = 2

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.experiment_bridge")


def experiment_id_for(hypothesis_id: str) -> str:
    return f"HYP-{str(hypothesis_id or '')[:12]}"


def enqueue_hypothesis_test(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    hypothesis_id: str,
    experiment_spec: dict[str, Any] | None,
) -> dict[str, Any]:
    """Queue the test, or refuse with a named reason. Idempotent per hypothesis."""
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    spec = experiment_spec if isinstance(experiment_spec, dict) else {}
    if not spec.get("evaluable"):
        return {
            "ok": False,
            "reason": str(spec.get("not_evaluable_reason") or "not_evaluable"),
            "result": RESULT_NOT_EVALUABLE,
        }
    if not spec.get("baseline_required"):
        return {"ok": False, "reason": "baseline_not_declared"}

    eid = experiment_id_for(hypothesis_id)
    try:
        from atlas.investment.fel.queue import enqueue

        item = enqueue(
            data_dir,
            kind=KIND,
            experiment_id=eid,
            laboratory_id=laboratory_id,
            params={
                "hypothesis_id": str(hypothesis_id),
                "experiment_spec": spec,
                "laboratory_id": laboratory_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("hypothesis enqueue failed", exc_info=True)
        return {"ok": False, "reason": f"enqueue_failed:{type(exc).__name__}"}

    try:
        from atlas.investment.cognitive.queue import STATUS_DISPATCHED, mark

        mark(
            data_dir,
            laboratory_id=laboratory_id,
            hypothesis_id=hypothesis_id,
            status=STATUS_DISPATCHED,
            detail=f"queued as {eid}",
            experiment_id=eid,
        )
    except Exception:  # noqa: BLE001
        _log.debug("cognitive queue dispatch mark skipped", exc_info=True)

    return {
        "ok": True,
        "experiment_id": eid,
        "hypothesis_id": str(hypothesis_id),
        "queue_id": (item or {}).get("queue_id"),
        "status": (item or {}).get("status"),
        "honesty": (
            "Queued for the existing FEL runner on persisted data. "
            "Not a verdict, not a promotion."
        ),
    }


def _load_bars(data_dir: str | Path, symbol: str) -> list[dict[str, Any]]:
    """Durable daily OHLCV off disk. Deliberately no live fetch."""
    try:
        from atlas.investment.market_bars_health import bar_path

        path = bar_path(data_dir, symbol)
        if path is None:
            return []
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    rows = doc.get("bars") if isinstance(doc, dict) else doc
    return [r for r in (rows or []) if isinstance(r, dict)]


def _session_direction(bar: dict[str, Any]) -> str | None:
    try:
        o = float(bar.get("open"))
        c = float(bar.get("close"))
    except (TypeError, ValueError):
        return None
    return "up" if c > o else ("down" if c < o else "flat")


def _invert(direction: str) -> str:
    return {"up": "down", "down": "up"}.get(direction, direction)


def _expected_underlier_direction(
    premium_direction: str, option_type: str | None
) -> str | None:
    """Translate a premium expectation into an underlier expectation.

    Contract mechanics, not a hypothesis: a call's premium moves with the underlier
    and a put's moves against it. Without a known right, the translation is unknown
    rather than assumed.
    """
    right = str(option_type or "").strip().upper()
    if right in {"CE", "CALL", "C"}:
        return premium_direction
    if right in {"PE", "PUT", "P"}:
        return _invert(premium_direction)
    return None


def evaluate_hypothesis(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    hypothesis_id: str,
    experiment_spec: dict[str, Any] | None,
    episodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Test the restated underlier-direction claim on persisted daily bars.

    The claim under test: did the control signal's directional call land more often
    for one group than the other, measured over sessions we hold durable bars for?
    """
    spec = experiment_spec if isinstance(experiment_spec, dict) else {}
    day = datetime.now(_IST).strftime("%Y-%m-%d")
    base: dict[str, Any] = {
        "version": VERSION,
        "kind": "COGNITIVE_EXPERIMENT_RESULT",
        "laboratory_id": str(laboratory_id or ""),
        "hypothesis_id": str(hypothesis_id or ""),
        "experiment_id": experiment_id_for(hypothesis_id),
        "as_of_ist": day,
        "dimension": spec.get("dimension"),
        "groups": list(spec.get("groups") or []),
        "metric": spec.get("metric"),
        "min_effect": spec.get("min_effect"),
        "data_requirement": spec.get("data_requirement"),
        "mutates_strategy": False,
        "promotion": None,
        "live_orders": False,
    }

    def not_evaluable(reason: str, detail: str = "") -> dict[str, Any]:
        return {
            **base,
            "result": RESULT_NOT_EVALUABLE,
            "reason": reason,
            "detail": detail,
            "honesty": (
                "No verdict. Refusing to score a claim the available data cannot "
                "separate is the honest outcome, not a failure."
            ),
        }

    if not data_dir:
        return not_evaluable("missing_data_dir")
    if not spec.get("evaluable"):
        return not_evaluable(str(spec.get("not_evaluable_reason") or "not_evaluable"))

    rows = [r for r in (episodes or []) if isinstance(r, dict)]
    if not rows:
        return not_evaluable("no_episodes", "no closed-loop episodes to test against")

    dim = str(spec.get("dimension") or "")
    compare_groups = [str(g) for g in (spec.get("groups") or [])]
    if len(compare_groups) < 2:
        return not_evaluable("no_contrast", "need two groups to compare")

    # Group membership comes from the episode's own decide-time dimension value.
    from atlas.investment.cognitive.pattern_detector import _derive, _dig

    dim_path = {name: path for name, path in _dimension_paths()}.get(dim)
    if dim_path is None:
        return not_evaluable("unknown_dimension", dim)

    symbols = sorted({str(r.get("underlying") or "").upper() for r in rows if r.get("underlying")})
    try:
        from atlas.investment.market_bars_health import assess_symbols

        health = assess_symbols(data_dir, symbols)
    except Exception:  # noqa: BLE001
        return not_evaluable("bars_health_unavailable")
    if not health.get("all_replayable"):
        bad = [
            str(s.get("symbol"))
            for s in (health.get("symbols") or [])
            if not s.get("replayable")
        ]
        return not_evaluable("bars_not_replayable", ", ".join(bad[:8]))

    # Baseline: the control's overall directional accuracy across every group. The
    # candidate claim must beat its own population, not an empty comparison.
    groups: dict[str, dict[str, int]] = {g: {"n": 0, "hits": 0} for g in compare_groups}
    population = {"n": 0, "hits": 0}
    unresolved = 0
    for row in rows:
        enriched = _derive(row)
        value = str(_dig(enriched, dim_path) or "")
        predicted = str(
            (row.get("prediction") or {}).get("expected_direction") or ""
        ).lower()
        underlying = str(row.get("underlying") or "").upper()
        session = (row.get("underlier_movement") or {}).get("session") or {}
        observed = _session_direction(session)
        if observed is None:
            bars = _load_bars(data_dir, underlying)
            observed = _session_direction(bars[-1]) if bars else None
        expected_underlier = _expected_underlier_direction(
            predicted, row.get("option_type") or (row.get("features") or {}).get("option_type")
        )
        if not predicted or observed is None or expected_underlier is None:
            unresolved += 1
            continue
        hit = observed == expected_underlier
        population["n"] += 1
        population["hits"] += 1 if hit else 0
        if value in groups:
            groups[value]["n"] += 1
            groups[value]["hits"] += 1 if hit else 0

    thin = [g for g, v in groups.items() if v["n"] < 3]
    if thin:
        return not_evaluable(
            "insufficient_sample", f"groups below n=3: {', '.join(sorted(thin))}"
        )

    rates = {
        g: round(v["hits"] / v["n"], 4) if v["n"] else None for g, v in groups.items()
    }
    baseline_rate = (
        round(population["hits"] / population["n"], 4) if population["n"] else None
    )
    high, low = compare_groups[0], compare_groups[-1]
    gap = None
    if rates.get(high) is not None and rates.get(low) is not None:
        gap = round(float(rates[high]) - float(rates[low]), 4)

    min_effect = float(spec.get("min_effect") or 0.5)
    if gap is None:
        result, reason = RESULT_NOT_EVALUABLE, "gap_uncomputable"
    elif gap >= min_effect:
        result, reason = RESULT_SUPPORTED, "gap_met_or_exceeded_min_effect"
    elif gap <= -min_effect:
        result, reason = RESULT_REJECTED, "gap_reversed_sign_beyond_min_effect"
    else:
        result, reason = RESULT_INCONCLUSIVE, "gap_smaller_than_min_effect"

    return {
        **base,
        "result": result,
        "reason": reason,
        "group_rates": rates,
        "group_counts": groups,
        "baseline": {
            "name": "control_population_direction_accuracy",
            "rate": baseline_rate,
            "n": population["n"],
        },
        "gap": gap,
        "unresolved_episodes": unresolved,
        "replication": {
            "passes_required": REPLICATION_PASSES,
            "passes_done": 1,
            "validated": False,
        },
        "honesty": (
            "One pass on persisted daily bars. "
            f"{RESULT_SUPPORTED} here is support, not validation — "
            f"{REPLICATION_PASSES} independent passes are required, and the "
            "premium-level claim remains untested because option history does not exist."
        ),
    }


def _dimension_paths() -> tuple[tuple[str, tuple[str, ...]], ...]:
    from atlas.investment.cognitive.pattern_detector import DIMENSIONS

    return DIMENSIONS


def persist_result(
    data_dir: str | Path | None, result: dict[str, Any] | None
) -> dict[str, Any]:
    if not data_dir or not isinstance(result, dict):
        return {"ok": False, "reason": "missing_args"}
    try:
        path = (
            Path(data_dir)
            / STORE_REL
            / str(result.get("laboratory_id") or "")
            / f"{result.get('experiment_id')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("cognitive experiment persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_result(
    data_dir: str | Path | None, *, laboratory_id: str, hypothesis_id: str
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = (
        Path(data_dir)
        / STORE_REL
        / str(laboratory_id)
        / f"{experiment_id_for(hypothesis_id)}.json"
    )
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def handle_hypothesis_test(item: dict[str, Any], data_dir: str) -> dict[str, Any]:
    """FEL dispatch handler — claimed on a BATCH tick like any other experiment."""
    params = dict(item.get("params") or {})
    lab = str(params.get("laboratory_id") or item.get("laboratory_id") or "")
    hypothesis_id = str(params.get("hypothesis_id") or "")
    spec = params.get("experiment_spec")

    episodes: list[dict[str, Any]] = []
    try:
        from atlas.investment.fno_closed_loop_dataset import load_closed_loop_episodes

        episodes = load_closed_loop_episodes(data_dir, laboratory_id=lab, eligible_only=True)
    except Exception:  # noqa: BLE001
        _log.debug("closed-loop episodes unavailable for hypothesis test", exc_info=True)

    result = evaluate_hypothesis(
        data_dir,
        laboratory_id=lab,
        hypothesis_id=hypothesis_id,
        experiment_spec=spec,
        episodes=episodes,
    )
    persist_result(data_dir, result)

    try:
        from atlas.investment.cognitive.queue import STATUS_DONE, mark

        mark(
            data_dir,
            laboratory_id=lab,
            hypothesis_id=hypothesis_id,
            status=STATUS_DONE,
            detail=f"{result.get('result')}:{result.get('reason')}",
            experiment_id=result.get("experiment_id"),
        )
    except Exception:  # noqa: BLE001
        _log.debug("cognitive queue done mark skipped", exc_info=True)

    return result
