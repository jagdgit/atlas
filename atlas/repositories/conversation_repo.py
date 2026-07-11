"""Repository for ``conversation.sessions`` / ``conversation.messages`` (ADR-0027).

The only SQL layer for conversation state. Returns typed models (ADR-0036).
Message ordinals are assigned server-side in a single INSERT (``max(ordinal)+1``)
so concurrent turns on the same session can't collide on the unique
``(session_id, ordinal)`` constraint.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models import ConversationMessage, ConversationSession
from atlas.repositories.base import BaseRepository

VALID_ROLES = {"user", "assistant", "system"}

_SESSION_COLS = "id, title, metadata, created_at, updated_at"
_MESSAGE_COLS = "id, session_id, ordinal, role, content, tool_calls, created_at"


class ConversationRepository(BaseRepository):
    # --- sessions -------------------------------------------------------
    def create_session(
        self,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationSession:
        row = self.fetch_one(
            f"""
            INSERT INTO conversation.sessions (title, metadata)
            VALUES (%s, %s)
            RETURNING {_SESSION_COLS}
            """,
            (title, Jsonb(metadata or {})),
        )
        return ConversationSession.from_row(row)

    def get_session(self, session_id: UUID | str) -> ConversationSession | None:
        row = self.fetch_one(
            f"SELECT {_SESSION_COLS} FROM conversation.sessions WHERE id = %s",
            (str(session_id),),
        )
        return ConversationSession.from_row(row) if row else None

    def list_sessions(self, *, limit: int = 50) -> list[ConversationSession]:
        rows = self.fetch_all(
            f"""
            SELECT {_SESSION_COLS} FROM conversation.sessions
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return ConversationSession.from_rows(rows)

    def touch_session(self, session_id: UUID | str) -> None:
        self.execute(
            "UPDATE conversation.sessions SET updated_at = now() WHERE id = %s",
            (str(session_id),),
        )

    # --- messages -------------------------------------------------------
    def add_message(
        self,
        session_id: UUID | str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> ConversationMessage:
        if role not in VALID_ROLES:
            raise ValueError(f"invalid message role: {role}")
        row = self.fetch_one(
            f"""
            INSERT INTO conversation.messages
                (session_id, ordinal, role, content, tool_calls)
            VALUES (
                %s,
                COALESCE(
                    (SELECT max(ordinal) + 1 FROM conversation.messages
                     WHERE session_id = %s),
                    0
                ),
                %s, %s, %s
            )
            RETURNING {_MESSAGE_COLS}
            """,
            (
                str(session_id),
                str(session_id),
                role,
                content,
                Jsonb(tool_calls or []),
            ),
        )
        self.touch_session(session_id)
        return ConversationMessage.from_row(row)

    def history(
        self, session_id: UUID | str, *, limit: int | None = None
    ) -> list[ConversationMessage]:
        """Return the session's messages in chronological order.

        With ``limit``, return the *most recent* ``limit`` messages, still ordered
        oldest→newest (so they drop straight into a prompt).
        """
        if limit is None:
            rows = self.fetch_all(
                f"""
                SELECT {_MESSAGE_COLS} FROM conversation.messages
                WHERE session_id = %s
                ORDER BY ordinal ASC
                """,
                (str(session_id),),
            )
        else:
            rows = self.fetch_all(
                f"""
                SELECT * FROM (
                    SELECT {_MESSAGE_COLS} FROM conversation.messages
                    WHERE session_id = %s
                    ORDER BY ordinal DESC
                    LIMIT %s
                ) recent
                ORDER BY ordinal ASC
                """,
                (str(session_id), limit),
            )
        return ConversationMessage.from_rows(rows)

    def count_sessions(self) -> int:
        return self.fetch_val("SELECT count(*) FROM conversation.sessions") or 0

    def count_messages(self, session_id: UUID | str) -> int:
        return (
            self.fetch_val(
                "SELECT count(*) FROM conversation.messages WHERE session_id = %s",
                (str(session_id),),
            )
            or 0
        )
