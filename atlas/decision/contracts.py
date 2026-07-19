"""Decision Engine contracts (Phase D · PHASE_D_PLAN §D.1, roadmap §5.5 / P9/P14/P15).

Typed, serialisable inputs and outputs for the Decision Engine — the shared Kernel Service that answers
*"what should this Mission do next?"*. The engine's **choice is deterministic** (rules + scoring, Q7);
an LLM may only render the human ``why`` prose of an already-made decision (CC-D1).

- :class:`DecisionRequest` — what a mission asks: its id/type, the config version in force, and a free
  ``context`` dict of signals/candidate options the mission-type rule interprets.
- :class:`ScoredOption` — one candidate next action with a deterministic base score, plus the refs
  (knowledge/experience/evidence) that justify it and an optional ``side_effecting`` flag (→ approval).
- :class:`Decision` — the full **P9 explanation record**: action, why, refs, config + model versions,
  confidence, and the alternatives it rejected. Persisted to ``decision.decisions`` (append-only).

Action kinds: ``recommend`` (a real next action), ``hold`` (nothing worth doing this tick), and
``capability_gap`` (P15 — a needed capability/reader/rule is missing; the engine names it for the
operator instead of fabricating an action).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --- action kinds ------------------------------------------------------------
ACTION_RECOMMEND = "recommend"
ACTION_HOLD = "hold"
ACTION_CAPABILITY_GAP = "capability_gap"

# --- confidence labels -------------------------------------------------------
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


@dataclass
class DecisionRequest:
    """What a Mission asks the engine: which mission, which config, and the decision context."""

    mission_id: str | None
    mission_type: str
    config_id: str | None = None
    config_version: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    now: datetime | None = None


@dataclass
class ScoredOption:
    """One candidate next action with a deterministic base score and its justifying refs."""

    key: str
    score: float = 0.0
    text: str = ""
    tags: tuple[str, ...] = ()
    rationale: str = ""
    knowledge_refs: list[Any] = field(default_factory=list)
    experience_refs: list[Any] = field(default_factory=list)
    evidence_refs: list[Any] = field(default_factory=list)
    side_effecting: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    # Set by the engine when it folds policy influence in (DD5); left at defaults otherwise.
    policy_boost: float = 0.0
    policy_ids: tuple[str, ...] = ()

    @property
    def final_score(self) -> float:
        return self.score + self.policy_boost

    def to_summary(self) -> dict[str, Any]:
        """Compact form recorded under ``alternatives_rejected`` / the chosen action (refs, not copies)."""
        return {
            "key": self.key,
            "score": round(self.final_score, 6),
            "base_score": round(self.score, 6),
            "policy_boost": round(self.policy_boost, 6),
            "policy_ids": list(self.policy_ids),
            "rationale": self.rationale,
            "side_effecting": self.side_effecting,
        }


@dataclass
class Decision:
    """The full P9 explanation record for one decision — the canonical 'Explain this' payload."""

    mission_id: str | None
    mission_type: str
    action_kind: str
    action: dict[str, Any] = field(default_factory=dict)
    why: str = ""
    decision_rule: str | None = None
    rule_version: str | None = None
    config_id: str | None = None
    config_version: int | None = None
    evidence_refs: list[Any] = field(default_factory=list)
    knowledge_refs: list[Any] = field(default_factory=list)
    experience_refs: list[Any] = field(default_factory=list)
    model_versions: dict[str, Any] = field(default_factory=dict)
    policy_ids: list[str] = field(default_factory=list)
    confidence: str = CONFIDENCE_LOW
    confidence_score: float = 0.0
    alternatives_rejected: list[dict[str, Any]] = field(default_factory=list)
    requires_approval: bool = False
    status: str = "recorded"
    # Populated after persistence.
    id: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "mission_id": str(self.mission_id) if self.mission_id else None,
            "mission_type": self.mission_type,
            "action_kind": self.action_kind,
            "action": self.action,
            "why": self.why,
            "decision_rule": self.decision_rule,
            "rule_version": self.rule_version,
            "config_id": str(self.config_id) if self.config_id else None,
            "config_version": self.config_version,
            "evidence_refs": self.evidence_refs,
            "knowledge_refs": self.knowledge_refs,
            "experience_refs": self.experience_refs,
            "model_versions": self.model_versions,
            "policy_ids": self.policy_ids,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "alternatives_rejected": self.alternatives_rejected,
            "requires_approval": self.requires_approval,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def derive_confidence(scores: list[float]) -> tuple[str, float]:
    """Deterministic confidence from the score distribution (softmax probability of the top option).

    A wide margin over the runners-up → high confidence; a near-tie → low. Reproducible (no LLM),
    bounded to [0, 1]. A lone option yields 1.0 (nothing competes with it).
    """
    if not scores:
        return CONFIDENCE_LOW, 0.0
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]  # shift for numerical stability
    total = sum(exps)
    prob = (max(exps) / total) if total > 0 else 0.0
    if prob >= 0.66:
        label = CONFIDENCE_HIGH
    elif prob >= 0.4:
        label = CONFIDENCE_MEDIUM
    else:
        label = CONFIDENCE_LOW
    return label, round(prob, 6)
