"""Day-one ModelPlugins wrap existing Atlas methods — registry is real before any new estimator."""

from __future__ import annotations

from typing import Any

from atlas.decision.contracts import DecisionRequest
from atlas.investment.expected_return_prototype import ER_MODEL, compute_prototype_er
from atlas.investment.fel.contracts import FeatureMatrix, FittedArtifact, Predictions
from atlas.investment.ranking import score_universe
from atlas.trading.indicators import rsi as rsi_fn
from atlas.trading.indicators import sma as sma_fn
from atlas.trading.strategy import StrategyDecisionRule


def _artifact(plugin_id: str, version: str, params: dict[str, Any] | None) -> FittedArtifact:
    return FittedArtifact(plugin_id=plugin_id, version=version, params=dict(params or {}))


def _require_identity(artifact: FittedArtifact, plugin_id: str) -> None:
    if artifact.plugin_id != plugin_id:
        raise ValueError(
            f"artifact {artifact.plugin_id} does not match plugin {plugin_id} "
            "(no silent substitution)"
        )


class RulesSmaRsiPlugin:
    """Wrap of ``StrategyDecisionRule`` (live V1 control)."""

    plugin_id = "rules_sma_rsi"
    version = "1.0.0"
    tasks = frozenset({"classification", "ranking"})

    def available(self) -> bool:
        return True

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact:
        del matrix, target
        return _artifact(self.plugin_id, self.version, params)

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions:
        _require_identity(artifact, self.plugin_id)
        rule = StrategyDecisionRule()
        values: list[dict[str, Any]] = []
        params = artifact.params or {}
        fast_p = int(params.get("sma_fast") or 10)
        slow_p = int(params.get("sma_slow") or 30)
        rsi_p = int(params.get("rsi_period") or 14)
        for row in matrix.rows:
            closes = row.get("closes") or []
            if not isinstance(closes, list):
                closes = []
            close_vals: list[float] = []
            for v in closes:
                try:
                    close_vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            price = row.get("price")
            if price is None and close_vals:
                price = close_vals[-1]
            req = DecisionRequest(
                mission_id=None,
                mission_type="paper_trading",
                context={
                    "symbol": str(row.get("symbol") or "X"),
                    "price": price,
                    "position_qty": row.get("position_qty") or 0,
                    "equity": row.get("equity") or 0,
                    "cash": row.get("cash") or 0,
                    "indicators": {
                        "sma_fast": sma_fn(close_vals, fast_p) if close_vals else row.get("sma_fast"),
                        "sma_slow": sma_fn(close_vals, slow_p) if close_vals else row.get("sma_slow"),
                        "rsi": rsi_fn(close_vals, rsi_p) if close_vals else row.get("rsi"),
                        "bars": len(close_vals),
                        "params": {"sma_fast": fast_p, "sma_slow": slow_p},
                    },
                },
            )
            options = rule.score(req, None)  # type: ignore[arg-type]
            top = max(options, key=lambda o: o.score) if options else None
            values.append(
                {
                    "symbol": row.get("symbol"),
                    "action": (top.payload or {}).get("kind") if top else "hold",
                    "score": top.score if top else None,
                    "rationale": top.rationale if top else "no options",
                }
            )
        return Predictions(values=values, extras={"wrap": "StrategyDecisionRule"})

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        del matrix
        return {
            "plugin_id": artifact.plugin_id,
            "kind": "rules",
            "rule": "sma_crossover_rsi",
            "control": True,
        }


class ErPrototypePlugin:
    """Wrap of ``compute_prototype_er`` (LOOP0 L1)."""

    plugin_id = "er_prototype_v1"
    version = "loop0.l1"
    tasks = frozenset({"regression"})

    def available(self) -> bool:
        return True

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact:
        del matrix, target
        return _artifact(self.plugin_id, self.version, params)

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions:
        _require_identity(artifact, self.plugin_id)
        snaps = [compute_prototype_er(row) for row in matrix.rows]
        return Predictions(
            values=[s.get("expected_return") for s in snaps],
            extras={"er_model": ER_MODEL, "snaps": snaps},
        )

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        del matrix
        return {"plugin_id": artifact.plugin_id, "kind": "prototype", "er_model": ER_MODEL}


class RankingV1Plugin:
    """Wrap of ``score_universe`` (IL.3)."""

    plugin_id = "ranking_v1"
    version = "1"
    tasks = frozenset({"ranking"})

    def available(self) -> bool:
        return True

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact:
        del matrix, target
        return _artifact(self.plugin_id, self.version, params)

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions:
        _require_identity(artifact, self.plugin_id)
        bars = matrix.meta.get("bars_by_symbol") if matrix.meta else None
        scored = score_universe(list(matrix.rows), bars_by_symbol=bars)
        return Predictions(
            values=[r.get("score") for r in scored],
            extras={"rows": scored},
        )

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        del matrix
        return {"plugin_id": artifact.plugin_id, "kind": "ranking", "wrap": "score_universe"}
