"""Abstract provider interfaces Atlas services depend on (ADR-0038).

Services depend on these protocols, never on concrete backends. Concrete
implementations (e.g. ``OllamaProvider``, ``DatabaseManager``) satisfy them
structurally. Existing protocols keep their original definition sites and are
re-exported here so ``atlas.interfaces`` is the one place to see "the seams".

    LLMProvider        text generation / chat        (impl: OllamaProvider)
    EmbeddingProvider  embeddings, split from chat    (impl: OllamaProvider)
    MemoryProvider     memory store (Sprint 6)        (impl: TBD)
    StorageProvider    persistence backend            (impl: DatabaseManager)
"""

from __future__ import annotations

from atlas.interfaces.llm import (
    ChatMessage,
    EmbeddingProvider,
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
)
from atlas.interfaces.memory import MemoryProvider
from atlas.interfaces.storage import StorageProvider

__all__ = [
    "LLMProvider",
    "EmbeddingProvider",
    "MemoryProvider",
    "StorageProvider",
    "ChatMessage",
    "EmbeddingResponse",
    "LLMResponse",
]
