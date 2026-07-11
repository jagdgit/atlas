"""Conversation layer (Sprint 10, D3).

First-class multi-turn state: sessions, ordered message history, and assembled
context (recent turns + relevant working memories). The transcript lives in the
``conversation`` schema; remembered facts stay in ``memory.items`` scoped to the
session id (ADR-0048) — kept deliberately separate.
"""

from __future__ import annotations

from atlas.conversation.service import ConversationContext, ConversationService

__all__ = ["ConversationService", "ConversationContext"]
