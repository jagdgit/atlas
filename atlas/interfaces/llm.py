"""LLM and embedding provider interfaces (ADR-0038).

``LLMProvider`` already lives in ``atlas/llm/provider.py`` (its original home) and
is re-exported here so ``atlas.interfaces`` is the single, discoverable site for
"the abstractions services depend on". ADR-0038 also splits embeddings out into a
dedicated ``EmbeddingProvider`` so a separate embedding backend/model server can
be swapped independently of chat/generation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from atlas.llm.provider import (
    ChatMessage,
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Produces embedding vectors, independent of chat/generation.

    ``OllamaProvider`` satisfies this structurally today (it implements
    ``embed``); a dedicated embedding server can implement just this protocol.
    """

    name: str

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse: ...

    def health(self) -> bool: ...


__all__ = [
    "ChatMessage",
    "EmbeddingResponse",
    "LLMResponse",
    "LLMProvider",
    "EmbeddingProvider",
]
