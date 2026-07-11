"""Atlas repositories — the only layer that contains SQL (ADR-0027)."""

from __future__ import annotations

from atlas.repositories.base import BaseRepository
from atlas.repositories.chunk_repo import ChunkRepository
from atlas.repositories.document_repo import DocumentRepository
from atlas.repositories.embedding_repo import EmbeddingRepository
from atlas.repositories.event_repo import EventRepository
from atlas.repositories.health_repo import HealthRepository
from atlas.repositories.memory_repo import MemoryRepository
from atlas.repositories.settings_repo import SettingsRepository
from atlas.repositories.task_repo import TaskRepository

__all__ = [
    "BaseRepository",
    "ChunkRepository",
    "DocumentRepository",
    "EmbeddingRepository",
    "EventRepository",
    "HealthRepository",
    "MemoryRepository",
    "SettingsRepository",
    "TaskRepository",
]
