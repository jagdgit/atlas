"""Machine profile detection (IR-RO8).

Suggest conservative / balanced / maximum from host RAM + CPU count.
Preferred tick slots (2 / 3 / 4) never exceed the configured hard ceiling.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from atlas.core.resources.profiles import PROFILES, get_profile


@dataclass(frozen=True)
class MachineProfileSuggestion:
    suggested_profile: str
    reason: str
    ram_gb: float | None
    cpu_count: int | None
    preferred_tick_slots: int
    hard_tick_ceiling: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "suggested_profile": self.suggested_profile,
            "reason": self.reason,
            "ram_gb": self.ram_gb,
            "cpu_count": self.cpu_count,
            "preferred_tick_slots": self.preferred_tick_slots,
            "hard_tick_ceiling": self.hard_tick_ceiling,
        }


def detect_machine_profile(
    *,
    hard_tick_ceiling: int | None = None,
    mem_total_kb: int | None = None,
    cpu_count: int | None = None,
    snapshot_fn: Callable[[], Any] | None = None,
    logger: logging.Logger | None = None,
) -> MachineProfileSuggestion:
    """Heuristic host → profile suggestion (solar-plant safe / shared desktop)."""
    log = logger or logging.getLogger("atlas.resources.machine_profile")
    ram_gb = None
    cpus = cpu_count if cpu_count is not None else os.cpu_count()

    if mem_total_kb is None and snapshot_fn is not None:
        try:
            snap = snapshot_fn()
            mem_total_kb = getattr(snap, "mem_total_kb", None)
            if mem_total_kb is None and isinstance(snap, dict):
                mem = snap.get("memory") or {}
                # HostMetrics uses bytes in some paths — prefer kb from monitor.
                total = mem.get("total")
                if total and total > 10_000_000:  # likely bytes
                    mem_total_kb = int(total) // 1024
                elif total:
                    mem_total_kb = int(total)
        except Exception as exc:  # noqa: BLE001
            log.debug("machine profile snapshot failed: %s", exc)

    if mem_total_kb is None:
        try:
            from atlas.core.resources.monitor import read_snapshot

            snap = read_snapshot(log)
            mem_total_kb = snap.mem_total_kb
        except Exception:  # noqa: BLE001
            mem_total_kb = None

    if mem_total_kb:
        ram_gb = round(mem_total_kb / (1024 * 1024), 1)

    # Heuristic: shared 16GB desktop → conservative; 32GB+ with many cores → balanced/max.
    if ram_gb is not None and ram_gb <= 18:
        suggested = "conservative"
        reason = f"~{ram_gb} GB RAM — prefer conservative (coexist with OS/prod/Ollama)"
    elif ram_gb is not None and ram_gb >= 48 and (cpus or 0) >= 12:
        suggested = "maximum"
        reason = f"~{ram_gb} GB RAM · {cpus} CPUs — maximum within hard ceilings"
    elif ram_gb is not None and ram_gb >= 28:
        suggested = "balanced"
        reason = f"~{ram_gb} GB RAM — balanced daily research"
    else:
        suggested = "balanced"
        reason = "default balanced (insufficient host signals)"

    prof = get_profile(suggested)
    preferred = int(getattr(prof, "preferred_tick_slots", 2) or 2)
    hard = int(hard_tick_ceiling) if hard_tick_ceiling else None
    if hard is not None:
        preferred = max(1, min(hard, preferred))

    return MachineProfileSuggestion(
        suggested_profile=suggested,
        reason=reason,
        ram_gb=ram_gb,
        cpu_count=cpus,
        preferred_tick_slots=preferred,
        hard_tick_ceiling=hard,
    )


def profile_catalog() -> list[dict[str, Any]]:
    out = []
    for name, prof in PROFILES.items():
        out.append(
            {
                "name": name,
                "description": prof.description,
                "preferred_tick_slots": getattr(prof, "preferred_tick_slots", 2),
                "cpu_target": prof.cpu_target,
                "ram_target": prof.ram_target,
            }
        )
    return out
