"""IntelligenceContext — the composed view of Atlas's intelligences for a decision (Phase D · §D.2).

The Decision Engine is *the consumer*: it combines **Research** (facts/literature), **Engineering**
(findings/recommendations) and **Personal** (preferences/constraints/skills) knowledge — plus **Policy**
arbitration — into one choice. This class is the thin, **lazy** access layer a
:class:`~atlas.decision.rules.DecisionRule` uses to pull exactly what it needs while it scores, without
importing concrete services (CC-D2 — resolve via injected capabilities) and without paying for an
expensive intelligence it doesn't consult (e.g. a full research run) unless it asks.

Capability honesty (P15): if a rule reaches for an intelligence that isn't wired, the accessor raises
:class:`~atlas.decision.rules.CapabilityGap`, which the engine turns into an honest ``capability_gap``
decision naming exactly what is missing — never a fabricated answer. All accessors are read-only
(P10/P14 — the engine recommends, it never acts through these).
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.rules import CapabilityGap


class IntelligenceContext:
    """Lazy, read-only accessors over the three intelligences (+ raw knowledge search)."""

    def __init__(
        self,
        *,
        engineering: Any = None,
        research: Any = None,
        personal: Any = None,
        knowledge: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._eng = engineering
        self._research = research
        self._personal = personal
        self._knowledge = knowledge
        self._logger = logger or logging.getLogger("atlas.decision.context")

    # --- engineering ----------------------------------------------------
    def findings(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Global engineering findings (the "get facts" path). Raises CapabilityGap if absent (P15)."""
        return self._require(self._eng, "engineering").list_findings(**kwargs)

    def recommend(self, context: str = "", *, limit: int | None = None) -> dict[str, Any]:
        """L5 engineering recommendations for a free-text context."""
        return self._require(self._eng, "engineering").recommend(context, limit=limit)

    def search(self, query: str, *, limit: int = 20) -> Any:
        """Lexical/semantic search over engineering knowledge."""
        return self._require(self._eng, "engineering").search(query, limit=limit)

    # --- personal -------------------------------------------------------
    def profile(self, *, include_inferred: bool = True) -> dict[str, Any]:
        """The curated owner profile (preferences/skills/identity/timeline) other missions read."""
        return self._require(self._personal, "personal").profile(include_inferred=include_inferred)

    def skills(self, *, include_inferred: bool = True) -> list[dict[str, Any]]:
        return self._require(self._personal, "personal").skills(include_inferred=include_inferred)

    # --- research -------------------------------------------------------
    def research(self, objective: str, **kwargs: Any) -> dict[str, Any]:
        """Run/verify research for fresh facts. Heavy — rules should call it sparingly."""
        return self._require(self._research, "research").research(objective, **kwargs)

    # --- raw knowledge --------------------------------------------------
    def knowledge_search(self, query: str, **kwargs: Any) -> Any:
        return self._require(self._knowledge, "knowledge").search(query, **kwargs)

    # --- availability (rules can check before committing to a path) ------
    def has(self, name: str) -> bool:
        return {
            "engineering": self._eng,
            "research": self._research,
            "personal": self._personal,
            "knowledge": self._knowledge,
        }.get(name) is not None

    def require(self, name: str) -> Any:
        """Return the named intelligence or raise CapabilityGap (P15)."""
        svc = {
            "engineering": self._eng,
            "research": self._research,
            "personal": self._personal,
            "knowledge": self._knowledge,
        }.get(name)
        return self._require(svc, name)

    # --- internals ------------------------------------------------------
    @staticmethod
    def _require(service: Any, name: str) -> Any:
        if service is None:
            raise CapabilityGap(f"intelligence:{name}", f"the {name} intelligence is not available")
        return service
