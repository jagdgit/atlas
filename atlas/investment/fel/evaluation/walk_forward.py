"""Walk-forward evaluator (FEL.3). Expanding folds; costs on the economic metric."""

from __future__ import annotations

from typing import Any

from atlas.investment.fel.contracts import FeatureMatrix, FittedArtifact, ModelPlugin


def expanding_folds(
    as_of_dates: list[str],
    *,
    min_train: int = 2,
    test_size: int = 1,
) -> list[dict[str, list[str]]]:
    dates = sorted({str(d) for d in as_of_dates if d})
    folds: list[dict[str, list[str]]] = []
    i = max(1, int(min_train))
    step = max(1, int(test_size))
    while i < len(dates):
        test = dates[i : i + step]
        if not test:
            break
        folds.append({"train": dates[:i], "test": test})
        i += step
    return folds


def _pairs(preds: list[Any], targets: list[Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p, t in zip(preds, targets):
        try:
            if p is None or t is None:
                continue
            out.append((float(p), float(t)))
        except (TypeError, ValueError):
            continue
    return out


def pearson(preds: list[Any], targets: list[Any]) -> float | None:
    pairs = _pairs(preds, targets)
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p for p, _ in pairs) / n
    my = sum(t for _, t in pairs) / n
    num = sum((p - mx) * (t - my) for p, t in pairs)
    dx = sum((p - mx) ** 2 for p, _ in pairs)
    dy = sum((t - my) ** 2 for _, t in pairs)
    den = (dx * dy) ** 0.5
    if den == 0:
        return None
    return num / den


def long_economic(
    preds: list[Any],
    targets: list[Any],
    *,
    round_trip_cost: float = 0.001,
) -> float | None:
    """Mean target of top-half predictions, minus round-trip cost. None if empty."""
    pairs = _pairs(preds, targets)
    if not pairs:
        return None
    pairs.sort(key=lambda pt: pt[0], reverse=True)
    k = max(1, len(pairs) // 2)
    chosen = pairs[:k]
    mean_t = sum(t for _, t in chosen) / len(chosen)
    return mean_t - float(round_trip_cost or 0.0)


def _as_matrix_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        feats = r.get("features") if isinstance(r.get("features"), dict) else {}
        item.update(feats)
        out.append(item)
    return out


def _predict_scores(plugin: ModelPlugin, artifact: FittedArtifact, rows: list[dict[str, Any]]) -> list[Any]:
    pred = plugin.predict(artifact, FeatureMatrix(rows=rows))
    values = list(pred.values)
    scores: list[Any] = []
    for i, row in enumerate(rows):
        raw = values[i] if i < len(values) else None
        if isinstance(raw, dict):
            scores.append(raw.get("score"))
        else:
            scores.append(raw)
    return scores


def _row_target(row: dict[str, Any]) -> Any:
    t = row.get("target")
    if isinstance(t, dict):
        return t.get("value")
    return t


def evaluate_walk_forward(
    *,
    dataset: dict[str, Any],
    candidate: ModelPlugin,
    baseline: ModelPlugin,
    costs: dict[str, Any] | None = None,
    min_train: int = 2,
) -> dict[str, Any]:
    rows = [r for r in (dataset.get("rows") or []) if isinstance(r, dict)]
    dates = [str(r.get("as_of") or "") for r in rows]
    folds = expanding_folds(dates, min_train=min_train)
    round_trip = float((costs or {}).get("round_trip") or 0.001)
    slippage = float((costs or {}).get("slippage") or 0.0)
    cost = round_trip + slippage
    if not folds:
        return {
            "evaluator_id": "walk_forward",
            "version": "fel.3",
            "result": "invalid",
            "reason": "insufficient_folds",
            "n_folds": 0,
        }

    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        train_set = [r for r in rows if str(r.get("as_of") or "") in set(fold["train"])]
        test_set = [r for r in rows if str(r.get("as_of") or "") in set(fold["test"])]
        if not test_set:
            continue
        train_matrix = FeatureMatrix(rows=_as_matrix_rows(train_set))
        test_rows = _as_matrix_rows(test_set)
        targets = [_row_target(r) for r in test_set]
        train_targets = [_row_target(r) for r in train_set]
        base_art = baseline.fit(train_matrix, train_targets, None)
        cand_art = candidate.fit(train_matrix, train_targets, None)
        if base_art.plugin_id != baseline.plugin_id or cand_art.plugin_id != candidate.plugin_id:
            return {
                "evaluator_id": "walk_forward",
                "result": "invalid",
                "reason": "artifact_identity_mismatch",
            }
        b_scores = _predict_scores(baseline, base_art, test_rows)
        c_scores = _predict_scores(candidate, cand_art, test_rows)
        fold_rows.append(
            {
                "train": fold["train"],
                "test": fold["test"],
                "n": len(test_set),
                "baseline": {
                    "ic": pearson(b_scores, targets),
                    "economic": long_economic(b_scores, targets, round_trip_cost=cost),
                },
                "candidate": {
                    "ic": pearson(c_scores, targets),
                    "economic": long_economic(c_scores, targets, round_trip_cost=cost),
                },
            }
        )

    def _mean(key_path: tuple[str, str]) -> float | None:
        vals = []
        for fr in fold_rows:
            node = fr[key_path[0]][key_path[1]]
            if node is not None:
                vals.append(float(node))
        if not vals:
            return None
        return sum(vals) / len(vals)

    base_econ = _mean(("baseline", "economic"))
    cand_econ = _mean(("candidate", "economic"))
    delta = None if base_econ is None or cand_econ is None else cand_econ - base_econ
    n_pairs = sum(int(fr["n"]) for fr in fold_rows)
    result, reason = _belief_result(delta, n_folds=len(fold_rows), n_pairs=n_pairs)
    return {
        "evaluator_id": "walk_forward",
        "version": "fel.3",
        "result": result,
        "reason": reason,
        "n_folds": len(fold_rows),
        "n_pairs": n_pairs,
        "round_trip_cost": round_trip,
        "slippage": slippage,
        "total_cost": cost,
        "baseline_economic": base_econ,
        "candidate_economic": cand_econ,
        "delta_economic": delta,
        "folds": fold_rows,
    }


def _belief_result(
    delta: float | None, *, n_folds: int, n_pairs: int
) -> tuple[str, str | None]:
    if n_folds < 2 or n_pairs < 6:
        return "invalid", "insufficient_sample"
    if delta is None:
        return "invalid", "metric_undefined"
    if delta > 0.0005:
        return "improve", None
    if delta < -0.0005:
        return "worse", None
    return "no_significant", None
