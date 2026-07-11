"""Atlas configuration package.

Usage:
    from atlas.config import get_config
    config = get_config()
    print(config.system.name)

A module-level ``config`` is also available lazily:
    from atlas.config import config
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.config.manager import (
    AtlasConfig,
    AuditConfig,
    BackupConfig,
    CodeConfig,
    ConversationConfig,
    DatabaseConfig,
    JobConfig,
    KnowledgeConfig,
    LLMConfig,
    LLMRole,
    LoggingConfig,
    MonitoringConfig,
    NetConfig,
    PathsConfig,
    ResearchConfig,
    SandboxConfig,
    SchedulerConfig,
    SystemConfig,
    get_config,
    load_config,
)

if TYPE_CHECKING:
    config: AtlasConfig

__all__ = [
    "AtlasConfig",
    "AuditConfig",
    "BackupConfig",
    "CodeConfig",
    "ConversationConfig",
    "DatabaseConfig",
    "JobConfig",
    "KnowledgeConfig",
    "LLMConfig",
    "LLMRole",
    "LoggingConfig",
    "MonitoringConfig",
    "NetConfig",
    "PathsConfig",
    "ResearchConfig",
    "SandboxConfig",
    "SchedulerConfig",
    "SystemConfig",
    "get_config",
    "load_config",
    "config",
]


def __getattr__(name: str) -> Any:
    if name == "config":
        return get_config()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
