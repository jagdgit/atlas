"""Work Admission — Should run *now*? (IR-RO10).

Complements Host Guard (Can?) and Admission Contract. Returns whether timing
policy allows this work class to run at this moment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from atlas.core.resources.work_profile import (
    SERVICE_BATCH,
    SERVICE_INTERACTIVE,
    SERVICE_NORMAL,
    SERVICE_REALTIME,
    normalize_service_class,
)


@dataclass(frozen=True)
class ShouldRunVerdict:
    allowed: bool
    reason: str
    run_at_hint: str | None = None  # ISO hint when deferred to a window

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "run_at_hint": self.run_at_hint,
        }


class WorkAdmissionPolicy:
    """IR-RO10 — schedule windows / idle-only classes."""

    name = "work_admission"
    VERSION = "ro10.1"

    def __init__(
        self,
        *,
        batch_quiet_start_hour: int = 22,  # local-ish UTC default overnight
        batch_quiet_end_hour: int = 6,
        enforce_batch_window: bool = False,  # off by default — opt-in
        clock: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._batch_start = int(batch_quiet_start_hour) % 24
        self._batch_end = int(batch_quiet_end_hour) % 24
        self._enforce_batch = bool(enforce_batch_window)
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.resources.admission_policy")

    def _now(self) -> datetime:
        if self._clock is not None and hasattr(self._clock, "now"):
            try:
                return self._clock.now()
            except Exception:  # noqa: BLE001
                pass
        return datetime.now(timezone.utc)

    def in_batch_window(self, now: datetime | None = None) -> bool:
        """True when current hour is inside the overnight BATCH window."""
        now = now or self._now()
        hour = now.hour
        start, end = self._batch_start, self._batch_end
        if start == end:
            return True  # window disabled / always
        if start < end:
            return start <= hour < end
        # wraps midnight (e.g. 22→6)
        return hour >= start or hour < end

    def should_run_now(
        self,
        *,
        service_class: str | None,
        force: bool = False,
        now: datetime | None = None,
    ) -> ShouldRunVerdict:
        if force:
            return ShouldRunVerdict(True, "forced")
        cls = normalize_service_class(service_class)
        now = now or self._now()

        if cls in {SERVICE_REALTIME, SERVICE_INTERACTIVE, "REALTIME_CRITICAL", "REALTIME_STANDARD"}:
            return ShouldRunVerdict(True, "realtime_or_interactive")

        if cls == SERVICE_NORMAL:
            return ShouldRunVerdict(True, "normal_always")

        # BATCH (and unknown treated as batch-ish only if explicitly BATCH)
        if cls == SERVICE_BATCH and self._enforce_batch:
            if self.in_batch_window(now):
                return ShouldRunVerdict(True, "batch_quiet_window")
            # Hint next window start
            hint_hour = self._batch_start
            hint = now.replace(hour=hint_hour, minute=0, second=0, microsecond=0)
            if hint <= now:
                from datetime import timedelta

                hint = hint + timedelta(days=1)
            return ShouldRunVerdict(
                False,
                f"batch_outside_quiet_window ({self._batch_start:02d}:00–{self._batch_end:02d}:00)",
                run_at_hint=hint.isoformat(),
            )

        return ShouldRunVerdict(True, "policy_default_allow")

    def snapshot(self) -> dict[str, Any]:
        now = self._now()
        return {
            "version": self.VERSION,
            "enforce_batch_window": self._enforce_batch,
            "batch_quiet_start_hour": self._batch_start,
            "batch_quiet_end_hour": self._batch_end,
            "in_batch_window": self.in_batch_window(now),
            "note": (
                "Should-run-now complements Host Guard. "
                "Enable enforce_batch_window to defer BATCH to quiet hours."
            ),
        }
