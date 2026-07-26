"""Dynamic budgets with hysteresis (IR-RO4).

Under host pressure, shrink *effective* tick slots and pool preferences.
When idle long enough, grow back — never above the hard env ceiling.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from atlas.core.resources.profiles import get_profile


@dataclass
class BudgetSnapshot:
    hard_tick_ceiling: int
    preferred_ticks: int
    effective_ticks: int
    pressure: bool
    pressure_reason: str
    profile: str
    hysteresis: str  # rising | falling | steady

    def as_dict(self) -> dict[str, Any]:
        return {
            "hard_tick_ceiling": self.hard_tick_ceiling,
            "preferred_ticks": self.preferred_ticks,
            "effective_ticks": self.effective_ticks,
            "pressure": self.pressure,
            "pressure_reason": self.pressure_reason,
            "profile": self.profile,
            "hysteresis": self.hysteresis,
        }


class DynamicBudgetController:
    """IR-RO4 — effective concurrency inside hard ceilings + hysteresis."""

    name = "dynamic_budgets"
    VERSION = "ro4.1"

    def __init__(
        self,
        *,
        hard_tick_ceiling: int,
        profile: str = "conservative",
        pressure_fn: Callable[[], tuple[bool, str]] | None = None,
        release_after_seconds: float = 120.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._hard = max(1, int(hard_tick_ceiling))
        self._profile = (profile or "conservative").strip().lower()
        self._pressure_fn = pressure_fn
        self._release_after = max(10.0, float(release_after_seconds))
        self._logger = logger or logging.getLogger("atlas.resources.budgets")
        self._lock = threading.Lock()
        self._under_pressure = False
        self._pressure_since: float | None = None
        self._clear_since: float | None = None
        self._last_reason = ""

    def set_profile(self, profile: str) -> None:
        self._profile = (profile or "conservative").strip().lower()

    def preferred_ticks(self) -> int:
        prof = get_profile(self._profile)
        preferred = int(getattr(prof, "preferred_tick_slots", 2) or 2)
        return max(1, min(self._hard, preferred))

    def _read_pressure(self) -> tuple[bool, str]:
        if self._pressure_fn is None:
            return False, ""
        try:
            return self._pressure_fn()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("pressure probe failed: %s", exc)
            return False, ""

    def effective_tick_slots(self, hard_ceiling: int | None = None) -> int:
        hard = max(1, int(hard_ceiling if hard_ceiling is not None else self._hard))
        preferred = max(1, min(hard, self.preferred_ticks()))
        pressure, reason = self._read_pressure()
        now = time.time()
        with self._lock:
            if pressure:
                self._under_pressure = True
                self._pressure_since = self._pressure_since or now
                self._clear_since = None
                self._last_reason = reason or "pressure"
                # Under pressure: shrink to at least 1, prefer half of preferred (floor 1).
                return max(1, min(preferred, max(1, preferred // 2)))
            # Clearing pressure — wait for hysteresis before growing back.
            if self._under_pressure:
                if self._clear_since is None:
                    self._clear_since = now
                if now - self._clear_since < self._release_after:
                    return max(1, min(preferred, max(1, preferred // 2)))
                self._under_pressure = False
                self._pressure_since = None
                self._clear_since = None
                self._last_reason = ""
            return preferred

    def snapshot(self) -> dict[str, Any]:
        hard = self._hard
        preferred = self.preferred_ticks()
        effective = self.effective_tick_slots(hard)
        pressure, reason = self._read_pressure()
        hyst = "steady"
        with self._lock:
            if self._under_pressure and not pressure:
                hyst = "rising"  # recovering toward preferred
            elif pressure:
                hyst = "falling"
        return BudgetSnapshot(
            hard_tick_ceiling=hard,
            preferred_ticks=preferred,
            effective_ticks=effective,
            pressure=pressure or self._under_pressure,
            pressure_reason=reason or self._last_reason,
            profile=self._profile,
            hysteresis=hyst,
        ).as_dict() | {"version": self.VERSION}
