"""Decision rules — the per-mission-type deterministic scoring plugins (Phase D · §D.1, DD2).

One engine, many missions: the generic :class:`~atlas.decision.engine.DecisionEngine` owns the shared
mechanics (gather refs, fold in policy, pick the top option, assemble the P9 record, persist), while a
**mission-type-specific** :class:`DecisionRule` owns the *domain scoring* — e.g. a trading strategy, a
job-match ranker, a research "what to read next" scorer. Rules are **pure + deterministic** (Q7): given
the same request they return the same options; they never call an LLM to choose and never persist.

A rule that cannot proceed because a capability it needs is **absent** (no data source, no reader, no
model) raises :class:`CapabilityGap` — the engine turns that into an honest ``capability_gap`` decision
(P15) instead of a fabricated action.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from atlas.decision.contracts import DecisionRequest, ScoredOption

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


class CapabilityGap(Exception):
    """Raised by a rule when a required capability is missing (→ a P15 ``capability_gap`` decision)."""

    def __init__(self, capability: str, detail: str = "") -> None:
        self.capability = capability
        self.detail = detail
        super().__init__(f"capability gap: {capability}{f' — {detail}' if detail else ''}")


@runtime_checkable
class DecisionRule(Protocol):
    """A deterministic, per-mission-type scorer. Returns candidate options; never picks or persists."""

    mission_type: str
    VERSION: str

    def score(self, request: DecisionRequest) -> list[ScoredOption]:
        """Return scored candidate options for this request (may be empty → the engine holds)."""
        ...


class DecisionRuleRegistry:
    """Registry of :class:`DecisionRule` keyed by mission type (mirrors the reader/worker registries)."""

    def __init__(self) -> None:
        self._rules: dict[str, DecisionRule] = {}

    def register(self, rule: DecisionRule) -> None:
        mtype = getattr(rule, "mission_type", None)
        if not mtype:
            raise ValueError("a DecisionRule must declare a non-empty mission_type")
        self._rules[mtype] = rule

    def get(self, mission_type: str) -> DecisionRule | None:
        return self._rules.get(mission_type)

    def known_types(self) -> list[str]:
        return sorted(self._rules)


def apply_policy_influence(
    options: list[ScoredOption], influences: list[dict[str, Any]]
) -> list[ScoredOption]:
    """Fold signed, bounded policy influence into option scores (DD5 — arbitration, not filtering).

    For each option, any policy rule whose ``terms`` intersect the option's tags/key/text contributes
    its signed ``weight`` (positive = prefer/trust, negative = avoid/distrust). Influence *nudges*
    ranking; it never removes an option. Mutates + returns the options (with ``policy_boost``/
    ``policy_ids`` recorded for explainability).
    """
    if not influences:
        return options
    for opt in options:
        haystack = set(opt.tags) | _tokenize(opt.text) | _tokenize(opt.key)
        boost = 0.0
        ids: list[str] = []
        for inf in influences:
            terms = inf.get("terms") or []
            if terms and any(t in haystack for t in terms):
                boost += float(inf.get("weight") or 0.0)
                ids.append(str(inf.get("id")))
        opt.policy_boost = boost
        opt.policy_ids = tuple(ids)
    return options
