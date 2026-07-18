"""Prior-knowledge recall for research jobs (Stage 3B.1 mandatory call site).

Research always retrieves through the global Access Layer:

    knowledge.retrieve(objective, role=\"research\", …)
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from atlas.knowledge.domains import RESEARCHER_DOMAINS

if TYPE_CHECKING:
    from atlas.knowledge.access import RankedContext
    from atlas.knowledge.service import KnowledgeService


def recall_prior_knowledge(
    knowledge: "KnowledgeService | Any",
    objective: str,
    *,
    k: int = 5,
    domains: list[str] | None = None,
) -> "RankedContext":
    """Retrieve existing knowledge relevant to a research objective."""
    return knowledge.retrieve(
        objective,
        domains=domains if domains is not None else list(RESEARCHER_DOMAINS),
        role="research",
        k=k,
    )
