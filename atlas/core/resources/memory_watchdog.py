"""IR-RO11 — Runtime Memory Watchdog (Layer 2).

Admission (Host Guard) answers *Can we start?* This module answers *May this
tick keep growing?* by sampling process RSS and host available RAM during a tick.

v0 is honest about the monolith: Atlas is still one Python process, so per-worker
"usage" is approximated as **RSS growth since tick start** plus a process-wide
soft ceiling. True per-worker isolation needs process classes (follow-on).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from atlas.core.resources.monitor import read_snapshot

ACTION_CONTINUE = "continue"
ACTION_YIELD_TICK = "yield_tick"  # end tick early; schedule resumes later
ACTION_PAUSE_WORKER = "pause_worker"  # capacity-queue until host recovers


def process_rss_mb() -> float | None:
    """Current process RSS in MiB (Linux /proc; None if unavailable)."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # VmRSS: <kb> kB
                    return float(parts[1]) / 1024.0
    except (OSError, IndexError, ValueError, TypeError):
        pass
    try:
        import resource

        # ru_maxrss is KB on Linux, bytes on macOS — prefer /proc above.
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if os.uname().sysname == "Darwin":
            return float(usage) / (1024.0 * 1024.0)
        return float(usage) / 1024.0
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class MemoryVerdict:
    ok: bool
    action: str
    reason: str
    rss_mb: float | None
    delta_mb: float | None
    budget_mb: int
    host_available_mb: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "reason": self.reason,
            "rss_mb": round(self.rss_mb, 1) if self.rss_mb is not None else None,
            "delta_mb": round(self.delta_mb, 1) if self.delta_mb is not None else None,
            "budget_mb": self.budget_mb,
            "host_available_mb": (
                round(self.host_available_mb, 1)
                if self.host_available_mb is not None
                else None
            ),
        }


@dataclass
class TickMemorySession:
    """Per-tick measurement window bound to a worker budget."""

    worker_id: str
    worker_type: str
    budget_mb: int
    baseline_rss_mb: float | None
    soft_ratio: float = 0.85
    process_rss_soft_mb: int | None = None
    host_ram_reserve_mb: int = 2048
    check_fn: Callable[["TickMemorySession"], MemoryVerdict] | None = None
    checks: int = 0
    last_verdict: MemoryVerdict | None = None

    def check(self, *, force: bool = False) -> MemoryVerdict:
        if self.check_fn is None:
            return MemoryVerdict(
                ok=True,
                action=ACTION_CONTINUE,
                reason="no_watchdog",
                rss_mb=process_rss_mb(),
                delta_mb=0.0,
                budget_mb=self.budget_mb,
            )
        verdict = self.check_fn(self, force=force)
        self.checks += 1
        self.last_verdict = verdict
        return verdict


@dataclass
class RuntimeMemoryWatchdog:
    """Layer 2 memory ownership for Resource OS (IR-RO11 v0)."""

    name: str = "memory_watchdog"
    VERSION: str = "ro11.v0"
    host_ram_reserve_mb: int = 2048
    # Soft ceiling for the whole Atlas process (below typical systemd MemoryMax).
    process_rss_soft_mb: int = 6144
    soft_ratio: float = 0.85
    min_check_interval_s: float = 1.0
    logger: logging.Logger | None = None
    _yields: int = field(default=0, init=False)
    _pauses: int = field(default=0, init=False)
    _checks: int = field(default=0, init=False)
    _last_status: dict[str, Any] = field(default_factory=dict, init=False)
    _last_check_mono: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.logger = self.logger or logging.getLogger("atlas.resources.memory_watchdog")

    def begin_tick(
        self,
        *,
        worker_id: str,
        worker_type: str = "",
        budget_mb: int | None = None,
    ) -> TickMemorySession:
        budget = max(64, int(budget_mb or 512))
        return TickMemorySession(
            worker_id=str(worker_id),
            worker_type=str(worker_type or ""),
            budget_mb=budget,
            baseline_rss_mb=process_rss_mb(),
            soft_ratio=self.soft_ratio,
            process_rss_soft_mb=self.process_rss_soft_mb,
            host_ram_reserve_mb=self.host_ram_reserve_mb,
            check_fn=self._evaluate,
        )

    def snapshot(self) -> dict[str, Any]:
        rss = process_rss_mb()
        host = {}
        try:
            snap = read_snapshot(self.logger)
            host = {
                "mem_available_mb": (
                    (snap.mem_available_kb / 1024.0)
                    if snap.mem_available_kb is not None
                    else None
                ),
                "ram_used_fraction": snap.ram_used_fraction,
            }
        except Exception:  # noqa: BLE001
            host = {}
        return {
            "version": self.VERSION,
            "layer": 2,
            "policy": "runtime_memory_enforcement",
            "process_rss_mb": round(rss, 1) if rss is not None else None,
            "process_rss_soft_mb": self.process_rss_soft_mb,
            "host_ram_reserve_mb": self.host_ram_reserve_mb,
            "soft_ratio": self.soft_ratio,
            "checks_total": self._checks,
            "yield_tick_total": self._yields,
            "pause_worker_total": self._pauses,
            "host": host,
            "last": dict(self._last_status),
            "note": (
                "IR-RO11 v0: tick RSS delta vs budget + process soft ceiling + "
                "host reserve. systemd MemoryMax remains Layer 3 backstop only."
            ),
        }

    def _evaluate(self, session: TickMemorySession, *, force: bool = False) -> MemoryVerdict:
        now = time.monotonic()
        # Throttle host/proc reads slightly when workers check every file.
        if (
            not force
            and self._last_check_mono
            and (now - self._last_check_mono) < self.min_check_interval_s
            and session.last_verdict is not None
            and session.last_verdict.ok
        ):
            return session.last_verdict

        self._last_check_mono = now
        self._checks += 1
        rss = process_rss_mb()
        baseline = session.baseline_rss_mb
        delta = None if rss is None or baseline is None else max(0.0, rss - baseline)
        host_avail = None
        try:
            snap = read_snapshot(self.logger)
            if snap.mem_available_kb is not None:
                host_avail = snap.mem_available_kb / 1024.0
        except Exception:  # noqa: BLE001
            host_avail = None

        soft_budget = max(64.0, session.budget_mb * session.soft_ratio)
        hard_budget = float(session.budget_mb)

        # 1) Host critically low → pause worker (Host Guard will resume later).
        if host_avail is not None and host_avail < float(session.host_ram_reserve_mb):
            self._pauses += 1
            verdict = MemoryVerdict(
                ok=False,
                action=ACTION_PAUSE_WORKER,
                reason=(
                    f"host_available_mb={host_avail:.0f} < "
                    f"reserve_mb={session.host_ram_reserve_mb}"
                ),
                rss_mb=rss,
                delta_mb=delta,
                budget_mb=session.budget_mb,
                host_available_mb=host_avail,
            )
            self._remember(session, verdict)
            return verdict

        # 2) Whole-process soft ceiling → pause (protect desktop / avoid OOM path).
        ceiling = session.process_rss_soft_mb or self.process_rss_soft_mb
        if rss is not None and ceiling and rss >= float(ceiling):
            self._pauses += 1
            verdict = MemoryVerdict(
                ok=False,
                action=ACTION_PAUSE_WORKER,
                reason=f"process_rss_mb={rss:.0f} >= soft_ceiling_mb={ceiling}",
                rss_mb=rss,
                delta_mb=delta,
                budget_mb=session.budget_mb,
                host_available_mb=host_avail,
            )
            self._remember(session, verdict)
            return verdict

        # 3) Tick growth past budget → yield tick (resume next schedule fire).
        if delta is not None and delta >= hard_budget:
            self._yields += 1
            verdict = MemoryVerdict(
                ok=False,
                action=ACTION_YIELD_TICK,
                reason=(
                    f"tick_rss_delta_mb={delta:.0f} >= budget_mb={session.budget_mb}"
                ),
                rss_mb=rss,
                delta_mb=delta,
                budget_mb=session.budget_mb,
                host_available_mb=host_avail,
            )
            self._remember(session, verdict)
            return verdict

        if delta is not None and delta >= soft_budget:
            self._yields += 1
            verdict = MemoryVerdict(
                ok=False,
                action=ACTION_YIELD_TICK,
                reason=(
                    f"tick_rss_delta_mb={delta:.0f} >= "
                    f"soft_budget_mb={soft_budget:.0f} ({session.soft_ratio:.0%} of "
                    f"{session.budget_mb})"
                ),
                rss_mb=rss,
                delta_mb=delta,
                budget_mb=session.budget_mb,
                host_available_mb=host_avail,
            )
            self._remember(session, verdict)
            return verdict

        verdict = MemoryVerdict(
            ok=True,
            action=ACTION_CONTINUE,
            reason="within_budget",
            rss_mb=rss,
            delta_mb=delta if delta is not None else 0.0,
            budget_mb=session.budget_mb,
            host_available_mb=host_avail,
        )
        self._remember(session, verdict)
        return verdict

    def _remember(self, session: TickMemorySession, verdict: MemoryVerdict) -> None:
        self._last_status = {
            "worker_id": session.worker_id,
            "worker_type": session.worker_type,
            **verdict.as_dict(),
            "checked_at_mono": time.monotonic(),
        }
        if not verdict.ok:
            self.logger.info(
                "IR-RO11 memory %s worker=%s type=%s %s",
                verdict.action,
                session.worker_id[:8],
                session.worker_type or "?",
                verdict.reason,
            )
