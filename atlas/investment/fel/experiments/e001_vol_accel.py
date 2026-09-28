"""E001 — first honest FEL experiment (deterministic, no LLM).

Question: does volume acceleration add information beyond momentum / RS for buy_name?

Baseline:  lin_mom_rs              = momentum + rs_vs_benchmark
Candidate: lin_mom_rs_volaccel     = momentum + rs_vs_benchmark + volume_acceleration_20d

Does not touch live V1 fills. Promotion never live_control.
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
    persist_pit_dataset,
)
from atlas.investment.fel.evaluation.walk_forward import evaluate_walk_forward
from atlas.investment.fel.experiments.runner import run_experiment
from atlas.investment.fel.features.store import (
    persist_feature_registry,
    record_evaluation,
)
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

_log = logging.getLogger("atlas.investment.fel.e001")

E001_ID = "E001-buy_name-vol-accel"
HYPOTHESIS_ID = "H-buy_name-vol-accel"
HYPOTHESIS_STATEMENT = (
    "Unusual participation (volume acceleration) adds information beyond "
    "momentum and relative strength for buy_name decisions."
)
OBSERVATION_FEATURES = list(CANDIDATE_FEATURES)
DEFAULT_COSTS = {"round_trip": 0.001, "slippage": 0.0005}  # 10 bps + 5 bps
VERSION = "fel.e001.1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def month_end_as_ofs(
    bars: list[dict[str, Any]],
    *,
    start: str = "2018-01-01",
    end: str | None = None,
    leave_tail_days: int = 10,
) -> list[str]:
    """Last available session date per YYYY-MM, within [start, end], with tail room for fwd ret."""
    if end is None:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_ym: dict[str, str] = {}
    for bar in bars:
        day = str(bar.get("date") or "")
        if not day or day < start or day > end:
            continue
        by_ym[day[:7]] = day
    dates = sorted(by_ym.values())
    if leave_tail_days > 0 and dates:
        # Drop final months that cannot form fwd_ret_5d against the bar tape.
        cutoff = dates[-1]
        # Keep dates that still have later bars in the source series.
        all_days = sorted(str(b.get("date") or "") for b in bars if b.get("date"))
        kept: list[str] = []
        for d in dates:
            try:
                idx = all_days.index(d)
            except ValueError:
                continue
            if idx + leave_tail_days < len(all_days):
                kept.append(d)
        return kept
    return dates


def select_symbols(
    data_dir: str | Path,
    *,
    membership: list[str] | None = None,
    min_bars: int = 400,
    limit: int | None = None,
) -> list[str]:
    if membership is None:
        from atlas.investment import universe

        membership = list(universe.symbols(universe.INDEX_NIFTY50) or [])
    out: list[str] = []
    for sym in membership:
        bars = load_bars(data_dir, sym)
        if len(bars) >= int(min_bars):
            out.append(sym)
        if limit and len(out) >= int(limit):
            break
    return out


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def filter_momentum_regime(dataset: dict[str, Any], *, high_momentum: bool) -> dict[str, Any]:
    rows = [r for r in (dataset.get("rows") or []) if isinstance(r, dict)]
    moms = []
    for r in rows:
        feats = r.get("features") if isinstance(r.get("features"), dict) else {}
        try:
            if feats.get("momentum") is not None:
                moms.append(float(feats["momentum"]))
        except (TypeError, ValueError):
            continue
    med = _median(moms)
    if med is None:
        return {**dataset, "rows": [], "n_rows": 0, "regime": "empty"}
    kept = []
    for r in rows:
        feats = r.get("features") if isinstance(r.get("features"), dict) else {}
        try:
            m = float(feats["momentum"])
        except (TypeError, ValueError, KeyError):
            continue
        if high_momentum and m >= med:
            kept.append(r)
        elif not high_momentum and m < med:
            kept.append(r)
    return {
        **dataset,
        "rows": kept,
        "n_rows": len(kept),
        "regime": "high_momentum" if high_momentum else "low_momentum",
        "momentum_median": med,
    }


def _belief_shape(
    overall: str,
    *,
    high: str | None,
    low: str | None,
) -> tuple[str, str]:
    """Map numeric outcomes into belief-shaped language (not an L5 record)."""
    if overall == "invalid":
        return "invalid", "insufficient or undefined metric"
    if overall == "improve" and high == "improve" and low == "improve":
        return "improve", "candidate beats baseline across momentum regimes"
    if overall == "improve" and high == "improve" and low != "improve":
        return "conditional", "useful mainly in high-momentum regimes"
    if overall == "improve" and low == "improve" and high != "improve":
        return "conditional", "useful mainly in low-momentum regimes"
    if high == "improve" and overall in {"no_significant", "worse"}:
        return "conditional", "overall weak; high-momentum slice improves"
    if overall == "worse":
        return "worse", "candidate underperforms baseline after costs"
    if overall == "no_significant":
        return "no_significant", "no reliable economic edge after costs"
    return overall, "see evaluation"


def _ensure_hypothesis(data_dir: str, laboratory_id: str) -> dict[str, Any]:
    existing = get_hypothesis(data_dir, HYPOTHESIS_ID, laboratory_id=laboratory_id)
    if existing:
        return existing
    created = create_hypothesis(
        data_dir,
        statement=HYPOTHESIS_STATEMENT,
        domain_tags=["buy_name", "volume", "momentum", "fel"],
        laboratory_id=laboratory_id,
        transfer_class="strategy",
        linked_experiment_ids=[],
        extra={"canonical_id": HYPOTHESIS_ID, "fel_experiment": E001_ID},
    )
    row = created.get("hypothesis") or {}
    # Rewrite under the stable scientific id so genealogy links stay fixed.
    if row and data_dir:
        row = dict(row)
        row["hypothesis_id"] = HYPOTHESIS_ID
        from atlas.investment.hypothesis_learning import store_dir

        root = store_dir(data_dir, laboratory_id=laboratory_id)
        path = root / "by_id" / f"{HYPOTHESIS_ID}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        # Remove uuid copy if different
        old = root / "by_id" / f"{created['hypothesis']['hypothesis_id']}.json"
        if old != path and old.is_file():
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
    if experiment_id not in ids:
        ids.append(experiment_id)
    row["linked_experiment_ids"] = ids[-20:]
    row["updated_at"] = _now()
    from atlas.investment.hypothesis_learning import store_dir

    path = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id" / f"{HYPOTHESIS_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


def _verdict_for(result: str) -> str:
    return {
        "improve": "supported",
        "conditional": "partially_supported",
        "no_significant": "inconclusive",
        "worse": "rejected",
        "invalid": "inconclusive",
        "blocked_unavailable": "inconclusive",
    }.get(result, "inconclusive")


def run_e001(
    data_dir: str | Path | None = None,
    *,
    laboratory_id: str | None = None,
    symbol_limit: int | None = None,
    min_train_months: int = 24,
    costs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build PIT → walk-forward baseline vs candidate → genealogy → hypothesis verdict."""
    from atlas.config.manager import get_config

    root = str(data_dir or get_config().paths.data)
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    cost_doc = dict(costs or DEFAULT_COSTS)
    fel = default_fel(root)

    symbols = select_symbols(root, limit=symbol_limit)
    if len(symbols) < 2:
        return {
            "experiment_id": E001_ID,
            "result": "invalid",
            "reason": "insufficient_symbols",
            "n_symbols": len(symbols),
            "promotion": "never",
        }

    bench = load_bars(root, "^NSEI")
    as_ofs = month_end_as_ofs(bench, start="2018-01-01")
    if len(as_ofs) < min_train_months + 3:
        return {
            "experiment_id": E001_ID,
            "result": "invalid",
            "reason": "insufficient_as_of_dates",
            "n_as_of": len(as_ofs),
            "promotion": "never",
        }

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
    dataset["dataset_id"] = f"DS-{E001_ID}"
    dataset["experiment_id"] = E001_ID
    dataset["fold_spec"] = {
        "kind": "expanding_month_end",
        "min_train": int(min_train_months),
        "test_size": 1,
        "as_of_rule": "month_end_session",
    }
    persist_pit_dataset(root, dataset)

    doc = run_experiment(
        dataset,
        hypothesis_id=HYPOTHESIS_ID,
        candidate_plugin_id=CANDIDATE_MOM_RS_VOL_ID,
        baseline_plugin_id=BASELINE_MOM_RS_ID,
        decision_type="buy_name",
        data_dir=root,
        costs=cost_doc,
        fel=fel,
        feature_ids=list(CANDIDATE_FEATURES),
        experiment_id=E001_ID,
        params={
            "baseline_features": list(BASELINE_FEATURES),
            "candidate_features": list(CANDIDATE_FEATURES),
            "fold_spec": dataset["fold_spec"],
            "universe": "nifty50_ready",
            "n_symbols": len(symbols),
            "n_as_of": len(as_ofs),
        },
        min_train=int(min_train_months),
    )

    # Regime / stability slices (same plugins, filtered rows).
    high = filter_momentum_regime(dataset, high_momentum=True)
    low = filter_momentum_regime(dataset, high_momentum=False)
    cand = fel.models.require(CANDIDATE_MOM_RS_VOL_ID)
    base = fel.models.require(BASELINE_MOM_RS_ID)
    high_eval = (
        evaluate_walk_forward(
            dataset=high, candidate=cand, baseline=base, costs=cost_doc, min_train=max(6, min_train_months // 2)
        )
        if high.get("n_rows")
        else {"result": "invalid", "reason": "empty_regime"}
    )
    low_eval = (
        evaluate_walk_forward(
            dataset=low, candidate=cand, baseline=base, costs=cost_doc, min_train=max(6, min_train_months // 2)
        )
        if low.get("n_rows")
        else {"result": "invalid", "reason": "empty_regime"}
    )
    shaped, note = _belief_shape(
        str(doc.get("result")),
        high=str(high_eval.get("result")),
        low=str(low_eval.get("result")),
    )
    doc["result"] = shaped
    doc["reason"] = note
    doc["regimes"] = {
        "high_momentum": {
            "n_rows": high.get("n_rows"),
            "momentum_median": high.get("momentum_median"),
            "evaluation": {
                k: high_eval.get(k)
                for k in (
                    "result",
                    "reason",
                    "n_folds",
                    "n_pairs",
                    "baseline_economic",
                    "candidate_economic",
                    "delta_economic",
                )
            },
        },
        "low_momentum": {
            "n_rows": low.get("n_rows"),
            "momentum_median": low.get("momentum_median"),
            "evaluation": {
                k: low_eval.get(k)
                for k in (
                    "result",
                    "reason",
                    "n_folds",
                    "n_pairs",
                    "baseline_economic",
                    "candidate_economic",
                    "delta_economic",
                )
            },
        },
    }
    doc["belief"] = {
        "statement": HYPOTHESIS_STATEMENT,
        "status": shaped,
        "note": note,
        "not_a_live_control_change": True,
        "not_an_l5_learning_record": True,
    }
    doc["version"] = VERSION
    from atlas.investment.fel.experiments.store import persist_experiment

    persist_experiment(root, doc)

    # Genealogy update on the candidate feature row.
    gene_status = {
        "improve": "conditional",  # still not promoted into the live decision model
        "conditional": "conditional",
        "no_significant": "candidate",
        "worse": "candidate",
        "invalid": "candidate",
    }.get(shaped, "candidate")
    record_evaluation(
        root,
        fel.features,
        "volume_acceleration_20d",
        result=note,
        not_useful_for=["sell_incumbent"] if shaped in {"conditional", "improve"} else [],
        tested_model=CANDIDATE_MOM_RS_VOL_ID,
        last_evaluated=_now()[:10],
        status=gene_status,  # type: ignore[arg-type]
    )
    persist_feature_registry(root, fel.features)

    hyp = _ensure_hypothesis(root, lab)
    _link_experiment(root, lab, E001_ID)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    out = run_e001()
    summary = {
        "experiment_id": out.get("experiment_id"),
        "result": out.get("result"),
        "reason": out.get("reason"),
        "promotion": out.get("promotion"),
        "dataset_id": out.get("dataset_id"),
        "baseline_plugin_id": out.get("baseline_plugin_id"),
        "model_plugin_id": out.get("model_plugin_id"),
        "belief": out.get("belief"),
        "hypothesis": out.get("hypothesis"),
        "evaluation": {
            k: (out.get("evaluation") or {}).get(k)
            for k in (
                "n_folds",
                "n_pairs",
                "baseline_economic",
                "candidate_economic",
                "delta_economic",
                "total_cost",
            )
        },
        "regimes": out.get("regimes"),
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
