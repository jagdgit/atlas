"""Four independent FEL registries — feature, model, evaluator, target.

Adding a model never edits the feature engine. Switching the active predictor is
a promotion record, not a code fork. Plugins are never deleted; retire is status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from atlas.investment.fel.contracts import (
    FEL_VERSION,
    BlockedUnavailable,
    EvaluatorPlugin,
    FeatureComputer,
    ModelPlugin,
    PluginStatus,
    TargetSpec,
)

T = TypeVar("T")


@dataclass
class RegistryRecord(Generic[T]):
    plugin_id: str
    version: str
    plugin: T
    status: PluginStatus = "active"
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.plugin_id}@{self.version}"


class PluginRegistry(Generic[T]):
    """Identity-keyed registry. Same id@version cannot be replaced by a different object."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, RegistryRecord[T]] = {}

    def register(
        self,
        plugin: T,
        *,
        plugin_id: str,
        version: str,
        status: PluginStatus = "active",
        notes: str = "",
        extra: dict[str, Any] | None = None,
    ) -> RegistryRecord[T]:
        key = f"{plugin_id}@{version}"
        existing = self._items.get(key)
        if existing is not None:
            if existing.plugin is plugin:
                return existing
            raise ValueError(f"{self.kind} already registered: {key}")
        rec = RegistryRecord(
            plugin_id=plugin_id,
            version=version,
            plugin=plugin,
            status=status,
            notes=notes,
            extra=dict(extra or {}),
        )
        self._items[key] = rec
        return rec

    def get(self, plugin_id: str, version: str | None = None) -> RegistryRecord[T] | None:
        if version:
            return self._items.get(f"{plugin_id}@{version}")
        matches = [r for r in self._items.values() if r.plugin_id == plugin_id]
        if not matches:
            return None
        active = [r for r in matches if r.status != "retired"]
        pool = active or matches
        pool.sort(key=lambda r: r.version, reverse=True)
        return pool[0]

    def require(self, plugin_id: str, version: str | None = None) -> T:
        rec = self.get(plugin_id, version)
        if rec is None:
            raise BlockedUnavailable(plugin_id, reason="not_registered", requested=plugin_id)
        if rec.status == "retired":
            raise BlockedUnavailable(plugin_id, reason="retired", requested=plugin_id)
        available = getattr(rec.plugin, "available", None)
        if callable(available) and not bool(available()):
            raise BlockedUnavailable(plugin_id, reason="available_false", requested=plugin_id)
        return rec.plugin

    def resolve(self, plugin_id: str, version: str | None = None) -> tuple[T | None, dict[str, Any] | None]:
        """Return (plugin, None) or (None, blocked_unavailable result). Never substitutes."""
        try:
            return self.require(plugin_id, version), None
        except BlockedUnavailable as exc:
            return None, exc.as_result()

    def retire(self, plugin_id: str, version: str | None = None) -> bool:
        rec = self.get(plugin_id, version)
        if rec is None:
            return False
        rec.status = "retired"
        return True

    def list(self, *, include_retired: bool = True) -> list[RegistryRecord[T]]:
        rows = list(self._items.values())
        if not include_retired:
            rows = [r for r in rows if r.status != "retired"]
        return rows

    def ids(self) -> list[str]:
        return sorted({r.plugin_id for r in self._items.values()})

    def __contains__(self, plugin_id: str) -> bool:
        return any(r.plugin_id == plugin_id for r in self._items.values())

    def __len__(self) -> int:
        return len(self._items)


class FeatureRegistry(PluginRegistry[FeatureComputer]):
    def __init__(self) -> None:
        super().__init__("feature")

    def register_computer(self, computer: FeatureComputer, **kw: Any) -> RegistryRecord[FeatureComputer]:
        extra = dict(kw.pop("extra", None) or {})
        extra.setdefault("origin", getattr(computer, "origin", "fel0_seed"))
        extra.setdefault("hypothesis_id", getattr(computer, "hypothesis_id", None))
        extra.setdefault("scientist_reason", getattr(computer, "scientist_reason", ""))
        extra.setdefault("tested_for", getattr(computer, "tested_for", ()))
        extra.setdefault("derived_from", getattr(computer, "derived_from", ()))
        extra.setdefault("source_concepts", getattr(computer, "source_concepts", ()))
        extra.setdefault("formula", getattr(computer, "formula", ""))
        extra.setdefault("availability_time", getattr(computer, "availability_time", "session_close"))
        extra.setdefault("status", getattr(computer, "status", "registered"))
        extra.setdefault("lesson_eligible", getattr(computer, "lesson_eligible", False))
        return self.register(
            computer,
            plugin_id=computer.feature_id,
            version=computer.version,
            extra=extra,
            **kw,
        )


class ModelRegistry(PluginRegistry[ModelPlugin]):
    def __init__(self) -> None:
        super().__init__("model")

    def register_plugin(self, plugin: ModelPlugin, **kw: Any) -> RegistryRecord[ModelPlugin]:
        status: PluginStatus = kw.pop("status", "active")
        if not plugin.available():
            status = kw.pop("forced_status", "reserved")
        return self.register(
            plugin,
            plugin_id=plugin.plugin_id,
            version=plugin.version,
            status=status,
            **kw,
        )


class EvaluatorRegistry(PluginRegistry[EvaluatorPlugin]):
    def __init__(self) -> None:
        super().__init__("evaluator")

    def register_plugin(self, plugin: EvaluatorPlugin, **kw: Any) -> RegistryRecord[EvaluatorPlugin]:
        return self.register(
            plugin,
            plugin_id=plugin.evaluator_id,
            version=plugin.version,
            **kw,
        )


class TargetRegistry(PluginRegistry[TargetSpec]):
    def __init__(self) -> None:
        super().__init__("target")

    def register_spec(self, spec: TargetSpec, **kw: Any) -> RegistryRecord[TargetSpec]:
        return self.register(
            spec,
            plugin_id=spec.target_id,
            version=spec.version,
            **kw,
        )


@dataclass
class FelRegistries:
    """The four independent registries. One object for tests and later runner wiring."""

    features: FeatureRegistry
    models: ModelRegistry
    evaluators: EvaluatorRegistry
    targets: TargetRegistry
    version: str = FEL_VERSION


def default_fel(data_dir: str | None = None) -> FelRegistries:
    """Wraps + seed features + reserved sockets. Overlay persisted genealogy when ``data_dir`` is set."""
    from atlas.investment.fel.evaluators import WalkForwardEvaluator
    from atlas.investment.fel.features.seeds import seed_feature_computers
    from atlas.investment.fel.models.baselines import (
        ErPrototypePlugin,
        RankingV1Plugin,
        RulesSmaRsiPlugin,
    )
    from atlas.investment.fel.models.linear_features import (
        baseline_mom_rs_plugin,
        candidate_mom_rs_vol_plugin,
    )
    from atlas.investment.fel.models.reserved import reserved_model_plugins
    from atlas.investment.fel.targets import seed_targets

    features = FeatureRegistry()
    for computer in seed_feature_computers():
        features.register_computer(computer)

    models = ModelRegistry()
    for plugin in (
        RulesSmaRsiPlugin(),
        ErPrototypePlugin(),
        RankingV1Plugin(),
        baseline_mom_rs_plugin(),
        candidate_mom_rs_vol_plugin(),
    ):
        models.register_plugin(plugin)
    for plugin in reserved_model_plugins():
        models.register_plugin(plugin, notes="socket; appliance not installed")

    evaluators = EvaluatorRegistry()
    evaluators.register_plugin(WalkForwardEvaluator())

    targets = TargetRegistry()
    for spec in seed_targets():
        targets.register_spec(spec)

    if data_dir:
        from atlas.investment.fel.features.store import overlay_persisted

        overlay_persisted(features, data_dir)

    return FelRegistries(
        features=features,
        models=models,
        evaluators=evaluators,
        targets=targets,
    )
