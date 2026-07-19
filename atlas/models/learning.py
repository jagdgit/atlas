"""Learning-domain models: LearningEvent and Experience (Stage 2, S18b, D11/§5d).

A ``LearningEvent`` is the governed, explainable, reversible record of a single
learning action (``learning.events``); an ``Experience`` is one entry in the
Experience store (``learning.experiences``) — problem → diagnosis → actions →
mistakes → solution → lessons. Both map rows to typed models (ADR-0036).

Governance (§5d.5) lives in the ``policy`` label; the Learning Level (§5d.6) lives
in ``level``. The event ``status`` (``proposed → applied → reverted``) is what makes
"Atlas never silently learns" enforceable: nothing is in a store until an event is
*applied*, and every application can be *reverted*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model

# --- source types (where the learning material came from) ----------------
SOURCE_JOB = "job"
SOURCE_REPO = "repo"
SOURCE_DOCUMENT = "document"
SOURCE_CONVERSATION = "conversation"
SOURCE_MANUAL = "manual"

# --- the five stores (§5d.2) ---------------------------------------------
STORE_EXPERIENCE = "experience"
STORE_KNOWLEDGE = "knowledge"
STORE_CODE = "code"
STORE_MEMORY = "memory"
STORE_CONVERSATION = "conversation"

# --- governance policies (§5d.5) -----------------------------------------
POLICY_TEMPORARY = "temporary"
POLICY_PROJECT = "project"
POLICY_PERSONAL = "personal"
POLICY_VERIFIED = "verified"
POLICIES = frozenset({POLICY_TEMPORARY, POLICY_PROJECT, POLICY_PERSONAL, POLICY_VERIFIED})

# --- event lifecycle -----------------------------------------------------
EVENT_PROPOSED = "proposed"
EVENT_APPLIED = "applied"
EVENT_REVERTED = "reverted"

# --- experience lifecycle ------------------------------------------------
EXP_ACTIVE = "active"
EXP_REVERTED = "reverted"

# --- Learning Levels (§5d.6) ---------------------------------------------
LEVEL_STORE = 1
LEVEL_UNDERSTAND = 2
LEVEL_CONNECT = 3
LEVEL_GENERALIZE = 4
LEVEL_RECOMMEND = 5

_LEVEL_NAMES = {
    1: "L1 Store",
    2: "L2 Understand",
    3: "L3 Connect",
    4: "L4 Generalize",
    5: "L5 Recommend",
}


def learning_level_name(level: int) -> str:
    return _LEVEL_NAMES.get(int(level), f"L{level}")


@dataclass(frozen=True, slots=True)
class LearningEvent(Model):
    id: str
    source_type: str
    store: str
    source_id: str | None = None
    policy: str = POLICY_TEMPORARY
    level: int = LEVEL_STORE
    status: str = EVENT_PROPOSED
    summary: str = ""
    reason: str = ""
    origin: str = ""
    project: str | None = None
    ref_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reviewed_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "store": self.store,
            "policy": self.policy,
            "level": self.level,
            "level_name": learning_level_name(self.level),
            "status": self.status,
            "summary": self.summary,
            "reason": self.reason,
            "origin": self.origin,
            "project": self.project,
            "ref_id": self.ref_id,
            "metadata": dict(self.metadata or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


@dataclass(frozen=True, slots=True)
class LearnedRepository(Model):
    """A repository distilled to structure — the Code store (S19, L2 Understand)."""

    id: str
    name: str
    root: str
    languages: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    file_count: int = 0
    symbol_count: int = 0
    loc: int = 0
    summary: str = ""
    top_symbols: list[Any] = field(default_factory=list)
    patterns: list[Any] = field(default_factory=list)
    policy: str = POLICY_PROJECT
    status: str = EXP_ACTIVE
    # Phase B provenance (§B.1, BB12/P2): stable identity + Asset Store link.
    repo_uid: str | None = None
    root_commit: str | None = None
    normalized_remote: str | None = None
    asset_id: str | None = None
    asset_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "root": self.root,
            "languages": dict(self.languages),
            "frameworks": list(self.frameworks),
            "entry_points": list(self.entry_points),
            "dependencies": {k: list(v) for k, v in self.dependencies.items()},
            "file_count": self.file_count,
            "symbol_count": self.symbol_count,
            "loc": self.loc,
            "summary": self.summary,
            "top_symbols": list(self.top_symbols),
            "patterns": list(self.patterns),
            "policy": self.policy,
            "status": self.status,
            "repo_uid": self.repo_uid,
            "root_commit": self.root_commit,
            "normalized_remote": self.normalized_remote,
            "asset_id": self.asset_id,
            "asset_version": self.asset_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True, slots=True)
class EngineeringPattern(Model):
    """A pattern generalized across learned repositories (S19, L4 Generalize)."""

    id: str
    name: str
    category: str = "engineering"
    description: str = ""
    prevalence: float = 0.0
    repo_count: int = 0
    total_repos: int = 0
    confidence: float = 0.0
    level: int = LEVEL_GENERALIZE
    evidence: list[str] = field(default_factory=list)
    status: str = EXP_ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "prevalence": round(self.prevalence, 3),
            "repo_count": self.repo_count,
            "total_repos": self.total_repos,
            "confidence": round(self.confidence, 3),
            "level": self.level,
            "level_name": learning_level_name(self.level),
            "evidence": list(self.evidence),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class Experience(Model):
    id: str
    title: str = ""
    problem: str = ""
    diagnosis: str = ""
    actions: list[Any] = field(default_factory=list)
    mistakes: str = ""
    solution: str = ""
    lessons: str = ""
    tags: list[str] = field(default_factory=list)
    source_job_id: str | None = None
    policy: str = POLICY_TEMPORARY
    status: str = EXP_ACTIVE
    payload: dict[str, Any] = field(default_factory=dict)
    bias_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "problem": self.problem,
            "diagnosis": self.diagnosis,
            "actions": list(self.actions),
            "mistakes": self.mistakes,
            "solution": self.solution,
            "lessons": self.lessons,
            "tags": list(self.tags),
            "source_job_id": self.source_job_id,
            "policy": self.policy,
            "status": self.status,
            "payload": dict(self.payload or {}),
            "bias_enabled": bool(self.bias_enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True, slots=True)
class ComponentObservation(Model):
    """Per-component+version ops metrics from a job (Stage 3B.5 / D3B.24)."""

    id: str
    component_key: str
    component_version: str = "1"
    corpus: str | None = None
    profile: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    source_job_id: str | None = None
    experience_id: str | None = None
    event_id: str | None = None
    created_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component_key": self.component_key,
            "component_version": self.component_version,
            "corpus": self.corpus,
            "profile": self.profile,
            "metrics": dict(self.metrics or {}),
            "source_job_id": self.source_job_id,
            "experience_id": self.experience_id,
            "event_id": self.event_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
