"""Mission Queue — first-class explainable states (IR-RO2).

One logical queue of *accepted* work. Items carry an owner and a wait reason so
operators (and IR-RO5 Candidate Selector) can see *why* something is not running.

Durable hint lives on ``mission.metadata["queue"]``; classification can also derive
state from worker capacity flags when the hint is missing (backward compatible).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# First-class queue states (RESOURCE_OS §7).
QUEUE_READY = "READY"
QUEUE_WAITING_HOST = "WAITING_HOST"
QUEUE_WAITING_NETWORK = "WAITING_NETWORK"
QUEUE_WAITING_GPU = "WAITING_GPU"
QUEUE_WAITING_SCHEDULE = "WAITING_SCHEDULE"
QUEUE_WAITING_OPERATOR = "WAITING_OPERATOR"
QUEUE_WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
QUEUE_BLOCKED = "BLOCKED"
QUEUE_RUNNING = "RUNNING"
QUEUE_CHECKPOINTING = "CHECKPOINTING"
QUEUE_PAUSED = "PAUSED"
QUEUE_COMPLETE = "COMPLETE"
QUEUE_ARCHIVED = "ARCHIVED"

QUEUE_STATES = (
    QUEUE_READY,
    QUEUE_WAITING_HOST,
    QUEUE_WAITING_NETWORK,
    QUEUE_WAITING_GPU,
    QUEUE_WAITING_SCHEDULE,
    QUEUE_WAITING_OPERATOR,
    QUEUE_WAITING_DEPENDENCY,
    QUEUE_BLOCKED,
    QUEUE_RUNNING,
    QUEUE_CHECKPOINTING,
    QUEUE_PAUSED,
    QUEUE_COMPLETE,
    QUEUE_ARCHIVED,
)

WAITING_STATES = frozenset(
    {
        QUEUE_WAITING_HOST,
        QUEUE_WAITING_NETWORK,
        QUEUE_WAITING_GPU,
        QUEUE_WAITING_SCHEDULE,
        QUEUE_WAITING_OPERATOR,
        QUEUE_WAITING_DEPENDENCY,
    }
)


@dataclass(frozen=True)
class QueueOwner:
    program: str | None = None
    mission: str | None = None
    mission_title: str | None = None
    worker: str | None = None
    portfolio: str | None = None
    operator: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueueItem:
    mission_id: str
    state: str
    reason: str = ""
    owner: QueueOwner = field(default_factory=QueueOwner)
    service_class: str | None = None
    worker_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    since: str | None = None
    criticality: str | None = None
    scheduling_policy: str | None = None
    mission_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "state": self.state,
            "reason": self.reason,
            "owner": self.owner.as_dict(),
            "service_class": self.service_class,
            "worker_ids": list(self.worker_ids),
            "depends_on": list(self.depends_on),
            "since": self.since,
            "criticality": self.criticality,
            "scheduling_policy": self.scheduling_policy,
            "mission_status": self.mission_status,
        }


def empty_queue_counts() -> dict[str, int]:
    return {s: 0 for s in QUEUE_STATES}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner_from_mission(
    mission: Any,
    *,
    worker_id: str | None = None,
) -> QueueOwner:
    meta = getattr(mission, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    mid = getattr(mission, "id", None) or meta.get("mission")
    return QueueOwner(
        program=meta.get("program_id") or meta.get("program"),
        mission=str(mid) if mid else None,
        mission_title=getattr(mission, "title", None),
        worker=worker_id,
        portfolio=meta.get("portfolio_key") or meta.get("portfolio_id"),
        operator=meta.get("operator") or meta.get("created_by") or "operator",
    )


def queue_block(
    *,
    state: str,
    reason: str = "",
    depends_on: list[str] | None = None,
    since: str | None = None,
    owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the durable ``metadata.queue`` object."""
    return {
        "state": state,
        "reason": reason or "",
        "depends_on": list(depends_on or []),
        "since": since or _now_iso(),
        "owner": owner or {},
    }


def classify_mission(
    mission: Any,
    workers: list[Any] | None = None,
    *,
    inflight_mission_ids: set[str] | frozenset[str] | None = None,
) -> QueueItem | None:
    """Map a mission (+ optional workers) to a queue item.

    Returns ``None`` for draft missions (not yet accepted into the queue).
    """
    status = getattr(mission, "status", None) or ""
    mid = str(getattr(mission, "id", "") or "")
    meta = getattr(mission, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    q = meta.get("queue") if isinstance(meta.get("queue"), dict) else {}
    workers = workers or []
    worker_ids = [
        str(getattr(w, "id", None) or (w.get("id") if isinstance(w, dict) else "") or "")
        for w in workers
    ]
    worker_ids = [w for w in worker_ids if w]
    primary_worker = worker_ids[0] if worker_ids else None
    owner = owner_from_mission(mission, worker_id=primary_worker)
    # Merge durable owner hints
    if isinstance(q.get("owner"), dict):
        od = q["owner"]
        owner = QueueOwner(
            program=od.get("program") or owner.program,
            mission=od.get("mission") or owner.mission,
            mission_title=od.get("mission_title") or owner.mission_title,
            worker=od.get("worker") or owner.worker,
            portfolio=od.get("portfolio") or owner.portfolio,
            operator=od.get("operator") or owner.operator,
        )

    service_class = meta.get("service_class") or (q.get("service_class"))
    criticality = getattr(mission, "criticality", None)
    policy = getattr(mission, "scheduling_policy", None)

    if status == "draft":
        return None
    if status == "archived":
        return QueueItem(
            mission_id=mid,
            state=QUEUE_ARCHIVED,
            reason="archived",
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            mission_status=status,
            criticality=criticality,
            scheduling_policy=policy,
        )
    if status == "completed":
        return QueueItem(
            mission_id=mid,
            state=QUEUE_COMPLETE,
            reason="completed",
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            mission_status=status,
            criticality=criticality,
            scheduling_policy=policy,
        )

    # Explicit durable queue hint wins when present.
    explicit = q.get("state")
    if explicit in QUEUE_STATES:
        return QueueItem(
            mission_id=mid,
            state=str(explicit),
            reason=str(q.get("reason") or ""),
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            depends_on=list(q.get("depends_on") or []),
            since=q.get("since"),
            criticality=criticality,
            scheduling_policy=policy,
            mission_status=status,
        )

    # Derive from mission lifecycle + workers.
    if status == "paused":
        return QueueItem(
            mission_id=mid,
            state=QUEUE_PAUSED,
            reason="mission_paused",
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            mission_status=status,
            criticality=criticality,
            scheduling_policy=policy,
        )

    if status == "waiting":
        # Lifecycle waiting without finer hint → dependency by default (explainable).
        return QueueItem(
            mission_id=mid,
            state=QUEUE_WAITING_DEPENDENCY,
            reason="mission_waiting",
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            mission_status=status,
            criticality=criticality,
            scheduling_policy=policy,
        )

    # Capacity-queued workers (archive / host deferral).
    for w in workers:
        wmeta = getattr(w, "metadata", None)
        if wmeta is None and isinstance(w, dict):
            wmeta = w.get("metadata")
        if isinstance(wmeta, dict) and wmeta.get("queued_for_capacity"):
            return QueueItem(
                mission_id=mid,
                state=QUEUE_WAITING_HOST,
                reason=str(wmeta.get("queue_reason") or meta.get("queue_reason") or "queued_for_capacity"),
                owner=owner,
                service_class=service_class,
                worker_ids=worker_ids,
                since=None,
                criticality=criticality,
                scheduling_policy=policy,
                mission_status=status,
            )
        if isinstance(wmeta, dict) and (wmeta.get("ops") or {}).get("wait_reason") in (
            "host_pressure",
            "budget",
        ):
            return QueueItem(
                mission_id=mid,
                state=QUEUE_WAITING_HOST,
                reason=str((wmeta.get("ops") or {}).get("wait_reason")),
                owner=owner,
                service_class=service_class,
                worker_ids=worker_ids,
                criticality=criticality,
                scheduling_policy=policy,
                mission_status=status,
            )

    inflight = inflight_mission_ids or frozenset()
    if mid and mid in inflight:
        return QueueItem(
            mission_id=mid,
            state=QUEUE_RUNNING,
            reason="tick_inflight",
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            criticality=criticality,
            scheduling_policy=policy,
            mission_status=status,
        )

    # Active mission with recovering workers → schedule wait.
    for w in workers:
        wstatus = getattr(w, "status", None) or (w.get("status") if isinstance(w, dict) else None)
        if wstatus == "recovering":
            return QueueItem(
                mission_id=mid,
                state=QUEUE_WAITING_SCHEDULE,
                reason="crash_backoff",
                owner=owner,
                service_class=service_class,
                worker_ids=worker_ids,
                criticality=criticality,
                scheduling_policy=policy,
                mission_status=status,
            )

    if meta.get("queued_for_capacity"):
        return QueueItem(
            mission_id=mid,
            state=QUEUE_WAITING_HOST,
            reason=str(meta.get("queue_reason") or "queued_for_capacity"),
            owner=owner,
            service_class=service_class,
            worker_ids=worker_ids,
            criticality=criticality,
            scheduling_policy=policy,
            mission_status=status,
        )

    # Default for active accepted work.
    return QueueItem(
        mission_id=mid,
        state=QUEUE_READY,
        reason="eligible",
        owner=owner,
        service_class=service_class,
        worker_ids=worker_ids,
        criticality=criticality,
        scheduling_policy=policy,
        mission_status=status,
    )


def summarize_queue(items: list[QueueItem]) -> dict[str, Any]:
    counts = empty_queue_counts()
    for item in items:
        counts[item.state] = counts.get(item.state, 0) + 1
    waiting = sum(counts[s] for s in WAITING_STATES)
    notable = [
        i.as_dict()
        for i in items
        if i.state
        in (
            QUEUE_WAITING_HOST,
            QUEUE_WAITING_DEPENDENCY,
            QUEUE_WAITING_OPERATOR,
            QUEUE_BLOCKED,
            QUEUE_RUNNING,
        )
    ]
    return {
        "counts": counts,
        "waiting": waiting,
        "active": sum(
            counts[s]
            for s in QUEUE_STATES
            if s not in (QUEUE_COMPLETE, QUEUE_ARCHIVED)
        ),
        "items": [i.as_dict() for i in items],
        "notable": notable[:20],
        "version": "ro2.1",
    }


class MissionQueueService:
    """Build the operator-facing Mission Queue snapshot (IR-RO2)."""

    name = "mission_queue"
    VERSION = "ro2.1"

    def __init__(
        self,
        *,
        missions: Any | None = None,
        workers: Any | None = None,
        arbiter: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._missions = missions
        self._workers = workers
        self._arbiter = arbiter
        self._logger = logger or logging.getLogger("atlas.resources.mission_queue")

    def snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        if self._missions is None:
            return {"counts": empty_queue_counts(), "items": [], "note": "missions unavailable"}
        try:
            rows = self._missions.list_missions(limit=max(1, limit))
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("mission list failed: %s", exc)
            return {"counts": empty_queue_counts(), "items": [], "note": str(exc)}

        inflight: set[str] = set()
        if self._arbiter is not None and hasattr(self._arbiter, "snapshot"):
            try:
                snap = self._arbiter.snapshot()
                for mid, n in (snap.get("inflight") or {}).items():
                    if int(n or 0) > 0:
                        inflight.add(str(mid))
            except Exception:  # noqa: BLE001
                pass

        items: list[QueueItem] = []
        for mission in rows:
            workers: list[Any] = []
            if self._workers is not None:
                try:
                    workers = self._workers.list_workers(mission_id=str(mission.id), limit=50)
                except Exception:  # noqa: BLE001
                    workers = []
            item = classify_mission(mission, workers, inflight_mission_ids=inflight)
            if item is not None:
                items.append(item)
        out = summarize_queue(items)
        out["note"] = (
            "Mission Queue (IR-RO2): READY / WAITING_* / RUNNING — why work is or isn't progressing."
        )
        return out

