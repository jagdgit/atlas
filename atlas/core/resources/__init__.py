"""Kernel resource stewardship (Stage 3.2c + IR-RO1/RO2/RO3)."""

from atlas.core.resources.admission import (
    AdmissionContract,
    ResourcePlanner,
    WorkEstimate,
)
from atlas.core.resources.manager import AdmissionDecision, PoolRecommendation, ResourceManager
from atlas.core.resources.memory_watchdog import RuntimeMemoryWatchdog, process_rss_mb
from atlas.core.resources.mission_queue import (
    MissionQueueService,
    QUEUE_READY,
    QUEUE_WAITING_DEPENDENCY,
    QUEUE_WAITING_HOST,
)
from atlas.core.resources.monitor import SystemSnapshot, read_snapshot
from atlas.core.resources.profiles import PROFILES, ResourceProfile, get_profile
from atlas.core.resources.scheduler import CandidateSelector, ResourceScheduler
from atlas.core.resources.work_profile import (
    SERVICE_BATCH,
    SERVICE_INTERACTIVE,
    SERVICE_NORMAL,
    SERVICE_REALTIME,
    WorkResourceProfile,
    normalize_service_class,
    service_class_rank,
)

__all__ = [
    "PROFILES",
    "QUEUE_READY",
    "QUEUE_WAITING_DEPENDENCY",
    "QUEUE_WAITING_HOST",
    "CandidateSelector",
    "ResourceScheduler",
    "SERVICE_BATCH",
    "SERVICE_INTERACTIVE",
    "SERVICE_NORMAL",
    "SERVICE_REALTIME",
    "AdmissionContract",
    "AdmissionDecision",
    "MissionQueueService",
    "PoolRecommendation",
    "ResourceManager",
    "ResourcePlanner",
    "ResourceProfile",
    "RuntimeMemoryWatchdog",
    "SystemSnapshot",
    "WorkEstimate",
    "WorkResourceProfile",
    "get_profile",
    "normalize_service_class",
    "process_rss_mb",
    "read_snapshot",
    "service_class_rank",
]
