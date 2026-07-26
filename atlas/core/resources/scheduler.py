"""Resource Scheduler — Candidate Selector + dispatch façade (IR-RO5).

Internal stages (operator never sees these names):

    Candidate Selector → Reservation Manager (later) → Host Guard → Dispatcher

v1 ships Candidate Selector ranking + REALTIME tick-slot reserve (via MissionArbiter).
Reservations (IR-RO7) and storage pressure (IR-RO6) plug in later.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

from atlas.core.resources.arbiter import (
    ArbitrationVerdict,
    MissionArbiter,
    MissionDemand,
)
from atlas.core.resources.work_profile import (
    SERVICE_REALTIME,
    normalize_service_class,
    service_class_rank,
)


class CandidateSelector:
    """Order READY work: service class → deadline urgency → priority → aging."""

    def __init__(self, arbiter: MissionArbiter) -> None:
        self._arbiter = arbiter

    def rank(
        self, demands: Sequence[MissionDemand], *, now: datetime | None = None
    ) -> list[MissionDemand]:
        now = now or self._arbiter._now()  # noqa: SLF001 — shared clock
        return sorted(demands, key=lambda d: self._sort_key(d, now))

    def _sort_key(self, demand: MissionDemand, now: datetime) -> tuple:
        cls_rank = service_class_rank(getattr(demand, "service_class", None))
        # Lower remaining seconds = more urgent; missing deadline → large number.
        deadline = demand.deadline
        if deadline is None:
            urgency = 10**12
        else:
            urgency = (deadline - now).total_seconds()
        score = self._arbiter.score(demand, now=now)
        # class asc, urgency asc (soonest first), score desc, importance desc, id asc
        return (cls_rank, urgency, -score, -demand.importance_rank(), str(demand.mission_id))

    def pick(
        self, demands: Sequence[MissionDemand], *, now: datetime | None = None
    ) -> MissionDemand | None:
        ranked = self.rank(demands, now=now)
        return ranked[0] if ranked else None


class ResourceScheduler:
    """Façade over Candidate Selector + MissionArbiter (IR-RO5)."""

    name = "resource_scheduler"
    VERSION = "ro5.2"

    def __init__(
        self,
        arbiter: MissionArbiter,
        *,
        reservations: Any | None = None,
        storage_pressure: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._arbiter = arbiter
        self._selector = CandidateSelector(arbiter)
        self._reservations = reservations
        self._storage_pressure = storage_pressure
        self._logger = logger or logging.getLogger("atlas.resources.scheduler")

    @property
    def arbiter(self) -> MissionArbiter:
        return self._arbiter

    @property
    def selector(self) -> CandidateSelector:
        return self._selector

    def attach(
        self,
        *,
        reservations: Any | None = None,
        storage_pressure: Any | None = None,
    ) -> None:
        if reservations is not None:
            self._reservations = reservations
        if storage_pressure is not None:
            self._storage_pressure = storage_pressure

    def rank(self, demands: Sequence[MissionDemand], *, now: datetime | None = None):
        return self._selector.rank(demands, now=now)

    def try_admit(self, demand: MissionDemand, *, now: datetime | None = None) -> ArbitrationVerdict:
        return self._arbiter.try_admit(demand, now=now)

    def release(self, mission_id: str) -> None:
        self._arbiter.release(mission_id)

    def snapshot(self) -> dict[str, Any]:
        snap = self._arbiter.snapshot()
        snap["scheduler_version"] = self.VERSION
        snap["realtime_class"] = SERVICE_REALTIME
        if self._reservations is not None and hasattr(self._reservations, "snapshot"):
            try:
                snap["reservations"] = self._reservations.snapshot()
            except Exception:  # noqa: BLE001
                snap["reservations"] = {}
        if self._storage_pressure is not None and hasattr(self._storage_pressure, "snapshot"):
            try:
                snap["storage_pressure"] = self._storage_pressure.snapshot()
            except Exception:  # noqa: BLE001
                snap["storage_pressure"] = {}
        return snap

    def is_realtime(self, demand: MissionDemand) -> bool:
        return normalize_service_class(getattr(demand, "service_class", None)) in {
            SERVICE_REALTIME,
            "REALTIME_CRITICAL",
            "REALTIME_STANDARD",
        }
