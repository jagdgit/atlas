"""Typed exception hierarchy for Atlas (ADR-0037).

    AtlasError
    ├── ConfigError
    ├── DatabaseError        (DatabaseConnectionError, MigrationError, QueryError)
    ├── LLMError             (ProviderUnreachableError, ModelMissingError, GenerationError)
    ├── KnowledgeError       (IngestError, EmbeddingMismatchError, SearchError)
    ├── AgentError           (AgentNotFoundError, AgentRunError)
    └── PluginError          (PluginLoadError, CapabilityMissingError,
                              ToolError → ToolNotFoundError)

Catch broadly with ``except AtlasError`` or precisely with a domain subclass.
"""

from __future__ import annotations

from atlas.exceptions.agent import AgentError, AgentNotFoundError, AgentRunError
from atlas.exceptions.base import AtlasError
from atlas.exceptions.config import ConfigError
from atlas.exceptions.database import (
    DatabaseConnectionError,
    DatabaseError,
    MigrationError,
    QueryError,
)
from atlas.exceptions.knowledge import (
    EmbeddingMismatchError,
    IngestError,
    KnowledgeError,
    SearchError,
)
from atlas.exceptions.llm import (
    GenerationError,
    LLMError,
    ModelMissingError,
    ProviderUnreachableError,
)
from atlas.exceptions.plugin import (
    CapabilityMissingError,
    PluginError,
    PluginLoadError,
    ToolError,
    ToolNotFoundError,
)

__all__ = [
    "AtlasError",
    "ConfigError",
    "DatabaseError",
    "DatabaseConnectionError",
    "MigrationError",
    "QueryError",
    "LLMError",
    "ProviderUnreachableError",
    "ModelMissingError",
    "GenerationError",
    "KnowledgeError",
    "IngestError",
    "EmbeddingMismatchError",
    "SearchError",
    "AgentError",
    "AgentNotFoundError",
    "AgentRunError",
    "PluginError",
    "PluginLoadError",
    "CapabilityMissingError",
    "ToolError",
    "ToolNotFoundError",
]
