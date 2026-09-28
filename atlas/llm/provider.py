"""LLM provider abstraction.

Atlas talks to LLMs through this protocol, never to a vendor SDK directly. Today
the only implementation is Ollama (local-first), but chat/generate/embed are the
stable surface that agents and services depend on, so a provider can be swapped
without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def coerce_chat_messages(messages: list[Any]) -> list[ChatMessage]:
    """Normalize dict / ChatMessage inputs for Ollama (expects ``as_dict``).

    Call sites historically passed raw ``{"role","content"}`` dicts; the provider
    requires ChatMessage. Coerce here so research/scientist paths cannot burn the
    off-market LLM window on AttributeError.
    """
    out: list[ChatMessage] = []
    for m in messages or []:
        if isinstance(m, ChatMessage):
            out.append(m)
            continue
        if isinstance(m, dict):
            role = str(m.get("role") or "user")
            content = m.get("content")
            if content is None:
                content = m.get("text") or ""
            out.append(ChatMessage(role=role, content=str(content)))
            continue
        role = str(getattr(m, "role", None) or "user")
        content = getattr(m, "content", None)
        if content is None:
            content = getattr(m, "text", None) or str(m)
        out.append(ChatMessage(role=role, content=str(content)))
    return out


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    thinking: str | None = None  # chain-of-thought, when a reasoning model emits it
    usage: dict[str, Any] = field(default_factory=dict)  # token/timing counters
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    model: str

    @property
    def dimension(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate(self, prompt: str, **options: Any) -> LLMResponse: ...

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse: ...

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse: ...

    def health(self) -> bool: ...
