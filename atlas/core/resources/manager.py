"""Kernel Resource Manager (Stage 3.2c) — caps, profiles, detect→slow.

Central question: given machine state + operator caps, how many workers should
research use *right now*? Never fails a job for capacity; never pretends thermal/
power are protected when sensors are missing.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator
from typing import Any

from atlas.core.resources.monitor import SystemSnapshot, read_snapshot
from atlas.core.resources.profiles import ResourceProfile, get_profile
from atlas.services.base import HealthStatus


@dataclass
class PoolRecommendation:
    download_workers: int
    reader_workers: int
    ocr_workers: int
    extract_workers: int
    global_max: int
    profile: str
    throttled: bool = False
    throttle_reason: str = ""
    protection: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def acquire_workers(self) -> int:
        """Combined acquire (download+read) pool size used by the Librarian."""
        return max(1, min(self.download_workers, self.reader_workers, self.global_max))

    def as_dict(self) -> dict[str, Any]:
        return {
            "download_workers": self.download_workers,
            "reader_workers": self.reader_workers,
            "ocr_workers": self.ocr_workers,
            "extract_workers": self.extract_workers,
            "acquire_workers": self.acquire_workers,
            "global_max": self.global_max,
            "profile": self.profile,
            "throttled": self.throttled,
            "throttle_reason": self.throttle_reason,
            "protection": dict(self.protection),
            "snapshot": dict(self.snapshot),
        }


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Projected resource decision for one task."""

    allowed: bool
    reason: str
    cost_units: int
    expected_ram_mb: int
    llm_slots: int
    budget_units: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "cost_units": self.cost_units,
            "expected_ram_mb": self.expected_ram_mb,
            "llm_slots": self.llm_slots,
            "budget_units": self.budget_units,
        }


class ResourceManager:
    """Observe → evaluate → allocate under hard operator caps."""

    name = "resources"

    # Soft pressure thresholds (Stage 3.2c — tunable later in Stage 4).
    LOAD_PRESSURE_HIGH = 0.90
    RAM_USED_HIGH = 0.88
    THERMAL_C_HIGH = 85.0
    THERMAL_C_RESUME = 75.0

    def __init__(
        self,
        *,
        profile: str = "balanced",
        max_worker_threads: int = 4,
        max_download_workers: int = 4,
        max_reader_workers: int = 4,
        max_ocr_workers: int = 2,
        max_extract_workers: int = 2,
        llm_max_concurrency: int = 1,
        cost_budgets: dict[str, int] | None = None,
        llm_cost_units: dict[str, int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._default_profile = (profile or "balanced").strip().lower()
        self._max_worker_threads = max(1, int(max_worker_threads or 1))
        self._max_download = max(1, int(max_download_workers or 1))
        self._max_reader = max(1, int(max_reader_workers or 1))
        self._max_ocr = max(1, int(max_ocr_workers or 1))
        self._max_extract = max(1, int(max_extract_workers or 1))
        self._llm_max = max(1, int(llm_max_concurrency or 1))
        self._cost_budgets = {
            "conservative": 12,
            "balanced": 20,
            "maximum": 32,
            "overnight": 32,
            **{str(k): max(1, int(v)) for k, v in (cost_budgets or {}).items()},
        }
        self._llm_cost_units = {
            "default": 15,
            **{
                str(kind): max(1, int(units))
                for kind, units in (llm_cost_units or {}).items()
            },
        }
        self._logger = logger or logging.getLogger("atlas.resources")
        self._lock = threading.Lock()
        self._leases: dict[str, int] = {}  # token → workers held
        self._cost_in_use = 0
        self._llm_in_use = 0
        self._llm_lane = threading.BoundedSemaphore(self._llm_max)
        self._thermal_hold = False

    def posture(self, *, profile: str | None = None) -> dict[str, Any]:
        """Honest protection summary for UI / activity (A32.17)."""
        snap = read_snapshot(self._logger)
        prof = get_profile(profile or self._default_profile)
        return {
            "profile": prof.name,
            "caps_enforced": True,
            "max_worker_threads": self._max_worker_threads,
            "thermal_monitored": snap.thermal_monitored,
            "power_monitored": snap.power_monitored,
            "cpu_ram_monitored": snap.load_pressure is not None or snap.ram_used_fraction is not None,
            "notes": list(snap.notes),
            "snapshot": snap.as_dict(),
            "message": self._posture_message(snap),
        }

    def recommend_pool_sizes(
        self,
        *,
        profile: str | None = None,
        llm_max_concurrency: int | None = None,
        download_work: int | None = None,
        reader_work: int | None = None,
        ocr_work: int | None = None,
        extract_work: int | None = None,
    ) -> PoolRecommendation:
        """Return effective pool sizes for the current machine + profile."""
        prof = get_profile(profile or self._default_profile)
        snap = read_snapshot(self._logger)
        throttled, reason = self._pressure(snap, prof)

        bonus = 0 if throttled else max(0, int(prof.worker_bonus))
        # Preferred sizes start from config caps, then profile may add within global max.
        global_max = self._max_worker_threads
        download = min(self._max_download + bonus, global_max)
        reader = min(self._max_reader + bonus, global_max)
        ocr = min(self._max_ocr, global_max)
        llm_cap = max(1, int(llm_max_concurrency or self._llm_max))
        extract = min(self._max_extract, global_max, llm_cap)

        if throttled:
            # Slow down to protect the system — never zero (job must continue).
            download = 1
            reader = 1
            ocr = 1
            extract = 1

        # Adaptive pools (D32.12): never start more workers than actual work.
        download = self._clamp_to_work(download, download_work)
        reader = self._clamp_to_work(reader, reader_work)
        ocr = self._clamp_to_work(ocr, ocr_work)
        extract = self._clamp_to_work(extract, extract_work)

        return PoolRecommendation(
            download_workers=max(1, download),
            reader_workers=max(1, reader),
            ocr_workers=max(1, ocr),
            extract_workers=max(1, extract),
            global_max=global_max,
            profile=prof.name,
            throttled=throttled,
            throttle_reason=reason,
            protection={
                "caps_enforced": True,
                "thermal_monitored": snap.thermal_monitored,
                "power_monitored": snap.power_monitored,
                "message": self._posture_message(snap),
            },
            snapshot=snap.as_dict(),
        )

    def request(
        self,
        *,
        workers: int = 1,
        kind: str = "generic",
        profile: str | None = None,
    ) -> tuple[str, int]:
        """Lease up to ``workers`` slots. Returns (token, granted). Never raises."""
        rec = self.recommend_pool_sizes(profile=profile)
        want = max(1, int(workers or 1))
        with self._lock:
            in_use = sum(self._leases.values())
            free = max(0, rec.global_max - in_use)
            granted = min(want, free, rec.acquire_workers if kind == "acquire" else want)
            if granted <= 0:
                # No free slots — grant 1 anyway so work queues/slows, never fails.
                granted = 1
            token = f"{kind}-{len(self._leases) + 1}-{threading.get_ident()}"
            self._leases[token] = granted
            return token, granted

    def release(self, token: str) -> None:
        with self._lock:
            self._leases.pop(token, None)

    def can_admit(
        self,
        *,
        cost_units: int,
        expected_ram_mb: int = 0,
        llm_slots: int = 0,
        profile: str | None = None,
    ) -> AdmissionDecision:
        """Decide from projected cost/RAM/LLM usage before task launch."""
        prof = get_profile(profile or self._default_profile)
        budget = self._cost_budgets.get(prof.name, self._cost_budgets["balanced"])
        cost = max(0, int(cost_units))
        ram_mb = max(0, int(expected_ram_mb))
        slots = max(0, int(llm_slots))
        snap = read_snapshot(self._logger)
        reasons: list[str] = []
        with self._lock:
            if self._cost_in_use + cost > budget:
                reasons.append(
                    f"cost budget {self._cost_in_use + cost}>{budget}"
                )
            if slots and self._llm_in_use + slots > self._llm_max:
                reasons.append(
                    f"LLM lane busy ({self._llm_in_use}/{self._llm_max})"
                )
        if ram_mb and snap.mem_available_kb is not None:
            available_mb = snap.mem_available_kb // 1024
            # Preserve 10% of total RAM as a safety margin when total is known.
            reserve_mb = (
                (snap.mem_total_kb // 1024) // 10 if snap.mem_total_kb else 0
            )
            if ram_mb > max(0, available_mb - reserve_mb):
                reasons.append(
                    f"projected RAM {ram_mb}MB exceeds safe available "
                    f"{max(0, available_mb - reserve_mb)}MB"
                )
        throttled, pressure_reason = self._pressure(snap, prof)
        # Under pressure, cheap I/O may still proceed so the pipeline does not
        # deadlock; heavy CPU/RAM/LLM work is deferred.
        if throttled and (cost > 2 or slots or ram_mb >= 256):
            reasons.append(pressure_reason)
        allowed = not reasons
        return AdmissionDecision(
            allowed=allowed,
            reason="; ".join(reasons) if reasons else "admitted",
            cost_units=cost,
            expected_ram_mb=ram_mb,
            llm_slots=slots,
            budget_units=budget,
        )

    @contextmanager
    def llm_lane(self, *, kind: str = "llm") -> Iterator[None]:
        """Acquire the globally shared LLM capacity lane.

        Calls wait instead of failing when full.  While occupied, the Execution
        Planner can see the lane as unavailable and prefer non-LLM work.
        """
        self._llm_lane.acquire()
        budget = self._cost_budgets.get(
            self._default_profile, self._cost_budgets["balanced"]
        )
        # A single configured task must always be able to make progress even
        # under a smaller profile budget; concurrent tasks remain constrained.
        task_cost = min(
            self._llm_cost_units.get(kind, self._llm_cost_units["default"]),
            budget,
        )
        with self._lock:
            self._llm_in_use += 1
            self._cost_in_use += task_cost
        try:
            yield
        finally:
            with self._lock:
                self._llm_in_use = max(0, self._llm_in_use - 1)
                self._cost_in_use = max(0, self._cost_in_use - task_cost)
            self._llm_lane.release()

    @property
    def llm_capacity(self) -> dict[str, int]:
        with self._lock:
            return {
                "limit": self._llm_max,
                "in_use": self._llm_in_use,
                "available": max(0, self._llm_max - self._llm_in_use),
                "cost_in_use": self._cost_in_use,
            }

    @staticmethod
    def _clamp_to_work(value: int, work: int | None) -> int:
        if work is None:
            return max(1, value)
        return max(1, min(value, max(1, int(work))))

    def _pressure(
        self, snap: SystemSnapshot, prof: ResourceProfile
    ) -> tuple[bool, str]:
        reasons: list[str] = []
        if snap.load_pressure is not None and snap.load_pressure >= self.LOAD_PRESSURE_HIGH:
            reasons.append(
                f"CPU load pressure {snap.load_pressure:.2f} ≥ {self.LOAD_PRESSURE_HIGH}"
            )
        if snap.ram_used_fraction is not None and snap.ram_used_fraction >= self.RAM_USED_HIGH:
            reasons.append(
                f"RAM used {snap.ram_used_fraction:.0%} ≥ {self.RAM_USED_HIGH:.0%}"
            )
        if snap.thermal_monitored and snap.thermal_c is not None:
            if snap.thermal_c >= self.THERMAL_C_HIGH:
                self._thermal_hold = True
                reasons.append(f"thermal {snap.thermal_c:.0f}°C ≥ {self.THERMAL_C_HIGH:.0f}°C")
            elif self._thermal_hold and snap.thermal_c > self.THERMAL_C_RESUME:
                reasons.append(
                    f"thermal still elevated {snap.thermal_c:.0f}°C "
                    f"(resume below {self.THERMAL_C_RESUME:.0f}°C)"
                )
            elif self._thermal_hold and snap.thermal_c <= self.THERMAL_C_RESUME:
                self._thermal_hold = False
        # Also throttle if we're clearly above the profile's soft targets.
        if (
            snap.load_pressure is not None
            and snap.load_pressure >= prof.cpu_target + 0.25
        ):
            reasons.append(
                f"load {snap.load_pressure:.2f} well above profile target {prof.cpu_target:.2f}"
            )
        if reasons:
            return True, "; ".join(reasons)
        return False, ""

    @staticmethod
    def _posture_message(snap: SystemSnapshot) -> str:
        parts = ["caps enforced"]
        if snap.load_pressure is not None or snap.ram_used_fraction is not None:
            parts.append("CPU/RAM monitored")
        else:
            parts.append("CPU/RAM not fully monitored")
        if snap.thermal_monitored:
            parts.append(f"thermal monitored ({snap.thermal_c:.0f}°C)" if snap.thermal_c else "thermal monitored")
        else:
            parts.append("thermal not monitored")
        parts.append("power not monitored")
        return "; ".join(parts)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        capacity = self.llm_capacity
        return HealthStatus.ok(
            "resource manager ready",
            max_worker_threads=self._max_worker_threads,
            llm_limit=capacity["limit"],
            llm_in_use=capacity["in_use"],
        )
