"""Mission Manager service (Phase A · PHASE_A_PLAN §A.1).

Owns the **Mission layer above Jobs**: create + lifecycle (`draft → active → waiting →
paused → completed → archived`), the append-only **Journal** (P9 explainability — refs, not
copies), and the on-demand aggregated view (owned Jobs + Workers + journal, Q2). Missions are
**operator-created only** (Q1). Archival is **non-destructive** (B5/B9): it stops activity but
keeps everything the mission produced — the mission is provenance, not an owner of knowledge.

A Kernel Service (registered lifecycle + capability); it holds no business logic for any
specific mission type — those are templates + configs + workers (P5/P7).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from atlas.exceptions.base import AtlasError
from atlas.models.mission import (
    CRITICALITIES,
    CRIT_NORMAL,
    MISSION_ACTIVE,
    MISSION_ARCHIVED,
    MISSION_COMPLETED,
    MISSION_DRAFT,
    MISSION_PAUSED,
    MISSION_TRANSITIONS,
    MISSION_WAITING,
    POLICY_BACKGROUND,
    SCHEDULING_POLICIES,
    Mission,
)
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.missions.repository import MissionRepository

# Lifecycle action → emitted event type (durable bus → dashboard).
_EVENT_FOR_STATUS = {
    MISSION_ACTIVE: "MissionActivated",
    MISSION_WAITING: "MissionWaiting",
    MISSION_PAUSED: "MissionPaused",
    MISSION_COMPLETED: "MissionCompleted",
    MISSION_ARCHIVED: "MissionArchived",
}


class MissionError(AtlasError):
    """A mission operation was invalid (missing mission, illegal transition, bad enum)."""


class MissionService:
    name = "missions"
    VERSION = "1"

    def __init__(
        self,
        repo: "MissionRepository",
        *,
        events: "EventDispatcher | None" = None,
        schedule_repo: Any | None = None,
        worker_repo: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._events = events
        # Optional (A.3/A.4): archiving a mission disables its schedules + stops its workers.
        # Kept as loose dependencies so the Mission Manager has no hard import on those layers.
        self._schedule_repo = schedule_repo
        self._worker_repo = worker_repo
        self._logger = logger or logging.getLogger("atlas.missions")

    # --- creation -------------------------------------------------------

    def create_mission(
        self,
        title: str,
        objective: str = "",
        *,
        scheduling_policy: str = POLICY_BACKGROUND,
        priority: int = 0,
        criticality: str = CRIT_NORMAL,
        budget: dict[str, Any] | None = None,
        deadline: Any | None = None,
        importance: str | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        knowledge_domains: list[str] | None = None,
        success_criteria: dict[str, Any] | None = None,
        template_id: str | None = None,
        template_version: int | None = None,
    ) -> Mission:
        """Create a mission in ``draft`` (operator-created only, Q1); journal + emit."""
        if not (title or "").strip():
            raise MissionError("mission title is required")
        self._validate_enums(scheduling_policy, criticality, priority)
        mission = self._repo.create(
            title=title.strip(),
            objective=objective,
            scheduling_policy=scheduling_policy,
            priority=priority,
            criticality=criticality,
            budget=budget,
            deadline=deadline,
            importance=importance,
            labels=labels,
            metadata=metadata,
            knowledge_domains=knowledge_domains,
            success_criteria=success_criteria,
            template_id=template_id,
            template_version=template_version,
        )
        self._repo.add_journal(
            mission.id, "created", f"mission created: {title.strip()[:120]}",
            {"template_id": template_id, "template_version": template_version},
        )
        self._emit("MissionCreated", mission)
        self._logger.info("created mission %s: %s", mission.id, title.strip()[:80])
        return mission

    # --- lifecycle ------------------------------------------------------

    def activate(self, mission_id: UUID | str, reason: str = "") -> Mission:
        return self._transition(mission_id, MISSION_ACTIVE, "activated", reason)

    def pause(self, mission_id: UUID | str, reason: str = "") -> Mission:
        return self._transition(mission_id, MISSION_PAUSED, "paused", reason)

    def resume(self, mission_id: UUID | str, reason: str = "") -> Mission:
        # resume = back to active from paused (or waiting).
        return self._transition(mission_id, MISSION_ACTIVE, "resumed", reason)

    def mark_waiting(self, mission_id: UUID | str, reason: str) -> Mission:
        """Ready but blocked on an external condition (market open, internet, …)."""
        return self._transition(mission_id, MISSION_WAITING, "waiting", reason)

    def clear_waiting(self, mission_id: UUID | str, reason: str = "") -> Mission:
        return self._transition(mission_id, MISSION_ACTIVE, "resumed", reason)

    def complete(self, mission_id: UUID | str, reason: str = "") -> Mission:
        return self._transition(mission_id, MISSION_COMPLETED, "completed", reason)

    def archive(self, mission_id: UUID | str, reason: str = "") -> Mission:
        """Non-destructive stop (B5/B9): disable activity, keep everything produced.

        Disables this mission's schedules (A.3) and stops its workers (A.4). Never deletes
        configs, journal, findings, experiences, assets, or checkpoints.
        """
        mission = self._transition(mission_id, MISSION_ARCHIVED, "archived", reason)
        if self._schedule_repo is not None:
            try:
                disabled = self._schedule_repo.disable_for_mission(mission_id)
                if disabled:
                    self._repo.add_journal(
                        mission_id,
                        "schedules_disabled",
                        f"archival disabled {disabled} schedule(s)",
                        {"count": disabled},
                    )
            except Exception:  # noqa: BLE001 - archival must not fail on schedule cleanup
                self._logger.exception("failed to disable schedules for %s", mission_id)
        if self._worker_repo is not None:
            try:
                stopped = self._worker_repo.stop_active_for_mission(mission_id)
                if stopped:
                    self._repo.add_journal(
                        mission_id,
                        "workers_stopped",
                        f"archival stopped {stopped} worker(s)",
                        {"count": stopped},
                    )
            except Exception:  # noqa: BLE001 - archival must not fail on worker cleanup
                self._logger.exception("failed to stop workers for %s", mission_id)
        return mission

    def _transition(
        self,
        mission_id: UUID | str,
        target: str,
        action: str,
        reason: str,
        refs: dict[str, Any] | None = None,
    ) -> Mission:
        mission = self._require(mission_id)
        allowed = MISSION_TRANSITIONS.get(mission.status, frozenset())
        if target not in allowed:
            raise MissionError(
                f"illegal transition {mission.status} → {target}",
                mission_id=str(mission_id),
                current=mission.status,
                target=target,
            )
        self._repo.set_status(mission.id, target)
        self._repo.add_journal(mission.id, action, reason, refs or {})
        updated = self._require(mission.id)
        self._emit(_EVENT_FOR_STATUS.get(target, "MissionUpdated"), updated, reason=reason)
        self._logger.info("mission %s %s (%s→%s)", mission.id, action, mission.status, target)
        return updated

    # --- journal + config + arbitration ---------------------------------

    def journal(
        self,
        mission_id: UUID | str,
        action: str,
        reason: str = "",
        refs: dict[str, Any] | None = None,
    ) -> None:
        """Append an explainability entry (refs/ids only, never copies — A8)."""
        self._require(mission_id)
        self._repo.add_journal(mission_id, action, reason, refs or {})

    def set_active_config(self, mission_id: UUID | str, config_id: str) -> None:
        self._require(mission_id)
        self._repo.set_active_config(mission_id, config_id)
        self._repo.add_journal(
            mission_id, "config_activated", "active config set", {"config_id": config_id}
        )

    def update_arbitration(
        self,
        mission_id: UUID | str,
        *,
        scheduling_policy: str | None = None,
        priority: int | None = None,
        criticality: str | None = None,
        budget: dict[str, Any] | None = None,
    ) -> Mission:
        self._require(mission_id)
        self._validate_enums(scheduling_policy, criticality, priority)
        self._repo.update_arbitration(
            mission_id,
            scheduling_policy=scheduling_policy,
            priority=priority,
            criticality=criticality,
            budget=budget,
        )
        updated = self._require(mission_id)
        self._repo.add_journal(mission_id, "arbitration_updated", "priority/budget changed")
        return updated

    # --- reads ----------------------------------------------------------

    def get_mission(self, mission_id: UUID | str, *, journal_limit: int = 50) -> dict[str, Any]:
        """Aggregated on-demand view (Q2): mission + owned jobs + workers + journal."""
        mission = self._require(mission_id)
        return {
            "mission": mission.to_dict(),
            "effective_priority": mission.effective_priority,
            "job_ids": self._repo.list_job_ids(mission.id),
            "workers": self._mission_workers(mission.id),
            "journal": [e.to_dict() for e in self._repo.list_journal(mission.id, limit=journal_limit)],
        }

    def _mission_workers(self, mission_id: str) -> list[dict[str, Any]]:
        """Owned workers for the aggregated view (A.4); empty if the layer isn't wired."""
        if self._worker_repo is None:
            return []
        try:
            return [w.to_dict() for w in self._worker_repo.list(mission_id=mission_id)]
        except Exception:  # noqa: BLE001 - the view must not fail on the worker layer
            self._logger.exception("failed to list workers for %s", mission_id)
            return []

    def list_missions(
        self,
        *,
        status: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> list[Mission]:
        return self._repo.list(status=status, label=label, limit=limit)

    def journal_entries(self, mission_id: UUID | str, *, limit: int = 100):
        self._require(mission_id)
        return self._repo.list_journal(mission_id, limit=limit)

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            active = len(self._repo.list(status=MISSION_ACTIVE, limit=1000))
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            return HealthStatus.fail(f"mission repo unreachable: {exc}")
        return HealthStatus.ok(f"{active} active mission(s)", active=active)

    # --- helpers --------------------------------------------------------

    def _require(self, mission_id: UUID | str) -> Mission:
        mission = self._repo.get(mission_id)
        if mission is None:
            raise MissionError("mission not found", mission_id=str(mission_id))
        return mission

    @staticmethod
    def _validate_enums(
        scheduling_policy: str | None, criticality: str | None, priority: int | None
    ) -> None:
        if scheduling_policy is not None and scheduling_policy not in SCHEDULING_POLICIES:
            raise MissionError(f"invalid scheduling_policy: {scheduling_policy!r}")
        if criticality is not None and criticality not in CRITICALITIES:
            raise MissionError(f"invalid criticality: {criticality!r}")
        if priority is not None and not (0 <= int(priority) <= 100):
            raise MissionError(f"priority out of range (0–100): {priority}")

    def _emit(self, event_type: str, mission: Mission, **extra: Any) -> None:
        if self._events is None:
            return
        payload = {
            "mission_id": mission.id,
            "title": mission.title,
            "status": mission.status,
            **extra,
        }
        try:
            self._events.emit(event_type, payload, source=self.name)
        except Exception:  # noqa: BLE001 - telemetry must never break a transition
            self._logger.exception("failed to emit %s", event_type)
