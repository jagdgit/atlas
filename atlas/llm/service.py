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
import time
from contextlib import contextmanager
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
        options.setdefault("_atlas_role", self._role)
        return self._service.generate(prompt, **options)

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        options.setdefault("model", self._model)
        options.setdefault("_atlas_role", self._role)
        return self._service.chat(messages, **options)

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        options.setdefault("model", self._model)
        options.setdefault("_atlas_role", self._role)
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
        resource_manager: Any | None = None,
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
        self._resources = resource_manager
        self._warned_roles: set[str] = set()
        self._logger = logger or logging.getLogger("atlas.llm")
        # OI-CU0 A1 — counters by CU lane (chat/market/research/background)
        self._cu_lane_calls: dict[str, int] = {}
        self._cu_lane_busy_hits: dict[str, int] = {}
        self._cu_lock = threading.Lock()

    # --- capability API -------------------------------------------------
    def generate(self, prompt: str, **options: Any) -> LLMResponse:
        role = str(options.pop("_atlas_role", "generate"))
        purpose = options.pop("_atlas_purpose", None)
        self._note_cu_lane_call(role)
        return self._call_instrumented(
            "generate",
            role,
            lambda: self._provider.generate(prompt, **options),
            purpose=purpose,
            model=options.get("model"),
        )

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        from atlas.llm.provider import coerce_chat_messages

        role = str(options.pop("_atlas_role", "chat"))
        purpose = options.pop("_atlas_purpose", None)
        self._note_cu_lane_call(role)
        normalized = coerce_chat_messages(list(messages or []))
        return self._call_instrumented(
            "chat",
            role,
            lambda: self._provider.chat(normalized, **options),
            purpose=purpose,
            model=options.get("model"),
        )

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        role = str(options.pop("_atlas_role", "embed"))
        purpose = options.pop("_atlas_purpose", None)
        self._note_cu_lane_call(role)
        return self._call_instrumented(
            "embed",
            role,
            lambda: self._provider.embed(texts, **options),
            purpose=purpose,
            model=options.get("model"),
            timer_kwargs={"batch": len(texts)},
        )

    def _call_instrumented(
        self,
        kind: str,
        role: str,
        fn,
        *,
        purpose: str | None = None,
        model: str | None = None,
        timer_kwargs: dict[str, Any] | None = None,
    ):
        """Acquire lane (measure queue wait) → call provider (measure generate)."""
        from atlas.investment.llm_lanes import LLMLaneBusy, cu_lane_for_role
        from atlas.llm.fitness_ledger import record_inference, timed_ms

        lane = cu_lane_for_role(role)
        model_name = model or self.model_for_role(role)
        t_all = time.perf_counter()
        queue_wait_ms: float | None = None
        generate_ms: float | None = None
        try:
            t_q = time.perf_counter()
            with self._lane_context(role):
                queue_wait_ms = timed_ms(t_q)
                t_g = time.perf_counter()
                try:
                    metric = f"llm.{kind}"
                    with timer(metric, **(timer_kwargs or {})):
                        result = fn()
                    generate_ms = timed_ms(t_g)
                except Exception as exc:  # noqa: BLE001
                    generate_ms = timed_ms(t_g)
                    err_l = str(exc).lower()
                    outcome = (
                        "timeout"
                        if ("timeout" in err_l or "timed out" in err_l)
                        else "error"
                    )
                    record_inference(
                        lane=lane,
                        role=role,
                        model=model_name,
                        kind=kind,
                        outcome=outcome,
                        queue_wait_ms=queue_wait_ms,
                        generate_ms=generate_ms,
                        total_ms=timed_ms(t_all),
                        purpose=str(purpose) if purpose else None,
                        error=f"{type(exc).__name__}: {exc}"[:300],
                    )
                    raise
            usage = getattr(result, "usage", None) if not isinstance(result, list) else None
            if hasattr(result, "model") and result.model:
                model_name = result.model
            record_inference(
                lane=lane,
                role=role,
                model=model_name,
                kind=kind,
                outcome="ok",
                queue_wait_ms=queue_wait_ms,
                generate_ms=generate_ms,
                total_ms=timed_ms(t_all),
                purpose=str(purpose) if purpose else None,
                usage=usage if isinstance(usage, dict) else None,
            )
            return result
        except LLMLaneBusy as exc:
            record_inference(
                lane=lane,
                role=role,
                model=model_name,
                kind=kind,
                outcome="lane_busy",
                queue_wait_ms=0.0,
                generate_ms=0.0,
                total_ms=timed_ms(t_all),
                purpose=str(purpose) if purpose else None,
                error=str(exc)[:300],
            )
            raise

    def _note_cu_lane_call(self, role: str) -> None:
        try:
            from atlas.investment.llm_lanes import cu_lane_for_role

            lane = cu_lane_for_role(role)
        except Exception:  # noqa: BLE001
            lane = "chat" if role == "chat" else "background"
        with self._cu_lock:
            self._cu_lane_calls[lane] = int(self._cu_lane_calls.get(lane) or 0) + 1

    def _lane_context(self, kind: str):
        """Use the kernel-owned global lane when Resource Manager is wired (CU.A2)."""
        if self._resources is not None:
            return self._resources.llm_lane(kind=kind)
        # Local semaphore fallback — same admit policy without ResourceManager.
        try:
            from atlas.investment.llm_lanes import (
                LLMLaneBusy,
                cu_lane_for_role,
                lane_acquire_blocking,
            )

            cu = cu_lane_for_role(kind)
            may_block = lane_acquire_blocking(cu)
        except Exception:  # noqa: BLE001
            cu = str(kind or "chat")
            may_block = True
            LLMLaneBusy = RuntimeError  # type: ignore[misc, assignment]

        @contextmanager
        def _local():
            if may_block:
                self._lane.acquire()
            else:
                if not self._lane.acquire(blocking=False):
                    with self._cu_lock:
                        self._cu_lane_busy_hits[cu] = (
                            int(self._cu_lane_busy_hits.get(cu) or 0) + 1
                        )
                    raise LLMLaneBusy(cu)
            try:
                yield
            finally:
                self._lane.release()

        return _local()

    # --- roles (D7) -----------------------------------------------------
    def honest_roster(self) -> dict[str, Any]:
        """CLC.R2 — one local reasoner + embed. Roles are lanes, not weights."""
        reasoner = self._model
        embed = self._embedding_model
        distinct = {str(v) for v in self._roles.values() if v}
        unused = [
            name
            for name in ("llama3:latest", "llama3", "gemma3", "gemma3:latest")
            if name not in distinct and name != reasoner and name != embed
        ]
        return {
            "version": "clc.r2.honest_roster.v1",
            "reasoner": reasoner,
            "embed": embed,
            "vision": "not installed",
            "unused": unused,
            "roles_are_lanes": True,
            "roles": dict(self._roles),
            "honesty": (
                f"one local reasoner ({reasoner}) + embed ({embed}). "
                "Role names (planner/scientist/market) are lanes, not different "
                "weights. vision=gemma3 is not installed. llama3:latest is unused."
            ),
        }

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

    def lane_busy(self) -> bool:
        """PLC.F6 — True when the inference lane is currently held (non-blocking probe)."""
        if self._resources is not None:
            try:
                decision = self._resources.can_admit(cost_units=0, llm_slots=1)
                if not getattr(decision, "allowed", True):
                    with self._cu_lock:
                        self._cu_lane_busy_hits["probe"] = (
                            int(self._cu_lane_busy_hits.get("probe") or 0) + 1
                        )
                    return True
            except Exception:  # noqa: BLE001
                pass
        # Probe local semaphore without waiting.
        acquired = self._lane.acquire(blocking=False)
        if not acquired:
            with self._cu_lock:
                self._cu_lane_busy_hits["probe"] = (
                    int(self._cu_lane_busy_hits.get("probe") or 0) + 1
                )
            return True
        self._lane.release()
        return False

    def lane_status(self) -> dict[str, Any]:
        busy = self.lane_busy()
        with self._cu_lock:
            calls = dict(self._cu_lane_calls)
            busy_hits = dict(self._cu_lane_busy_hits)
        return {
            "busy": busy,
            "max_concurrency": self._max_concurrency,
            "cu_lanes": calls,
            "cu_busy_probes": busy_hits,
            "honesty": (
                "Bounded concurrency (CU.A2) — chat/market may wait; "
                "daytime research/background defer when saturated; "
                "no blind concurrency raise"
                if busy
                else "LLM lane free"
            ),
        }

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
        data = {
            "models": models,
            "chat_model_ready": chat_ok,
            "embedding_model_ready": embed_ok,
            "roles": self._roles,
            "roles_ready": role_status,
            "max_concurrency": self._max_concurrency,
            "honest_roster": self.honest_roster(),
        }
        # Chat missing ⇒ can't do the main job (failed). Chat present but embedding
        # not pulled ⇒ up but below full capability (degraded, S22), not a failure.
        if not chat_ok:
            return HealthStatus.fail(detail, **data)
        if not embed_ok:
            return HealthStatus.degraded_status(detail, **data)
        return HealthStatus.ok(detail, **data)

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
