"""Conversation service — sessions, history, and context assembly (D3).

Kernel-managed capability. Owns the conversation transcript and turns it into the
context a turn needs: the recent messages plus any relevant *working memories*
(``memory.items`` scoped to the session id, ADR-0048). It never routes or answers
— that is the Planner / AssistantService. Keeping transcript (what was said) apart
from memory (what to keep) is deliberate (D3).

Mode-agnostic by design (D1): the same session/history primitives back a
synchronous chat turn now and will back an asynchronous job's conversation later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas.llm.provider import ChatMessage
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.models import ConversationMessage, ConversationSession, MemoryItem
    from atlas.repositories.conversation_repo import ConversationRepository
    from atlas.services.memory_service import MemoryService


@dataclass(frozen=True)
class ConversationContext:
    """Assembled context for one turn: recent transcript + relevant memories.

    Optional ``job_id`` / ``activity`` / ``workspace`` are set by the Job Engine
    (Stage 3, Step 5 fast-follow) so a research step can stream into the live
    activity feed and write artifacts into the per-job workspace.
    """

    session_id: str
    recent: "list[ConversationMessage]" = field(default_factory=list)
    memories: "list[MemoryItem]" = field(default_factory=list)
    job_id: str | None = None
    activity: Any = None
    workspace: Any = None

    def as_chat_messages(self) -> list[ChatMessage]:
        """Recent transcript as LLM chat messages (oldest→newest)."""
        return [ChatMessage(m.role, m.content) for m in self.recent if m.content]

    def memory_block(self) -> str:
        """Relevant memories rendered as a plain text block (or empty)."""
        if not self.memories:
            return ""
        return "\n".join(f"- {m.content}" for m in self.memories)


class ConversationService:
    name = "conversation"

    def __init__(
        self,
        repo: "ConversationRepository",
        memory: "MemoryService | None" = None,
        *,
        max_context_turns: int = 10,
        working_memory_k: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._memory = memory
        self._max_context_turns = max_context_turns
        self._working_memory_k = working_memory_k
        self._logger = logger or logging.getLogger("atlas.conversation")

    # --- sessions -------------------------------------------------------
    def start_session(
        self, *, title: str | None = None, metadata: dict[str, Any] | None = None
    ) -> "ConversationSession":
        session = self._repo.create_session(title=title, metadata=metadata)
        self._logger.info("started conversation session %s", session.id)
        return session

    def get_session(self, session_id: str) -> "ConversationSession | None":
        return self._repo.get_session(session_id)

    def list_sessions(self, *, limit: int = 50) -> "list[ConversationSession]":
        return self._repo.list_sessions(limit=limit)

    def ensure_session(self, session_id: str | None) -> "ConversationSession":
        """Return the referenced session, or start a new one if id is None/unknown."""
        if session_id:
            existing = self._repo.get_session(session_id)
            if existing is not None:
                return existing
        return self.start_session()

    # --- messages -------------------------------------------------------
    def add_user_message(self, session_id: str, content: str) -> "ConversationMessage":
        return self._repo.add_message(session_id, "user", content)

    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> "ConversationMessage":
        return self._repo.add_message(
            session_id, "assistant", content, tool_calls=tool_calls
        )

    def history(
        self, session_id: str, *, limit: int | None = None
    ) -> "list[ConversationMessage]":
        return self._repo.history(session_id, limit=limit)

    # --- context assembly ----------------------------------------------
    def build_context(self, session_id: str, query: str) -> ConversationContext:
        """Assemble recent turns + relevant working memories for this turn."""
        recent = self._repo.history(session_id, limit=self._max_context_turns)
        memories: "list[MemoryItem]" = []
        if self._memory is not None and query.strip() and self._working_memory_k > 0:
            try:
                memories = self._memory.recall(
                    query, scope=session_id, limit=self._working_memory_k
                )
            except Exception:  # noqa: BLE001 - context enrichment is best-effort
                self._logger.exception("working-memory recall failed for context")
        return ConversationContext(
            session_id=session_id, recent=recent, memories=memories
        )

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            count = self._repo.count_sessions()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"conversation store unreachable: {exc}")
        return HealthStatus.ok(f"{count} session(s)", sessions=count)
