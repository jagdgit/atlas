"""Knowledge package: ingestion, Access Layer, findings lifecycle."""

from atlas.knowledge.access import RankedContext, RankedHit
from atlas.knowledge.chunking import Chunk, chunk_text
from atlas.knowledge.conflict import (
    KnowledgeConflictDecisionRule,
    MISSION_TYPE_KNOWLEDGE_CONFLICT,
)
from atlas.knowledge.consolidation import KnowledgeLifecycleService
from atlas.knowledge.lifecycle import freshness_label
from atlas.knowledge.service import KnowledgeService, SearchResult

__all__ = [
    "Chunk",
    "chunk_text",
    "KnowledgeConflictDecisionRule",
    "KnowledgeLifecycleService",
    "KnowledgeService",
    "MISSION_TYPE_KNOWLEDGE_CONFLICT",
    "RankedContext",
    "RankedHit",
    "SearchResult",
    "freshness_label",
]
