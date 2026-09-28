"""FEL.0 contracts — plugin seam for the Feature & Experiment Laboratory.

Atlas already uses Protocol + Registry + honest ``available()`` (feeds, OCR,
search, instrument packs, decision rules). FEL copies that pattern. Callers
never import sklearn / torch / an RL library; they call ``ModelPlugin``.

Locked (OI-FEL0): no silent substitution; wraps of existing Atlas methods first;
reserved plugin ids may exist with ``available() is False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

FEL_VERSION = "fel.1"

DECISION_ELIGIBLE_STATUSES: frozenset[str] = frozenset({"registered", "promoted"})
OBSERVATION_STATUSES: frozenset[str] = frozenset(
    {"registered", "candidate", "promoted", "conditional"}
)

DecisionType = Literal[
    "buy_name",
    "size_name",
    "sell_incumbent",
    "switch",
    "hold_cash",
    "event_react",
]

Role = Literal["observer", "scientist", "experimentalist", "strategist", "learner"]

ModelTask = Literal["regression", "classification", "ranking", "probability"]

FeatureStatus = Literal[
    "registered",
    "candidate",
    "promoted",
    "conditional",
    "retired",
    "deceived",
]

PluginStatus = Literal["active", "reserved", "retired"]

ExperimentResult = Literal[
    "improve",
    "no_significant",
    "worse",
    "conditional",
    "invalid",
    "blocked_unavailable",
]


class BlockedUnavailable(Exception):
    """Requested plugin is missing or ``available()`` is false — never run a substitute."""

    def __init__(self, plugin_id: str, *, reason: str = "", requested: str | None = None) -> None:
        self.plugin_id = plugin_id
        self.reason = reason or "unavailable"
        self.requested = requested or plugin_id
        super().__init__(f"blocked_unavailable: {self.requested} ({self.reason})")

    def as_result(self) -> dict[str, Any]:
        return {
            "result": "blocked_unavailable",
            "plugin_id": self.plugin_id,
            "requested": self.requested,
            "ran": None,
            "reason": self.reason,
        }


@dataclass
class FeatureMatrix:
    """as-of rows for fit/predict. Missing features stay missing (never coerced to 0)."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FittedArtifact:
    """Identity is plugin_id + version + params — not 'whatever is imported'."""

    plugin_id: str
    version: str
    params: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        return f"{self.plugin_id}@{self.version}"


@dataclass
class Predictions:
    values: list[Any] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureGenealogy:
    """Why this feature exists — scientific memory on the registry row, not a new store."""

    feature_id: str
    version: str
    sources: list[str] = field(default_factory=list)
    formula: str = ""
    timeframe: str = "1d"
    lookback: int = 0
    availability_time: str = "session_close"
    origin: str = "wrap"
    hypothesis_id: str | None = None
    scientist_reason: str = ""
    source_concepts: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    tested_for: list[str] = field(default_factory=list)
    tested_models: list[str] = field(default_factory=list)
    result: str | None = None
    not_useful_for: list[str] = field(default_factory=list)
    status: FeatureStatus = "registered"
    data_quality: str | None = None
    usage_count: int = 0
    predictive_score: dict[str, Any] = field(default_factory=dict)
    stability: str | None = None
    correlation: dict[str, Any] = field(default_factory=dict)
    importance: dict[str, Any] = field(default_factory=dict)
    last_evaluated: str | None = None
    # CLC.3 — L1/L2 caution only. Never implies live_control / decision_eligible.
    lesson_eligible: bool = False

    @property
    def decision_eligible(self) -> bool:
        return self.status in DECISION_ELIGIBLE_STATUSES

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "version": self.version,
            "sources": list(self.sources),
            "formula": self.formula,
            "timeframe": self.timeframe,
            "lookback": self.lookback,
            "availability_time": self.availability_time,
            "origin": self.origin,
            "hypothesis_id": self.hypothesis_id,
            "scientist_reason": self.scientist_reason,
            "source_concepts": list(self.source_concepts),
            "derived_from": list(self.derived_from),
            "tested_for": list(self.tested_for),
            "tested_models": list(self.tested_models),
            "result": self.result,
            "not_useful_for": list(self.not_useful_for),
            "status": self.status,
            "data_quality": self.data_quality,
            "usage_count": int(self.usage_count),
            "predictive_score": dict(self.predictive_score),
            "stability": self.stability,
            "correlation": dict(self.correlation),
            "importance": dict(self.importance),
            "last_evaluated": self.last_evaluated,
            "decision_eligible": self.decision_eligible,
            "lesson_eligible": bool(self.lesson_eligible),
        }


@runtime_checkable
class FeatureComputer(Protocol):
    feature_id: str
    version: str
    sources: tuple[str, ...]
    timeframe: str
    lookback: int
    status: FeatureStatus

    def compute(self, pit_context: dict[str, Any]) -> Any:
        """Return a value or None. Never invent 0 for missing inputs."""
        ...


@runtime_checkable
class ModelPlugin(Protocol):
    plugin_id: str
    version: str
    tasks: frozenset[str]

    def available(self) -> bool: ...

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact: ...

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions: ...

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        ...


@runtime_checkable
class EvaluatorPlugin(Protocol):
    evaluator_id: str
    version: str

    def available(self) -> bool: ...

    def evaluate(self, **kwargs: Any) -> dict[str, Any]: ...


@runtime_checkable
class TargetSpec(Protocol):
    target_id: str
    version: str
    decision_type: DecisionType
    horizon: str
