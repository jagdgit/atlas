"""LLM service — kernel-managed capability wrapping an LLMProvider.

Agents/services depend on this service (via the container), not on Ollama. Its
health check verifies the provider is reachable and that the configured chat
model is actually available, so a missing model surfaces in `system.health`
rather than failing at request time.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from atlas.llm.provider import ChatMessage, EmbeddingResponse, LLMResponse
from atlas.services.base import HealthStatus
from atlas.telemetry import timer

if TYPE_CHECKING:
    from atlas.llm.provider import LLMProvider


class LLMService:
    name = "llm"

    def __init__(
        self,
        provider: "LLMProvider",
        *,
        model: str,
        embedding_model: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._embedding_model = embedding_model
        self._logger = logger or logging.getLogger("atlas.llm")

    # --- capability API -------------------------------------------------
    def generate(self, prompt: str, **options: Any) -> LLMResponse:
        with timer("llm.generate"):
            return self._provider.generate(prompt, **options)

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        with timer("llm.chat"):
            return self._provider.chat(messages, **options)

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        with timer("llm.embed", batch=len(texts)):
            return self._provider.embed(texts, **options)

    @property
    def provider(self) -> "LLMProvider":
        return self._provider

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        if not self._provider.health():
            self._logger.warning(
                "LLM provider '%s' not reachable at startup", self._provider.name
            )
            return
        available = set(self._available_models())
        if self._model not in available:
            self._logger.warning(
                "configured chat model '%s' not found; available: %s",
                self._model,
                sorted(available),
            )

    def stop(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()

    def health_check(self) -> HealthStatus:
        if not self._provider.health():
            return HealthStatus.fail(f"{self._provider.name} unreachable")
        models = self._available_models()
        chat_ok = self._model_available(self._model, models)
        embed_ok = self._model_available(self._embedding_model, models)
        detail = (
            f"{self._provider.name} up; chat '{self._model}'"
            f"{'' if chat_ok else ' [MISSING]'}, "
            f"embed '{self._embedding_model}'{'' if embed_ok else ' [not pulled]'}"
        )
        # A missing embedding model is non-fatal (only needed for the knowledge
        # sprint); a missing chat model means the service can't do its main job.
        return HealthStatus(
            healthy=chat_ok,
            detail=detail,
            data={
                "models": models,
                "chat_model_ready": chat_ok,
                "embedding_model_ready": embed_ok,
            },
        )

    # --- internals ------------------------------------------------------
    @staticmethod
    def _model_available(name: str, models: list[str]) -> bool:
        # Ollama resolves a bare name (no tag) to ':latest'; match either form.
        if name in models:
            return True
        return ":" not in name and f"{name}:latest" in models

    def _available_models(self) -> list[str]:
        lister = getattr(self._provider, "list_models", None)
        if callable(lister):
            try:
                return lister()
            except Exception:  # noqa: BLE001
                return []
        return []
