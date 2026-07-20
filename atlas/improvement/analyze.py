"""Analyze hermetic baseline reports for regressions / floor breaches (Phase D · §D.10)."""

from __future__ import annotations

from typing import Any

# Default absolute floors for known aggregate metrics (hermetic baseline is high-quality;
# floors are deliberately lenient so a healthy suite does not constantly alert).
DEFAULT_FLOORS: dict[str, float] = {
    "retrieval_hermetic.precision_at_k": 0.5,
    "retrieval_hermetic.recall_at_k": 0.5,
    "synthesis_duplicates.merge_accuracy": 0.5,
    "synthesis_contradictions.contradiction_recall": 0.3,
    "freshness.freshness_label_accuracy": 0.5,
    "supersession.supersession_correctness": 0.5,
    "provenance.provenance_completeness": 0.5,
}

# Metrics where lower is better (a rise is a regression).
_LOWER_IS_BETTER = frozenset({
    "synthesis_duplicates.false_merge_rate",
    "synthesis_contradictions.false_merge_rate",
})


def flatten_metrics(sections: dict[str, Any]) -> dict[str, float]:
    """Flatten BaselineReport.sections into ``section.metric → float`` scores."""
    out: dict[str, float] = {}
    for section, payload in (sections or {}).items():
        if section == "notes" or not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and key not in ("n_cases", "n_problems", "k"):
                out[f"{section}.{key}"] = float(value)
    return out


def analyze_baseline(
    current: dict[str, float],
    *,
    previous: dict[str, float] | None = None,
    floors: dict[str, float] | None = None,
    regression_drop: float = 0.05,
) -> list[dict[str, Any]]:
    """Return finding dicts for floor breaches and regressions vs the previous run.

    Each finding: ``{id, metric, kind, current, previous, floor, delta, severity}``.
    """
    floors = {**DEFAULT_FLOORS, **(floors or {})}
    previous = previous or {}
    findings: list[dict[str, Any]] = []

    for metric, value in sorted(current.items()):
        floor = floors.get(metric)
        prev = previous.get(metric)
        lower_better = metric in _LOWER_IS_BETTER

        if floor is not None:
            breached = value > floor if lower_better else value < floor
            if breached:
                findings.append({
                    "id": f"floor:{metric}",
                    "metric": metric,
                    "kind": "below_floor" if not lower_better else "above_ceiling",
                    "current": value,
                    "previous": prev,
                    "floor": floor,
                    "delta": (value - prev) if prev is not None else None,
                    "severity": "high" if abs(value - floor) >= 0.2 else "medium",
                })

        if prev is not None and regression_drop > 0:
            if lower_better:
                delta = value - prev
                regressed = delta >= regression_drop
            else:
                delta = prev - value
                regressed = delta >= regression_drop
            if regressed:
                findings.append({
                    "id": f"regression:{metric}",
                    "metric": metric,
                    "kind": "regression",
                    "current": value,
                    "previous": prev,
                    "floor": floor,
                    "delta": (value - prev),
                    "severity": "high" if abs(value - prev) >= 0.15 else "medium",
                })

    # Deduplicate by id (floor + regression on same metric can both fire — keep both).
    return findings
