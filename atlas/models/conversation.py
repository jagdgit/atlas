"""Conversation-domain models: ConversationSession, ConversationMessage (D3).

A session is a multi-turn thread; a message is one ordered turn within it. These
map ``conversation.sessions`` / ``conversation.messages`` rows (ADR-0036). The
transcript is distinct from remembered facts (``memory.items``): the session is
*what was said*, memory is *what to keep*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class ConversationSession(Model):
    id: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConversationMessage(Model):
    id: str
    session_id: str
    ordinal: int
    role: str  # 'user' | 'assistant' | 'system'
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None
