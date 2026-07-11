"""Memory service — remember / recall / forget over ``memory.items``.

Kernel-managed capability implementing ``MemoryProvider`` (ADR-0038). Ties the
memory repository to the LLM embedding backend:

    remember(content, kind) -> embed (semantic/episodic) -> store
    recall(query)           -> embed query -> cosine search over embedded, live rows

Three kinds (ADR-0048):
    working   — short-term; gets a TTL (``expires_at``); not embedded by default
    episodic  — event log; time-ordered by ``occurred_at``; embedded for recall
    semantic  — durable facts; embedded for recall

Recall filters expired rows; a periodic ``memory_prune`` scheduler task reclaims
them (crash-safe, like the ingestion scan).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from atlas.services.base import HealthStatus
from atlas.telemetry import timer

if TYPE_CHECKING:
    from atlas.llm.service import LLMService
    from atlas.models import MemoryItem
    from atlas.repositories.memory_repo import MemoryRepository

_EMBEDDED_KINDS = {"episodic", "semantic"}


class MemoryService:
    name = "memory"

    def __init__(
        self,
        repo: "MemoryRepository",
        llm: "LLMService",
        *,
        embedding_model: str,
        recall_k: int = 5,
        similarity_floor: float = 0.0,
        working_ttl_seconds: int = 3600,
        embed_working: bool = False,
        prune_interval: int = 0,
        enqueue: "Callable[..., Any] | None" = None,
        count_pending: "Callable[[str], int] | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm
        self._model = embedding_model
        self._recall_k = recall_k
        self._floor = similarity_floor
        self._working_ttl = working_ttl_seconds
        self._embed_working = embed_working
        self._prune_interval = prune_interval
        self._enqueue = enqueue
        self._count_pending = count_pending
        self._logger = logger or logging.getLogger("atlas.memory")

    # --- capability API (MemoryProvider) --------------------------------
    def remember(
        self,
        content: str,
        *,
        kind: str = "semantic",
        scope: str = "global",
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
        ttl_seconds: int | None = None,
        embed: bool | None = None,
    ) -> "MemoryItem":
        """Store a memory. Embeds semantic/episodic content by default so it is
        recallable; working memory gets a TTL and is not embedded unless asked."""
        should_embed = self._should_embed(kind) if embed is None else embed
        vector = None
        model = None
        if should_embed and content.strip():
            with timer("memory.embed"):
                vector = self._llm.embed([content], model=self._model).vectors[0]
            model = self._model

        expires_at = self._expiry(kind, ttl_seconds)
        item = self._repo.add(
            kind,
            content,
            scope=scope,
            embedding=vector,
            embedding_model=model,
            importance=importance,
            metadata=metadata,
            occurred_at=occurred_at,
            expires_at=expires_at,
        )
        self._logger.info("remembered %s memory %s (scope=%s)", kind, item.id, scope)
        return item

    def recall(
        self,
        query: str,
        *,
        limit: int | None = None,
        kind: str | None = None,
        scope: str | None = None,
        **_: Any,
    ) -> "list[MemoryItem]":
        """Semantic recall: most-similar, non-expired memories above the floor."""
        k = limit or self._recall_k
        with timer("memory.recall"):
            vector = self._llm.embed([query], model=self._model).vectors[0]
            results = self._repo.semantic_search(vector, kind=kind, scope=scope, limit=k)
        return [r for r in results if (r.similarity or 0.0) >= self._floor]

    def recent(
        self, *, kind: str | None = None, scope: str | None = None, limit: int = 20
    ) -> "list[MemoryItem]":
        return self._repo.recent(kind=kind, scope=scope, limit=limit)

    def forget(self, memory_id: str) -> bool:
        return self._repo.forget(memory_id)

    def prune(self) -> int:
        removed = self._repo.prune_expired()
        if removed:
            self._logger.info("pruned %d expired memory item(s)", removed)
        return removed

    # --- scheduler integration -----------------------------------------
    def prune_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scheduler handler for task_type 'memory_prune'.

        Re-enqueues itself after ``prune_interval`` seconds so expiry cleanup is
        durable across restarts (same pattern as ``ingest_scan``).
        """
        removed = self.prune()
        if self._enqueue is not None and self._prune_interval > 0:
            self._enqueue(
                "memory_prune", {}, delay_seconds=float(self._prune_interval)
            )
        return {"pruned": removed}

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        """Seed a durable prune chain on startup (idempotent across restarts)."""
        if self._enqueue is None or self._prune_interval <= 0:
            return
        if self._count_pending is not None and self._count_pending("memory_prune") > 0:
            self._logger.info("memory_prune already queued; not seeding another")
            return
        self._enqueue("memory_prune", {}, delay_seconds=float(self._prune_interval))
        self._logger.info(
            "seeded initial memory_prune (interval %ds)", self._prune_interval
        )
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            count = self._repo.count()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"memory store unreachable: {exc}")
        return HealthStatus.ok(f"{count} memories", count=count)

    # --- internals ------------------------------------------------------
    def _should_embed(self, kind: str) -> bool:
        if kind == "working":
            return self._embed_working
        return kind in _EMBEDDED_KINDS

    def _expiry(self, kind: str, ttl_seconds: int | None) -> datetime | None:
        ttl = ttl_seconds if ttl_seconds is not None else (
            self._working_ttl if kind == "working" else None
        )
        if not ttl or ttl <= 0:
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=ttl)
