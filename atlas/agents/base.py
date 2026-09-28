"""Agent layer — the top of the four-layer architecture.

Agents orchestrate *services* (knowledge, llm) to accomplish goals. They know
*what* they want, never *how* it is done: an agent calls kernel-level services
and repositories, never SQL or a vendor SDK directly (ADR-0006/0027/0030).

This module defines the stable surface every agent shares:

    Agent.run(query, **options) -> AgentResult

so the AgentService can dispatch to any agent uniformly, and so new agent types
(summarizer, research, ...) plug in without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Citation:
    """A source reference backing part of an answer.

    M4 Step 2: every RAG citation exposes finding_id (when the hit is a
    finding), document_id, retrieval score, source tier, and source timestamp.
    These fields are provenance — they do not change retrieval ranking.
    """

    index: int  # 1-based marker used inline as [index]
    document_id: str
    chunk_id: str
    similarity: float
    snippet: str
    finding_id: str | None = None
    source: str | None = None
    timestamp: str | None = None
    score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        score = self.score if self.score is not None else self.similarity
        return {
            "index": self.index,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "similarity": round(self.similarity, 4),
            "snippet": self.snippet,
            "finding_id": self.finding_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "score": round(float(score), 6) if score is not None else None,
        }


@dataclass(frozen=True)
class AgentResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [c.as_dict() for c in self.citations],
            "usage": self.usage,
            "run_id": self.run_id,
        }


@runtime_checkable
class Agent(Protocol):
    name: str
    kind: str

    def run(self, query: str, **options: Any) -> AgentResult: ...
