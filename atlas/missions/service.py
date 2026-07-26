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
        mission = self._transition(mission_id, MISSION_COMPLETED, "completed", reason)
        self._resolve_parent_waits(mission.id)
        return mission

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
        self._resolve_parent_waits(mission.id)
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

    def update_metadata(self, mission_id: UUID | str, metadata: dict[str, Any]) -> Mission:
        """Replace mission metadata (IR-RO2 queue hints, admission, …)."""
        mission = self._require(mission_id)
        self._repo.update_metadata(mission.id, metadata or {})
        return self._require(mission_id)

    def set_queue_state(
        self,
        mission_id: UUID | str,
        state: str,
        *,
        reason: str = "",
        depends_on: list[str] | None = None,
        journal: bool = True,
    ) -> Mission:
        """Persist ``metadata.queue`` (IR-RO2). Optionally move lifecycle to waiting."""
        from atlas.core.resources.mission_queue import (
            QUEUE_STATES,
            QUEUE_WAITING_DEPENDENCY,
            owner_from_mission,
            queue_block,
        )

        if state not in QUEUE_STATES:
            raise MissionError(f"invalid queue state: {state!r}")
        mission = self._require(mission_id)
        meta = dict(mission.metadata or {})
        meta["queue"] = queue_block(
            state=state,
            reason=reason,
            depends_on=depends_on,
            owner=owner_from_mission(mission).as_dict(),
        )
        self._repo.update_metadata(mission.id, meta)
        if state == QUEUE_WAITING_DEPENDENCY and mission.status == MISSION_ACTIVE:
            try:
                self.mark_waiting(mission.id, reason or "waiting_dependency")
            except MissionError:
                pass
        elif state == "READY" and mission.status == MISSION_WAITING:
            try:
                self.clear_waiting(mission.id, reason or "queue_ready")
            except MissionError:
                pass
        if journal:
            self._repo.add_journal(
                mission.id,
                "queue_state",
                reason or state,
                refs={"state": state, "depends_on": list(depends_on or [])},
            )
        return self._require(mission_id)

    def set_waiting_dependency(
        self,
        mission_id: UUID | str,
        depends_on: list[str] | str,
        *,
        reason: str = "waiting_dependency",
    ) -> Mission:
        """Mark mission WAITING_DEPENDENCY on another mission/artifact id(s)."""
        from atlas.core.resources.mission_queue import QUEUE_WAITING_DEPENDENCY

        deps = depends_on if isinstance(depends_on, list) else [depends_on]
        return self.set_queue_state(
            mission_id,
            QUEUE_WAITING_DEPENDENCY,
            reason=reason,
            depends_on=[str(d) for d in deps if d],
        )

    def clear_queue_wait(self, mission_id: UUID | str, *, reason: str = "cleared") -> Mission:
        """Set queue state back to READY (e.g. after Host Guard resume)."""
        from atlas.core.resources.mission_queue import QUEUE_READY

        return self.set_queue_state(mission_id, QUEUE_READY, reason=reason)

    # --- Mission DAG (IR-M1) --------------------------------------------

    def spawn_child(
        self,
        parent_id: UUID | str,
        title: str,
        objective: str = "",
        *,
        role: str = "child",
        wait_on_child: bool = True,
        activate: bool = True,
        metadata: dict[str, Any] | None = None,
        **create_kwargs: Any,
    ) -> Mission:
        """Create a child mission linked under ``parent`` (IR-M1).

        When ``wait_on_child`` is True, the parent is marked WAITING_DEPENDENCY on the child.
        """
        from atlas.core.resources.mission_dag import dag_block, read_dag

        parent = self._require(parent_id)
        meta = dict(metadata or {})
        meta["dag"] = dag_block(parent_id=str(parent.id), role=role)
        child = self.create_mission(
            title,
            objective or f"{role} for {parent.title}",
            metadata=meta,
            **create_kwargs,
        )
        # Link on parent
        pmeta = dict(parent.metadata or {})
        pdag = read_dag(pmeta)
        children = list(pdag.get("children") or [])
        if str(child.id) not in children:
            children.append(str(child.id))
        pmeta["dag"] = dag_block(
            parent_id=pdag.get("parent_id"),
            role=pdag.get("role") or "parent",
            children=children,
            pipeline=pdag.get("pipeline") or [],
        )
        self._repo.update_metadata(parent.id, pmeta)
        self._repo.add_journal(
            parent.id,
            "child_spawned",
            f"spawned {role} child",
            refs={"child_id": str(child.id), "role": role},
        )
        if wait_on_child:
            parent = self._require(parent.id)
            q = (parent.metadata or {}).get("queue") if isinstance(parent.metadata, dict) else {}
            existing = []
            if isinstance(q, dict):
                existing = [str(d) for d in (q.get("depends_on") or []) if d]
            deps = list(dict.fromkeys([*existing, *children]))
            self.set_waiting_dependency(
                parent.id,
                deps,
                reason=f"waiting_on_child:{role}",
            )
        if activate:
            try:
                if child.status == MISSION_DRAFT:
                    self.activate(child.id, reason=f"dag child {role}")
            except MissionError:
                pass
        return self._require(child.id)

    def get_dag(self, mission_id: UUID | str) -> dict[str, Any]:
        """Snapshot of mission DAG node + loaded children (IR-M1)."""
        from atlas.core.resources.mission_dag import dag_snapshot, read_dag

        mission = self._require(mission_id)
        dag = read_dag(mission.metadata if isinstance(mission.metadata, dict) else {})
        children = []
        for cid in dag.get("children") or []:
            try:
                children.append(self._require(cid))
            except MissionError:
                continue
        return dag_snapshot(mission, children=children)

    def set_research_confidence(
        self,
        mission_id: UUID | str,
        *,
        confidence_score: float | None = None,
        confidence: str | None = None,
        source: str = "research",
    ) -> Mission:
        """Persist research confidence on mission metadata (IR-M3 scheduler signal)."""
        mission = self._require(mission_id)
        meta = dict(mission.metadata or {})
        score = None
        if confidence_score is not None:
            try:
                score = max(0.0, min(1.0, float(confidence_score)))
            except (TypeError, ValueError):
                score = None
        from atlas.core.resources.mission_dag import utc_now_iso

        meta["research"] = {
            "confidence_score": score,
            "confidence": confidence,
            "source": source,
            "updated_at": utc_now_iso(),
        }
        self._repo.update_metadata(mission.id, meta)
        self._repo.add_journal(
            mission.id,
            "research_confidence",
            confidence or (f"score={score}" if score is not None else "updated"),
            refs={"confidence_score": score, "confidence": confidence, "source": source},
        )
        return self._require(mission.id)

    def _resolve_parent_waits(self, child_id: UUID | str) -> None:
        """When a child completes/archives, unblock parents whose depends_on are all terminal."""
        from atlas.core.resources.mission_dag import all_deps_terminal, read_dag
        from atlas.core.resources.mission_queue import QUEUE_WAITING_DEPENDENCY

        child = self._require(child_id)
        parent_id = None
        meta = child.metadata if isinstance(child.metadata, dict) else {}
        parent_id = read_dag(meta).get("parent_id")
        candidates: list[Mission] = []
        if parent_id:
            try:
                candidates.append(self._require(parent_id))
            except MissionError:
                pass
        # Also scan recent missions that list this child in depends_on (small N).
        try:
            for m in self.list_missions(limit=200):
                q = (m.metadata or {}).get("queue") if isinstance(m.metadata, dict) else {}
                if not isinstance(q, dict):
                    continue
                if q.get("state") != QUEUE_WAITING_DEPENDENCY:
                    continue
                deps = [str(d) for d in (q.get("depends_on") or []) if d]
                if str(child.id) in deps:
                    if all(str(c.id) != str(m.id) for c in candidates):
                        candidates.append(m)
        except Exception:  # noqa: BLE001
            self._logger.debug("parent wait scan failed", exc_info=True)

        if not candidates:
            return
        # Build status map for deps.
        status_by_id: dict[str, str] = {str(child.id): child.status}
        for parent in candidates:
            q = (parent.metadata or {}).get("queue") if isinstance(parent.metadata, dict) else {}
            deps = [str(d) for d in ((q or {}).get("depends_on") or []) if d] if isinstance(q, dict) else []
            for dep in deps:
                if dep not in status_by_id:
                    try:
                        status_by_id[dep] = self._require(dep).status
                    except MissionError:
                        status_by_id[dep] = ""
            if all_deps_terminal(deps, status_by_id):
                try:
                    self.clear_queue_wait(parent.id, reason=f"deps_complete:{child.id}")
                except Exception:  # noqa: BLE001
                    self._logger.debug("clear_queue_wait failed for %s", parent.id, exc_info=True)

    # --- reads ----------------------------------------------------------

    def get_mission(self, mission_id: UUID | str, *, journal_limit: int = 50) -> dict[str, Any]:
        """Aggregated on-demand view (Q2): mission + owned jobs + workers + journal."""
        mission = self._require(mission_id)
        workers = self._mission_workers(mission.id)
        from atlas.core.resources.mission_queue import classify_mission

        queue_item = classify_mission(mission, workers)
        return {
            "mission": mission.to_dict(),
            "effective_priority": mission.effective_priority,
            "job_ids": self._repo.list_job_ids(mission.id),
            "workers": workers,
            "queue": queue_item.as_dict() if queue_item else None,
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
