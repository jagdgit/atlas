"""Per-template Work Resource Profiles (IR-RO3).

Seeded into ``success_criteria.resources`` via :func:`with_resources` (called from
:func:`atlas.missions.philosophy.with_philosophy` so builtins stay one-line).
"""

from __future__ import annotations

from typing import Any

from atlas.core.resources.work_profile import (
    CHECKPOINT_NONE,
    CHECKPOINT_PER_FILE,
    CHECKPOINT_PER_TICK,
    DEADLINE_NONE,
    DEADLINE_SESSION,
    DEADLINE_SIGNAL_TTL,
    DEADLINE_SOFT,
    SERVICE_BATCH,
    SERVICE_INTERACTIVE,
    SERVICE_NORMAL,
    SERVICE_REALTIME,
    WorkResourceProfile,
)

# Source of truth for builtin template resource declarations.
TEMPLATE_RESOURCES: dict[str, WorkResourceProfile] = {
    "hello_watcher": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=300,
        criticality="low",
        scheduling_policy="background",
        cpu="low",
        ram_mb=128,
        expected_tick_ms=1_000,
        checkpointability=CHECKPOINT_NONE,
    ),
    "market_observer": WorkResourceProfile(
        service_class=SERVICE_REALTIME,
        latency_tolerance_seconds=5,
        deadline_policy=DEADLINE_SIGNAL_TTL,
        criticality="critical",
        scheduling_policy="realtime",
        cpu="low",
        ram_mb=256,
        network="medium",
        expected_tick_ms=2_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "paper_trading": WorkResourceProfile(
        service_class=SERVICE_REALTIME,
        latency_tolerance_seconds=60,
        deadline_policy=DEADLINE_SIGNAL_TTL,
        criticality="critical",
        scheduling_policy="realtime",
        cpu="low",
        ram_mb=256,
        network="medium",
        llm="no",
        expected_tick_ms=3_000,
    ),
    "decision_simulation": WorkResourceProfile(
        service_class=SERVICE_REALTIME,
        latency_tolerance_seconds=60,
        deadline_policy=DEADLINE_SIGNAL_TTL,
        criticality="critical",
        scheduling_policy="realtime",
        cpu="low",
        ram_mb=256,
        network="medium",
        llm="no",
        expected_tick_ms=5_000,
    ),
    "portfolio_ledger": WorkResourceProfile(
        service_class=SERVICE_INTERACTIVE,
        latency_tolerance_seconds=300,
        deadline_policy=DEADLINE_SOFT,
        criticality="high",
        scheduling_policy="background",
        cpu="low",
        ram_mb=256,
        llm="no",
        expected_tick_ms=5_000,
    ),
    "investment_universe": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        deadline_policy=DEADLINE_SESSION,
        criticality="high",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=512,
        network="medium",
        expected_tick_ms=30_000,
    ),
    "opportunity_discovery": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        deadline_policy=DEADLINE_SESSION,
        criticality="normal",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=512,
        network="medium",
        expected_tick_ms=45_000,
    ),
    "company_intelligence": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=512,
        disk_io="medium",
        storage_growth="medium",
        network="medium",
        llm="yes",
        expected_tick_ms=60_000,
    ),
    "news_intelligence": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="medium",
        storage_growth="low",
        expected_tick_ms=20_000,
    ),
    "event_research": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        criticality="normal",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=512,
        network="medium",
        expected_tick_ms=45_000,
    ),
    "research": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="batch",
        cpu="medium",
        ram_mb=768,
        disk_io="medium",
        storage_growth="high",
        network="medium",
        expected_tick_ms=300_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "knowledge_verification": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        criticality="normal",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=512,
        expected_tick_ms=60_000,
    ),
    "repository_learning": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="background",
        cpu="medium",
        ram_mb=768,
        disk_io="high",
        storage_growth="medium",
        expected_tick_ms=60_000,
        checkpointability=CHECKPOINT_PER_FILE,
    ),
    "owner_knowledge": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=3 * 86400,
        deadline_policy=DEADLINE_NONE,
        criticality="low",
        scheduling_policy="batch",
        cpu="medium",
        ram_mb=512,
        disk_io="high",
        storage_growth="high",
        expected_tick_ms=60_000,
        checkpointability=CHECKPOINT_PER_FILE,
    ),
    "government_intelligence": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=256,
        expected_tick_ms=15_000,
    ),
    "investor_reports": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=256,
        expected_tick_ms=20_000,
    ),
    "investment_mentor": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=7 * 86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=384,
        expected_tick_ms=120_000,
    ),
    "engineering_mentor": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=7 * 86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=384,
        expected_tick_ms=120_000,
    ),
    "personal_mentor": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=7 * 86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=384,
        expected_tick_ms=120_000,
    ),
    "learning_governance": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=256,
        expected_tick_ms=60_000,
    ),
    "system_introspection": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        criticality="low",
        scheduling_policy="idle",
        cpu="low",
        ram_mb=256,
        expected_tick_ms=30_000,
    ),
    "self_improvement": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=7 * 86400,
        criticality="low",
        scheduling_policy="idle",
        cpu="low",
        ram_mb=384,
        expected_tick_ms=120_000,
    ),
    "technology_watch": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="medium",
        expected_tick_ms=60_000,
    ),
    "security_monitoring": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=3600,
        deadline_policy=DEADLINE_SOFT,
        criticality="high",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="medium",
        expected_tick_ms=60_000,
    ),
    "career_observer": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        deadline_policy=DEADLINE_SOFT,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=384,
        network="low",
        disk_io="medium",
        expected_tick_ms=45_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "career_research": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        deadline_policy=DEADLINE_SOFT,
        criticality="low",
        scheduling_policy="batch",
        cpu="low",
        ram_mb=384,
        network="low",
        expected_tick_ms=45_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "job_hunting": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="medium",
        expected_tick_ms=60_000,
    ),
    "patent_watch": WorkResourceProfile(
        service_class=SERVICE_NORMAL,
        latency_tolerance_seconds=86400,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="medium",
        expected_tick_ms=60_000,
    ),
    # IRA.21 — Investing Research workers: bounded RAM + cooperative yield (not OS process isolation).
    "research_freshness": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        deadline_policy=DEADLINE_SOFT,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=384,
        network="low",
        expected_tick_ms=45_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "fundamentals_enrich": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        deadline_policy=DEADLINE_SOFT,
        criticality="low",
        scheduling_policy="background",
        cpu="low",
        ram_mb=256,
        network="medium",
        expected_tick_ms=60_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
    "thesis_outcome": WorkResourceProfile(
        service_class=SERVICE_BATCH,
        latency_tolerance_seconds=86400,
        deadline_policy=DEADLINE_SOFT,
        criticality="normal",
        scheduling_policy="background",
        cpu="low",
        ram_mb=256,
        network="low",
        expected_tick_ms=30_000,
        checkpointability=CHECKPOINT_PER_TICK,
    ),
}


def resources_for(template_name: str) -> WorkResourceProfile:
    return TEMPLATE_RESOURCES.get(template_name) or WorkResourceProfile()


def resources_dict_for(template_name: str) -> dict[str, Any]:
    return resources_for(template_name).as_dict()


def with_resources(
    success_criteria: dict[str, Any] | None, template_name: str
) -> dict[str, Any]:
    """Merge ``resources`` block into template success_criteria for seeding."""
    out = dict(success_criteria or {})
    out["resources"] = resources_dict_for(template_name)
    return out


def profile_from_template_criteria(
    success_criteria: dict[str, Any] | None,
    *,
    template_name: str | None = None,
) -> WorkResourceProfile:
    """Read profile from seeded criteria, falling back to TEMPLATE_RESOURCES."""
    sc = success_criteria or {}
    raw = sc.get("resources")
    if isinstance(raw, dict) and raw.get("service_class"):
        from atlas.core.resources.work_profile import profile_from_dict

        return profile_from_dict(raw)
    if template_name:
        return resources_for(template_name)
    return WorkResourceProfile()
