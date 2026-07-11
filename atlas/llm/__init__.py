"""LLM package: provider abstraction + kernel-managed LLM service."""

from atlas.llm.ollama_provider import OllamaError, OllamaProvider
from atlas.llm.provider import (
    ChatMessage,
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
)
from atlas.llm.service import LLMService

__all__ = [
    "ChatMessage",
    "EmbeddingResponse",
    "LLMProvider",
    "LLMResponse",
    "LLMService",
    "OllamaError",
    "OllamaProvider",
]
