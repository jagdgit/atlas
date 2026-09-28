"""E002 — volume acceleration only in the high-momentum half of the cross-section.

Prior (E001): unconditional vol accel vs mom/RS for buy_name was worse after costs.
This experiment pre-registers the remaining scientific question:

    Does volume acceleration add information beyond momentum / RS for buy_name
    when momentum is already at or above the cross-sectional median?

Same plugins, same PIT tape as E001 (loaded, not rebuilt when present), same
costs. Walk-forward runs only on the high-momentum rows. Does not touch V1.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.investment.bar_store import load_bars
from atlas.investment.fel.datasets.builder import (
    build_pit_dataset,
    load_pit_dataset,
    persist_pit_dataset,
)
from atlas.investment.fel.experiments.e001_vol_accel import (
    DEFAULT_COSTS,
    E001_ID,
    OBSERVATION_FEATURES,
    filter_momentum_regime,
    month_end_as_ofs,
    select_symbols,
)
from atlas.investment.fel.experiments.runner import run_experiment
from atlas.investment.fel.features.store import persist_feature_registry, record_evaluation
from atlas.investment.fel.models.linear_features import (
    BASELINE_FEATURES,
    BASELINE_MOM_RS_ID,
    CANDIDATE_FEATURES,
    CANDIDATE_MOM_RS_VOL_ID,
)
from atlas.investment.fel.registry import default_fel
from atlas.investment.hypothesis_learning import (
    create_hypothesis,
    get_hypothesis,
    record_verdict,
)
from atlas.investment.laboratory import DEFAULT_SWING_LAB, normalize_laboratory_id

_log = logging.getLogger("atlas.investment.fel.e002")

E002_ID = "E002-buy_name-vol-accel-high-mom"
HYPOTHESIS_ID = "H-buy_name-vol-accel-high-mom"
HYPOTHESIS_STATEMENT = (
    "Volume acceleration adds information beyond momentum and relative strength "
    "for buy_name decisions only when momentum is already at or above the "
    "cross-sectional median."
)
E001_DATASET_ID = "DS-E001-buy_name-vol-accel"
VERSION = "fel.e002.1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verdict_for(result: str) -> str:
    return {
        "improve": "supported",
        "conditional": "partially_supported",
        "no_significant": "inconclusive",
        "worse": "rejected",
        "invalid": "inconclusive",
        "blocked_unavailable": "inconclusive",
    }.get(result, "inconclusive")


def _ensure_hypothesis(data_dir: str, laboratory_id: str) -> dict[str, Any]:
    existing = get_hypothesis(data_dir, HYPOTHESIS_ID, laboratory_id=laboratory_id)
    if existing:
        return existing
    created = create_hypothesis(
        data_dir,
        statement=HYPOTHESIS_STATEMENT,
        domain_tags=["buy_name", "volume", "momentum", "regime", "fel"],
        laboratory_id=laboratory_id,
        transfer_class="strategy",
        linked_experiment_ids=[E001_ID],
        extra={
            "canonical_id": HYPOTHESIS_ID,
            "fel_experiment": E002_ID,
            "parent_experiment": E001_ID,
            "parent_hypothesis": "H-buy_name-vol-accel",
        },
    )
    row = created.get("hypothesis") or {}
    if row and data_dir:
        row = dict(row)
        row["hypothesis_id"] = HYPOTHESIS_ID
        from atlas.investment.hypothesis_learning import store_dir

        root = store_dir(data_dir, laboratory_id=laboratory_id)
        path = root / "by_id" / f"{HYPOTHESIS_ID}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        old_id = (created.get("hypothesis") or {}).get("hypothesis_id")
        if old_id and old_id != HYPOTHESIS_ID:
            old = root / "by_id" / f"{old_id}.json"
            if old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass
    return get_hypothesis(data_dir, HYPOTHESIS_ID, laboratory_id=laboratory_id) or row


def _link_experiment(data_dir: str, laboratory_id: str, experiment_id: str) -> None:
    row = get_hypothesis(data_dir, HYPOTHESIS_ID, laboratory_id=laboratory_id)
    if not row:
        return
    ids = list(row.get("linked_experiment_ids") or [])
    for eid in (E001_ID, experiment_id):
        if eid not in ids:
            ids.append(eid)
    row["linked_experiment_ids"] = ids[-20:]
    row["updated_at"] = _now()
    from atlas.investment.hypothesis_learning import store_dir

    path = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id" / f"{HYPOTHESIS_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


def _load_or_build_parent_dataset(
    root: str,
    *,
    lab: str,
    fel: Any,
    symbol_limit: int | None,
    min_train_months: int,
) -> dict[str, Any]:
    existing = load_pit_dataset(root, E001_DATASET_ID, laboratory_id=lab)
    if existing and (existing.get("rows") or []):
        existing["source"] = "e001_dataset"
        return existing

    symbols = select_symbols(root, limit=symbol_limit)
    if len(symbols) < 2:
        return {"rows": [], "n_rows": 0, "reason": "insufficient_symbols", "n_symbols": len(symbols)}
    bench = load_bars(root, "^NSEI")
    as_ofs = month_end_as_ofs(bench, start="2018-01-01")
    if len(as_ofs) < min_train_months + 3:
        return {"rows": [], "n_rows": 0, "reason": "insufficient_as_of_dates", "n_as_of": len(as_ofs)}
    dataset = build_pit_dataset(
        root,
        symbols=symbols,
        as_of_dates=as_ofs,
        laboratory_id=lab,
        feature_ids=OBSERVATION_FEATURES,
        target_horizon=5,
        benchmark_symbol="^NSEI",
        fel=fel,
    )
    dataset["dataset_id"] = E001_DATASET_ID
    dataset["experiment_id"] = E001_ID
    dataset["source"] = "rebuilt"
    persist_pit_dataset(root, dataset)
    return dataset


def run_e002(
    data_dir: str | Path | None = None,
    *,
    laboratory_id: str | None = None,
    symbol_limit: int | None = None,
    min_train_months: int = 24,
    costs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk-forward vol accel vs mom/RS on the high-momentum PIT slice only."""
    from atlas.config.manager import get_config

    root = str(data_dir or get_config().paths.data)
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    cost_doc = dict(costs or DEFAULT_COSTS)
    fel = default_fel(root)

    parent = _load_or_build_parent_dataset(
        root,
        lab=lab,
        fel=fel,
        symbol_limit=symbol_limit,
        min_train_months=min_train_months,
    )
    if not (parent.get("rows") or []):
        return {
            "experiment_id": E002_ID,
            "result": "invalid",
            "reason": parent.get("reason") or "empty_parent_dataset",
            "promotion": "never",
            "parent_experiment": E001_ID,
        }

    high = filter_momentum_regime(parent, high_momentum=True)
    high["dataset_id"] = f"DS-{E002_ID}"
    high["experiment_id"] = E002_ID
    high["parent_dataset_id"] = parent.get("dataset_id") or E001_DATASET_ID
    high["fold_spec"] = {
        "kind": "expanding_month_end",
        "min_train": int(min_train_months),
        "test_size": 1,
        "as_of_rule": "month_end_session",
        "regime": "high_momentum",
    }
    persist_pit_dataset(root, high)

    if int(high.get("n_rows") or 0) < 8:
        return {
            "experiment_id": E002_ID,
            "result": "invalid",
            "reason": "insufficient_high_momentum_rows",
            "n_rows": high.get("n_rows"),
            "promotion": "never",
            "parent_experiment": E001_ID,
        }

    doc = run_experiment(
        high,
        hypothesis_id=HYPOTHESIS_ID,
        candidate_plugin_id=CANDIDATE_MOM_RS_VOL_ID,
        baseline_plugin_id=BASELINE_MOM_RS_ID,
        decision_type="buy_name",
        data_dir=root,
        costs=cost_doc,
        fel=fel,
        feature_ids=list(CANDIDATE_FEATURES),
        experiment_id=E002_ID,
        params={
            "baseline_features": list(BASELINE_FEATURES),
            "candidate_features": list(CANDIDATE_FEATURES),
            "fold_spec": high["fold_spec"],
            "universe": "nifty50_ready",
            "regime": "high_momentum",
            "momentum_median": high.get("momentum_median"),
            "n_rows": high.get("n_rows"),
            "parent_experiment": E001_ID,
            "parent_dataset": parent.get("dataset_id"),
            "parent_source": parent.get("source"),
        },
        min_train=int(min_train_months),
    )
    shaped = str(doc.get("result") or "invalid")
    note = str(doc.get("reason") or "")
    if shaped == "improve":
        note = "candidate beats baseline in the high-momentum regime after costs"
    elif shaped == "worse":
        note = "volume acceleration still underperforms mom/RS in the high-momentum regime"
    elif shaped == "no_significant":
        note = "no reliable economic edge from volume acceleration in the high-momentum regime"
    doc["result"] = shaped
    doc["reason"] = note
    doc["parent_experiment"] = E001_ID
    doc["regime"] = {
        "name": "high_momentum",
        "n_rows": high.get("n_rows"),
        "momentum_median": high.get("momentum_median"),
        "parent_n_rows": parent.get("n_rows"),
    }
    doc["belief"] = {
        "statement": HYPOTHESIS_STATEMENT,
        "status": shaped,
        "note": note,
        "prior": "E001 rejected unconditional volume acceleration for buy_name",
        "not_a_live_control_change": True,
        "not_an_l5_learning_record": True,
    }
    doc["version"] = VERSION
    from atlas.investment.fel.experiments.store import persist_experiment

    persist_experiment(root, doc)

    gene_status = {
        "improve": "conditional",
        "conditional": "conditional",
        "no_significant": "candidate",
        "worse": "candidate",
        "invalid": "candidate",
    }.get(shaped, "candidate")
    record_evaluation(
        root,
        fel.features,
        "volume_acceleration_20d",
        result=f"e002 high-momentum: {note}",
        not_useful_for=["sell_incumbent"] if shaped in {"conditional", "improve"} else [],
        tested_model=CANDIDATE_MOM_RS_VOL_ID,
        last_evaluated=_now()[:10],
        status=gene_status,  # type: ignore[arg-type]
    )
    persist_feature_registry(root, fel.features)

    hyp = _ensure_hypothesis(root, lab)
    _link_experiment(root, lab, E002_ID)
    try:
        verdict = record_verdict(
            root,
            hypothesis_id=HYPOTHESIS_ID,
            verdict=_verdict_for(shaped),
            laboratory_id=lab,
            evidence_n=max(3, int((doc.get("evaluation") or {}).get("n_folds") or 0)),
            note=note,
            force=True,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("hypothesis verdict failed: %s", exc)
        verdict = {"error": str(exc)}

    doc["hypothesis"] = {
        "hypothesis_id": HYPOTHESIS_ID,
        "status": (verdict.get("hypothesis") or hyp or {}).get("status"),
        "verdict": (verdict.get("hypothesis") or {}).get("verdict"),
    }
    persist_experiment(root, doc)
    return doc
