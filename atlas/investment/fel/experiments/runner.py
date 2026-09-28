"""FEL.3 experiment runner — baseline required, no silent swap, no live promotion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from atlas.investment.fel.contracts import FEL_VERSION
from atlas.investment.fel.datasets.builder import assert_lab_hermetic
from atlas.investment.fel.experiments.store import persist_experiment
from atlas.investment.fel.promotion import promotion_for
from atlas.investment.fel.registry import FelRegistries, default_fel
from atlas.investment.laboratory import DEFAULT_SWING_LAB, normalize_laboratory_id

VERSION = "fel.3.runner"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_experiment(
    dataset: dict[str, Any],
    *,
    hypothesis_id: str,
    candidate_plugin_id: str,
    baseline_plugin_id: str,
    decision_type: str = "buy_name",
    data_dir: str | None = None,
    costs: dict[str, Any] | None = None,
    fel: FelRegistries | None = None,
    feature_ids: list[str] | None = None,
    experiment_id: str | None = None,
    params: dict[str, Any] | None = None,
    min_train: int = 2,
) -> dict[str, Any]:
    eid = str(experiment_id or uuid4())
    if not baseline_plugin_id:
        return {
            "experiment_id": eid,
            "result": "invalid",
            "reason": "baseline_required",
            "promotion": "never",
            "ran": None,
        }
    lab = normalize_laboratory_id(
        laboratory_id=(dataset.get("laboratory_id") if dataset else None) or DEFAULT_SWING_LAB
    )
    if dataset:
        assert_lab_hermetic(dataset)
    bundle = fel or default_fel()
    candidate, cand_err = bundle.models.resolve(candidate_plugin_id)
    if cand_err:
        cand_err["experiment_id"] = eid
        cand_err["baseline_plugin_id"] = baseline_plugin_id
        cand_err["promotion"] = "never"
        return cand_err
    baseline, base_err = bundle.models.resolve(baseline_plugin_id)
    if base_err:
        base_err["experiment_id"] = eid
        base_err["promotion"] = "never"
        return base_err

    evaluator, ev_err = bundle.evaluators.resolve("walk_forward")
    if ev_err:
        ev_err["experiment_id"] = eid
        ev_err["promotion"] = "never"
        return ev_err

    cost_doc = dict(costs or {"round_trip": 0.001, "slippage": 0.0})
    evaluation = evaluator.evaluate(
        dataset=dataset,
        candidate=candidate,
        baseline=baseline,
        costs=cost_doc,
        min_train=int(min_train),
    )
    result = str(evaluation.get("result") or "invalid")
    doc = {
        "experiment_id": eid,
        "version": VERSION,
        "fel_version": FEL_VERSION,
        "hypothesis_id": hypothesis_id,
        "decision_type": decision_type,
        "laboratory_id": lab,
        "dataset_id": dataset.get("dataset_id") if dataset else None,
        "feature_ids": list(feature_ids or dataset.get("feature_ids") or []),
        "model_plugin_id": candidate.plugin_id,
        "model_version": candidate.version,
        "baseline_plugin_id": baseline.plugin_id,
        "baseline_version": baseline.version,
        "evaluator": "walk_forward",
        "params": dict(params or {}),
        "fold_spec": (params or {}).get("fold_spec") or (dataset or {}).get("fold_spec"),
        "costs": cost_doc,
        "evaluation": evaluation,
        "result": result,
        "reason": evaluation.get("reason"),
        "promotion": promotion_for(result=result),
        "ran": {
            "candidate": candidate.plugin_id,
            "baseline": baseline.plugin_id,
        },
        "created_at": _now(),
        "note": (
            "Belief-shaped outcome for the Scientist; not an L5 learning record "
            "and not a live-control change."
        ),
    }
    persist_experiment(data_dir, doc)
    return doc
