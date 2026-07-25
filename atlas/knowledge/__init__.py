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
from atlas.knowledge.temporal import (
    TRUTH_CURRENT,
    TRUTH_HISTORICAL,
    TRUTH_PREDICTED,
    annotate_finding_item,
    is_operative_fact,
    partition_by_truth,
    stamp_prediction,
    stamp_validity,
    truth_kind,
)

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
    "TRUTH_CURRENT",
    "TRUTH_HISTORICAL",
    "TRUTH_PREDICTED",
    "annotate_finding_item",
    "freshness_label",
    "is_operative_fact",
    "partition_by_truth",
    "stamp_prediction",
    "stamp_validity",
    "truth_kind",
]
