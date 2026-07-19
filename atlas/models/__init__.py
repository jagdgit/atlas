"""Typed domain models for Atlas (ADR-0036).

Repositories map SQL rows to these models; everything above the repository layer
passes typed models instead of raw dicts. Value types already defined near their
services (``SearchResult``, ``Citation``, ``AgentResult``, LLM response types) are
re-exported here so callers have a single import site for "the shapes of things".

Migration is incremental (ADR-0036 / §18.9 F5): repositories are converted one at
a time; dict-returning methods coexist with model-returning ones until callers
move over.
"""

from __future__ import annotations

from atlas.models.agent_run import AgentRecord, AgentRun, AgentStep
from atlas.models.base import Model
from atlas.models.conversation import ConversationMessage, ConversationSession
from atlas.models.document import Chunk, Document, Embedding
from atlas.models.health import HealthRecord
from atlas.models.job import Job, JobStep
from atlas.models.learning import (
    EngineeringPattern,
    Experience,
    LearnedRepository,
    LearningEvent,
)
from atlas.models.memory import MemoryItem
from atlas.models.task import Task, TaskRun

__all__ = [
    "Model",
    "Document",
    "Chunk",
    "Embedding",
    "Task",
    "TaskRun",
    "AgentRecord",
    "AgentRun",
    "AgentStep",
    "ConversationSession",
    "ConversationMessage",
    "HealthRecord",
    "Job",
    "JobStep",
    "Experience",
    "LearningEvent",
    "LearnedRepository",
    "EngineeringPattern",
    "MemoryItem",
]
