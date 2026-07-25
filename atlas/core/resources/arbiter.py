"""Cross-mission arbiter (Phase D · §D.4, roadmap A7 / OI-A3 / OI-D2).

The Resource Manager (``manager.py``) answers *machine* questions — CPU/RAM/thermal/LLM caps for one
task. The **arbiter** answers the orthogonal *cross-mission* question: when several missions compete for
the same worker slots, **who goes first, and who waits?** It weighs each mission's

* ``effective_priority`` — policy band + priority + criticality (the primary signal),
* **deadline urgency** — a bounded boost that grows as a deadline nears (or is overdue),
* **importance** — an advisory tiebreak, then ``mission_id`` for full determinism,
* **fair-share soft penalty** (OI-D2) — recent admits in a sliding window gently lower score so a
  hogging mission yields under contention (not preemption — running ticks are never interrupted),
  and enforces
* **hard per-mission budget caps** (``max_concurrent_tasks``, ``llm_units_per_window``, optional
  ``ram_mb``) and an optional **global** concurrency cap.

Fairness (A7 — "deferred, not starved indefinitely"): every deferral ages a mission's score upward by a
bounded amount, so a repeatedly-passed-over mission eventually wins a slot. Admission resets its aging.
The arbiter is deterministic and in-memory (single-process, like the Phase-A worker gate); multi-process
arbitration is tracked debt.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

# importance is a free-text advisory field; these are the values we rank, unknown → neutral.
_IMPORTANCE_RANK: dict[str, int] = {"critical": 3, "high": 2, "normal": 1, "low": 0}

DEFAULT_LLM_WINDOW_SECONDS = 300


@dataclass(frozen=True, slots=True)
class MissionDemand:
    """One mission asking for a slot, projected from its ``mission.missions`` row."""

    mission_id: str
    effective_priority: int = 0
    deadline: datetime | None = None
    importance: str | None = None
    max_concurrent_tasks: int | None = None  # hard per-mission cap; None = unlimited
    inflight: int = 0  # this mission's current in-flight count (for the pure `select`)
    # OI-A3 resource caps (None = unlimited / not checked)
    llm_units_per_window: int | None = None
    llm_window_seconds: int = DEFAULT_LLM_WINDOW_SECONDS
    estimated_llm_units: int = 1  # coarse: one worker tick ≈ 1 unit
    ram_mb: int | None = None
    host_available_ram_mb: int | None = None  # filled by WorkerManager from machine RM

    def importance_rank(self) -> int:
        return _IMPORTANCE_RANK.get((self.importance or "").strip().lower(), 0)


@dataclass(frozen=True, slots=True)
class ArbitrationVerdict:
    mission_id: str
    admitted: bool
    reason: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "admitted": self.admitted,
            "reason": self.reason,
            "score": round(self.score, 4),
        }


class MissionArbiter:
    name = "mission_arbiter"
    VERSION = "1.2.0"

    def __init__(
        self,
        *,
        global_max_concurrent: int | None = None,
        deadline_horizon_seconds: float = 3600.0,
        deadline_boost_max: float = 15.0,
        starvation_boost_per_defer: float = 2.0,
        starvation_boost_max: float = 40.0,
        fair_share_window_seconds: float = 300.0,
        fair_share_penalty_per_admit: float = 1.0,
        fair_share_penalty_max: float = 20.0,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._global_max = global_max_concurrent if global_max_concurrent and global_max_concurrent > 0 else None
        self._horizon = max(1.0, float(deadline_horizon_seconds))
        self._deadline_boost_max = max(0.0, float(deadline_boost_max))
        self._starve_per = max(0.0, float(starvation_boost_per_defer))
        self._starve_max = max(0.0, float(starvation_boost_max))
        self._fair_window = max(1.0, float(fair_share_window_seconds))
        self._fair_per = max(0.0, float(fair_share_penalty_per_admit))
        self._fair_max = max(0.0, float(fair_share_penalty_max))
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.arbiter")
        self._lock = threading.RLock()
        self._inflight: dict[str, int] = {}
        self._total = 0
        self._deferrals: dict[str, int] = {}  # mission → consecutive deferrals (anti-starvation aging)
        # OI-A3: per-mission sliding window of (unix_ts, units) admissions.
        self._llm_ledger: dict[str, deque[tuple[float, int]]] = {}
        # OI-D2: per-mission sliding window of admit timestamps (fair-share usage).
        self._admit_ledger: dict[str, deque[float]] = {}

    # --- scoring (deterministic) ----------------------------------------
    def score(self, demand: MissionDemand, *, now: datetime | None = None, deferrals: int | None = None) -> float:
        """priority + deadline urgency + starvation aging − fair-share usage penalty."""
        now = now or self._now()
        defers = self._deferrals.get(demand.mission_id, 0) if deferrals is None else deferrals
        aging = min(self._starve_max, defers * self._starve_per)
        return (
            float(demand.effective_priority)
            + self._deadline_boost(demand.deadline, now)
            + aging
            - self._fair_share_penalty(demand.mission_id, now)
        )

    def _fair_share_penalty(self, mission_id: str, now: datetime) -> float:
        """Bounded soft penalty for recent admits (OI-D2). Zero when fair-share is disabled."""
        if self._fair_per <= 0 or self._fair_max <= 0:
            return 0.0
        with self._lock:
            admits = self._admits_in_window_locked(mission_id, now)
        return min(self._fair_max, admits * self._fair_per)

    def _deadline_boost(self, deadline: datetime | None, now: datetime | None) -> float:
        if deadline is None:
            return 0.0
        now = now or self._now()
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            return self._deadline_boost_max  # overdue → full urgency
        if remaining >= self._horizon:
            return 0.0  # beyond the horizon → not yet urgent
        return self._deadline_boost_max * (1.0 - remaining / self._horizon)

    def _sort_key(self, demand: MissionDemand, now: datetime | None) -> tuple:
        # score desc, importance desc, then mission_id asc → total, stable, deterministic order.
        return (-self.score(demand, now=now), -demand.importance_rank(), str(demand.mission_id))

    # --- pure batch arbitration (no state) ------------------------------
    def rank(self, demands: Sequence[MissionDemand], *, now: datetime | None = None) -> list[MissionDemand]:
        """Contention order: who *should* run first, ignoring current occupancy."""
        now = now or self._now()
        return sorted(demands, key=lambda d: self._sort_key(d, now))

    def select(
        self, demands: Sequence[MissionDemand], slots: int, *, now: datetime | None = None
    ) -> list[ArbitrationVerdict]:
        """Fill ``slots`` from the ranked demands, honouring hard per-mission caps.

        Returns a verdict per demand in ranked order: the top admissible get in; those over their own
        hard cap are deferred (a freed slot goes to the next mission, not wasted); the remainder are
        deferred for lack of slots.
        """
        now = now or self._now()
        free = max(0, int(slots))
        out: list[ArbitrationVerdict] = []
        for d in self.rank(demands, now=now):
            s = self.score(d, now=now)
            cap = d.max_concurrent_tasks
            if cap is not None and cap > 0 and d.inflight >= cap:
                out.append(ArbitrationVerdict(d.mission_id, False, f"mission budget cap {d.inflight}/{cap}", s))
            elif free > 0:
                free -= 1
                out.append(ArbitrationVerdict(d.mission_id, True, "admitted", s))
            else:
                out.append(ArbitrationVerdict(d.mission_id, False, "no free slots (global capacity)", s))
        return out

    # --- stateful admission gate ----------------------------------------
    def try_admit(self, demand: MissionDemand, *, now: datetime | None = None) -> ArbitrationVerdict:
        """Reserve a slot for one mission, or defer it. Never raises."""
        now = now or self._now()
        with self._lock:
            current = self._inflight.get(demand.mission_id, 0)
            cap = demand.max_concurrent_tasks
            score = self.score(demand, now=now)
            if cap is not None and cap > 0 and current >= cap:
                self._defer_locked(demand.mission_id)
                return ArbitrationVerdict(demand.mission_id, False, f"mission budget cap {current}/{cap}", score)
            if self._global_max is not None and self._total >= self._global_max:
                self._defer_locked(demand.mission_id)
                return ArbitrationVerdict(
                    demand.mission_id, False, f"global capacity {self._total}/{self._global_max}", score
                )
            # OI-A3 — host RAM reserve (soft): deny when machine available < mission reserve.
            ram_need = demand.ram_mb
            host_ram = demand.host_available_ram_mb
            if ram_need is not None and ram_need > 0 and host_ram is not None and host_ram < ram_need:
                self._defer_locked(demand.mission_id)
                return ArbitrationVerdict(
                    demand.mission_id,
                    False,
                    f"mission ram_mb {host_ram}/{ram_need}",
                    score,
                )
            # OI-A3 — LLM units sliding window.
            llm_cap = demand.llm_units_per_window
            units = max(0, int(demand.estimated_llm_units or 0))
            if llm_cap is not None and llm_cap > 0 and units > 0:
                window = max(1, int(demand.llm_window_seconds or DEFAULT_LLM_WINDOW_SECONDS))
                used = self._llm_used_locked(demand.mission_id, now=now, window_seconds=window)
                if used + units > llm_cap:
                    self._defer_locked(demand.mission_id)
                    return ArbitrationVerdict(
                        demand.mission_id,
                        False,
                        f"mission llm_units_per_window {used}/{llm_cap}",
                        score,
                    )
                self._llm_record_locked(demand.mission_id, now=now, units=units, window_seconds=window)
            self._inflight[demand.mission_id] = current + 1
            self._total += 1
            self._deferrals.pop(demand.mission_id, None)  # admitted → reset aging (fairness)
            self._record_admit_locked(demand.mission_id, now)  # OI-D2 fair-share usage
            return ArbitrationVerdict(demand.mission_id, True, "admitted", score)

    def release(self, mission_id: str) -> None:
        with self._lock:
            current = self._inflight.get(mission_id, 0)
            if current <= 1:
                self._inflight.pop(mission_id, None)
            else:
                self._inflight[mission_id] = current - 1
            self._total = max(0, self._total - 1)

    def _defer_locked(self, mission_id: str) -> None:
        self._deferrals[mission_id] = self._deferrals.get(mission_id, 0) + 1

    def _llm_used_locked(self, mission_id: str, *, now: datetime, window_seconds: int) -> int:
        ledger = self._llm_ledger.get(mission_id)
        if not ledger:
            return 0
        cutoff = now.timestamp() - window_seconds
        while ledger and ledger[0][0] < cutoff:
            ledger.popleft()
        if not ledger:
            self._llm_ledger.pop(mission_id, None)
            return 0
        return sum(u for _, u in ledger)

    def _llm_record_locked(
        self, mission_id: str, *, now: datetime, units: int, window_seconds: int
    ) -> None:
        ledger = self._llm_ledger.setdefault(mission_id, deque())
        ledger.append((now.timestamp(), units))
        # Opportunistic prune so the deque cannot grow without bound.
        self._llm_used_locked(mission_id, now=now, window_seconds=window_seconds)

    def _admits_in_window_locked(self, mission_id: str, now: datetime) -> int:
        ledger = self._admit_ledger.get(mission_id)
        if not ledger:
            return 0
        cutoff = now.timestamp() - self._fair_window
        while ledger and ledger[0] < cutoff:
            ledger.popleft()
        if not ledger:
            self._admit_ledger.pop(mission_id, None)
            return 0
        return len(ledger)

    def _record_admit_locked(self, mission_id: str, now: datetime) -> None:
        if self._fair_per <= 0 or self._fair_max <= 0:
            return
        ledger = self._admit_ledger.setdefault(mission_id, deque())
        ledger.append(now.timestamp())
        self._admits_in_window_locked(mission_id, now)

    # --- introspection --------------------------------------------------
    def inflight_for(self, mission_id: str) -> int:
        with self._lock:
            return self._inflight.get(mission_id, 0)

    def deferrals_for(self, mission_id: str) -> int:
        with self._lock:
            return self._deferrals.get(mission_id, 0)

    def recent_admits(self, mission_id: str) -> int:
        with self._lock:
            return self._admits_in_window_locked(mission_id, self._now())

    def llm_units_used(self, mission_id: str, *, window_seconds: int = DEFAULT_LLM_WINDOW_SECONDS) -> int:
        with self._lock:
            return self._llm_used_locked(
                mission_id, now=self._now(), window_seconds=max(1, int(window_seconds))
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            llm_used = {
                mid: self._llm_used_locked(mid, now=now, window_seconds=DEFAULT_LLM_WINDOW_SECONDS)
                for mid in self._llm_ledger
            }
            admits = {
                mid: self._admits_in_window_locked(mid, now) for mid in self._admit_ledger
            }
            return {
                "total_inflight": self._total,
                "global_max": self._global_max,
                "inflight": dict(self._inflight),
                "deferrals": dict(self._deferrals),
                "llm_units_in_window": llm_used,
                "admits_in_fair_share_window": admits,
                "fair_share_window_seconds": self._fair_window,
            }

    def _now(self) -> datetime:
        if self._clock is not None:
            try:
                return self._clock.now()
            except Exception:  # noqa: BLE001 - fall back to wall clock
                pass
        return datetime.now(timezone.utc)


def demand_from_mission(
    mission: Any,
    *,
    host_available_ram_mb: int | None = None,
    estimated_llm_units: int = 1,
) -> MissionDemand:
    """Project a ``Mission`` (or any object exposing the arbitration fields) into a MissionDemand."""
    return MissionDemand(
        mission_id=str(getattr(mission, "id", "")),
        effective_priority=int(getattr(mission, "effective_priority", 0) or 0),
        deadline=getattr(mission, "deadline", None),
        importance=getattr(mission, "importance", None),
        max_concurrent_tasks=getattr(mission, "max_concurrent_tasks", None),
        llm_units_per_window=getattr(mission, "llm_units_per_window", None),
        llm_window_seconds=int(
            getattr(mission, "llm_window_seconds", DEFAULT_LLM_WINDOW_SECONDS) or DEFAULT_LLM_WINDOW_SECONDS
        ),
        estimated_llm_units=max(0, int(estimated_llm_units)),
        ram_mb=getattr(mission, "ram_mb", None),
        host_available_ram_mb=host_available_ram_mb,
    )
