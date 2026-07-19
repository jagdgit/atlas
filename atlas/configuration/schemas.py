"""Mission-config schema registry (Phase A · PHASE_A_PLAN §A.2, P6/B6).

A config **document** is only ever stored after it validates against a registered Pydantic
schema (invalid configs are rejected, never persisted). Each schema is registered under a
``schema_type`` (e.g. ``"hello_watcher"``, ``"paper_trading"``) *and* carries an explicit
integer ``schema_version`` (B6): stored config rows keep the ``schema_version`` they were
written under, old rows stay immutable, and a breaking change becomes a **new** version —
never an automatic in-place transform.

The full Phase-A/D template schemas (paper_trading, job_hunting, …) register here as their
phases land; Phase A ships ``hello_watcher`` (the acceptance vehicle) as the reference impl.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.exceptions.base import AtlasError


class ConfigSchemaError(AtlasError):
    """A config document is invalid, or its ``schema_type`` is unknown."""


# --- built-in schemas ----------------------------------------------------


class HelloWatcherConfig(BaseModel):
    """Config for the Phase-A acceptance worker (§A.4/A.5).

    ``extra='forbid'`` so an unknown/typo'd key is a hard error at write time rather than a
    silently ignored setting — this is what makes "invalid config is rejected" meaningful.
    """

    model_config = ConfigDict(extra="forbid")

    greeting: str = "hello"
    tick_limit: int = Field(default=0, ge=0)   # 0 = unlimited ticks
    tick_interval_seconds: int = Field(default=60, ge=1)


class GenericConfig(BaseModel):
    """Permissive schema for **stub** templates (§A.5) whose real config schema lands with its
    Phase (B/C/D). ``extra='allow'`` so a stub mission can carry a free-form config now and be
    tightened to a strict schema + a new ``schema_version`` when the feature is built (B6)."""

    model_config = ConfigDict(extra="allow")


class RepoWatcherConfig(BaseModel):
    """Config for the Repository-Learning mission's RepoWatcher (Phase B · §B.6, BB7).

    ``extra='forbid'`` so a typo'd key is rejected at write time (a real strict schema, unlike
    the ``generic`` stub it replaces). Exactly one of ``repo_url`` / ``repo_path`` identifies the
    repository; both may be empty at instantiation and filled in via a later config edit (a new
    version — B6). ``embed_code`` toggles priority-capped code embeddings (BB4); ``languages`` is
    informational (the Reader Registry detects languages, B.4)."""

    model_config = ConfigDict(extra="forbid")

    repo_url: str = ""
    repo_path: str = ""
    branch: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["python"])
    embed_code: bool = False
    policy: str = "project"
    tick_interval_seconds: int = Field(default=3600, ge=1)


class ArchiveRoot(BaseModel):
    """One configured root of the User Archive (Phase C · §C.8).

    A root is a durable *source* of assets (not a job that finishes): a directory Atlas keeps
    reading. ``kind`` selects the pipeline — ``code`` → repository learning (findings + experience),
    ``document`` → the Document Reader, ``conversation`` → the Conversation Reader (chat/Cursor
    exports). ``domain`` labels the knowledge/coverage provenance; ``extensions`` optionally narrows
    which files a document/conversation root ingests (defaults per kind)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    kind: str = Field(default="document", pattern="^(code|document|conversation)$")
    domain: str = "personal"
    extensions: list[str] | None = None


class OwnerKnowledgeConfig(BaseModel):
    """Config for the Owner Knowledge Mission's worker (Phase C · §C.8, CC7).

    A permanent mission that continuously reads the operator's **User Archive** — code, docs, papers,
    notes, chats — into global knowledge + experience, then rebuilds the personal profile. ``extra=
    'forbid'`` (a real strict schema). Roots may be empty at instantiation and filled via a later
    config edit (a new version — B6)."""

    model_config = ConfigDict(extra="forbid")

    archive_roots: list[ArchiveRoot] = Field(default_factory=list)
    build_profile: bool = True
    embed: bool = False
    policy: str = "project"
    tick_interval_seconds: int = Field(default=3600, ge=1)


class TradingInstrument(BaseModel):
    """One instrument the Paper-Trading mission replays (Phase D · §D.6).

    ``symbol`` is the ticker the strategy + policy reason about; ``asset`` names the OHLCV feed asset
    (a ``market_data`` asset registered in the Asset Store) — defaults to the symbol if omitted."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    asset: str = ""


class TradingStrategyParams(BaseModel):
    """MA-crossover + RSI strategy parameters (Phase D · §D.6). All optional with sane defaults."""

    model_config = ConfigDict(extra="forbid")

    sma_fast: int = Field(default=10, ge=1)
    sma_slow: int = Field(default=30, ge=2)
    rsi_period: int = Field(default=14, ge=2)
    rsi_overbought: float = Field(default=70.0, ge=0, le=100)
    rsi_oversold: float = Field(default=30.0, ge=0, le=100)
    trade_fraction: float = Field(default=0.1, gt=0, le=1)
    sell_fraction: float = Field(default=1.0, gt=0, le=1)


class PaperTradingConfig(BaseModel):
    """Config for the Paper-Trading mission's worker (Phase D · §D.6, P10 — SIMULATION ONLY).

    ``extra='forbid'`` (a real strict schema, unlike the ``generic`` stub it replaces). Instruments +
    strategy params + risk constraints + replay cadence are all versioned (an edit is a new version —
    B6, and the worker picks it up on the next tick). NO real money, NO real broker (P10)."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[TradingInstrument] = Field(default_factory=list)
    starting_cash: float = Field(default=100_000.0, gt=0)
    strategy: TradingStrategyParams = Field(default_factory=TradingStrategyParams)
    max_position_qty: float = Field(default=0.0, ge=0)     # 0 = unbounded
    max_exposure_pct: float = Field(default=0.0, ge=0)     # 0 = unbounded (percent of equity)
    bars_per_tick: int = Field(default=1, ge=1)
    drawdown_alert_pct: float = Field(default=0.0, ge=0)   # 0 = no drawdown alert
    tick_interval_seconds: int = Field(default=300, ge=1)


# --- registry ------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredSchema:
    schema_type: str
    schema_version: int
    model: type[BaseModel]


class SchemaRegistry:
    """Maps ``schema_type`` → the current Pydantic model + its ``schema_version``."""

    def __init__(self) -> None:
        self._schemas: dict[str, RegisteredSchema] = {}

    def register(
        self, schema_type: str, model: type[BaseModel], *, schema_version: int = 1
    ) -> None:
        self._schemas[schema_type] = RegisteredSchema(
            schema_type=schema_type, schema_version=schema_version, model=model
        )

    def known(self) -> list[str]:
        return sorted(self._schemas)

    def current_version(self, schema_type: str) -> int:
        return self._require(schema_type).schema_version

    def validate(self, schema_type: str, document: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Validate + normalize a document; return ``(normalized_document, schema_version)``.

        Raises :class:`ConfigSchemaError` for an unknown ``schema_type`` or an invalid
        document (never stores an invalid config).
        """
        reg = self._require(schema_type)
        try:
            model = reg.model.model_validate(document or {})
        except ValidationError as exc:
            raise ConfigSchemaError(
                f"invalid {schema_type} config",
                schema_type=schema_type,
                errors=exc.errors(include_url=False),
            ) from exc
        return model.model_dump(mode="json"), reg.schema_version

    def _require(self, schema_type: str) -> RegisteredSchema:
        reg = self._schemas.get(schema_type)
        if reg is None:
            raise ConfigSchemaError(
                f"unknown config schema_type: {schema_type!r}",
                known=self.known(),
            )
        return reg


def default_registry() -> SchemaRegistry:
    """The registry Atlas boots with (built-in schemas)."""
    registry = SchemaRegistry()
    registry.register("hello_watcher", HelloWatcherConfig, schema_version=1)
    registry.register("generic", GenericConfig, schema_version=1)
    registry.register("repo_watcher", RepoWatcherConfig, schema_version=1)
    registry.register("owner_knowledge", OwnerKnowledgeConfig, schema_version=1)
    registry.register("paper_trading", PaperTradingConfig, schema_version=1)
    return registry
