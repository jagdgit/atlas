"""LLM service — kernel-managed capability wrapping an LLMProvider.

Agents/services depend on this service (via the container), not on Ollama. Its
health check verifies the provider is reachable and that the configured chat
model is actually available, so a missing model surfaces in `system.health`
rather than failing at request time.

Two Stage-2 concepts live here (D7 / R4):

- **Roles, not model names.** Callers ask for a *role* (chat/planner/researcher/
  summarizer/code/vision/embed) via ``for_role``; the service resolves the role to
  a concrete model. Swap models by editing config — no call site names a model.
- **A single LLM lane.** On CPU-only hardware, running two models at once thrashes
  RAM, so every generate/chat/embed call passes through one semaphore
  (``llm.max_concurrency``, default 1). Concurrency in Atlas is parallel I/O, not
  parallel inference.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, TYPE_CHECKING

from atlas.llm.provider import ChatMessage, EmbeddingResponse, LLMResponse
from atlas.services.base import HealthStatus
from atlas.telemetry import timer

if TYPE_CHECKING:
    from atlas.llm.provider import LLMProvider


class RoleClient:
    """A thin, role-bound view of the LLMService (D7).

    Returned by ``LLMService.for_role``; injects the role's model into each call
    while still routing through the service's single inference lane. Callers use
    ``llm.for_role("planner").chat(...)`` and never learn the model name.
    """

    __slots__ = ("_service", "_role", "_model")

    def __init__(self, service: "LLMService", role: str, model: str) -> None:
        self._service = service
        self._role = role
        self._model = model

    @property
    def role(self) -> str:
        return self._role

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str, **options: Any) -> LLMResponse:
        options.setdefault("model", self._model)
        return self._service.generate(prompt, **options)

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        options.setdefault("model", self._model)
        return self._service.chat(messages, **options)

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        options.setdefault("model", self._model)
        return self._service.embed(texts, **options)


class LLMService:
    name = "llm"

    def __init__(
        self,
        provider: "LLMProvider",
        *,
        model: str,
        embedding_model: str,
        roles: dict[str, str] | None = None,
        max_concurrency: int = 1,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._embedding_model = embedding_model
        # role -> model name. Always contains at least chat/embed (seeded by config).
        self._roles = dict(roles or {})
        self._roles.setdefault("chat", model)
        self._roles.setdefault("embed", embedding_model)
        self._max_concurrency = max(1, int(max_concurrency))
        self._lane = threading.BoundedSemaphore(self._max_concurrency)
        self._warned_roles: set[str] = set()
        self._logger = logger or logging.getLogger("atlas.llm")

    # --- capability API -------------------------------------------------
    def generate(self, prompt: str, **options: Any) -> LLMResponse:
        with self._lane, timer("llm.generate"):
            return self._provider.generate(prompt, **options)

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        with self._lane, timer("llm.chat"):
            return self._provider.chat(messages, **options)

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        with self._lane, timer("llm.embed", batch=len(texts)):
            return self._provider.embed(texts, **options)

    # --- roles (D7) -----------------------------------------------------
    def model_for_role(self, role: str) -> str:
        """Resolve a role to a model name, falling back to the chat model.

        A missing role is not fatal (it may just not be configured yet); we warn
        once and use the chat model so the caller still gets an answer.
        """
        model = self._roles.get(role)
        if model is None:
            if role not in self._warned_roles:
                self._logger.warning(
                    "LLM role '%s' not configured; falling back to chat model '%s'",
                    role,
                    self._model,
                )
                self._warned_roles.add(role)
            return self._model
        return model

    def for_role(self, role: str) -> RoleClient:
        """Return a role-bound client (chat/planner/researcher/...)."""
        return RoleClient(self, role, self.model_for_role(role))

    @property
    def roles(self) -> dict[str, str]:
        return dict(self._roles)

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
        # Non-chat roles (planner/researcher/...) may reference models that are not
        # pulled yet — reported here for visibility but not counted against health,
        # since S10 only exercises chat + embed.
        role_status = {
            role: self._model_available(name, models)
            for role, name in sorted(self._roles.items())
        }
        return HealthStatus(
            healthy=chat_ok,
            detail=detail,
            data={
                "models": models,
                "chat_model_ready": chat_ok,
                "embedding_model_ready": embed_ok,
                "roles": self._roles,
                "roles_ready": role_status,
                "max_concurrency": self._max_concurrency,
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
