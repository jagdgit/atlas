"""Kernel-level system services (Phase 0, ATLAS_OS_ROADMAP §5.7+).

Small, shared, permanent services that belong to Atlas itself rather than to any
Mission or Intelligence — e.g. the :class:`~atlas.system.time.ClockService`.
"""

from __future__ import annotations

from atlas.system.time import ClockService, NtpStatus
from atlas.system.versioning import (
    KNOWLEDGE_SCHEMA_VERSION,
    ArtifactVersions,
    build_artifact_versions,
)

__all__ = [
    "ClockService",
    "NtpStatus",
    "ArtifactVersions",
    "build_artifact_versions",
    "KNOWLEDGE_SCHEMA_VERSION",
]
