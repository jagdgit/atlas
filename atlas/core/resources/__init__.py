"""Kernel resource stewardship (Stage 3.2c)."""

from atlas.core.resources.manager import AdmissionDecision, PoolRecommendation, ResourceManager
from atlas.core.resources.monitor import SystemSnapshot, read_snapshot
from atlas.core.resources.profiles import PROFILES, ResourceProfile, get_profile

__all__ = [
    "PROFILES",
    "AdmissionDecision",
    "PoolRecommendation",
    "ResourceManager",
    "ResourceProfile",
    "SystemSnapshot",
    "get_profile",
    "read_snapshot",
]
