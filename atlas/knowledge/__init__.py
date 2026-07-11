"""Knowledge package: ingestion, chunking, embedding, and semantic search."""

from atlas.knowledge.chunking import Chunk, chunk_text
from atlas.knowledge.service import KnowledgeService, SearchResult

__all__ = ["Chunk", "chunk_text", "KnowledgeService", "SearchResult"]
