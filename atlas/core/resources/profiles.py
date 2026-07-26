"""Resource profiles — policies for how aggressively Atlas uses the machine (3.2c).

Profiles never override operator env/config hard caps. Overnight may prefer +1/+2
workers only *inside* ``max_worker_threads``. Full pools → slower, never job failure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    name: str
    cpu_target: float  # 0..1 desired utilization signal
    ram_target: float
    worker_bonus: int  # extra preferred workers vs baseline (within hard max)
    description: str
    preferred_tick_slots: int = 2  # IR-RO8 — preferred concurrency under hard ceiling


PROFILES: dict[str, ResourceProfile] = {
    "conservative": ResourceProfile(
        name="conservative",
        cpu_target=0.40,
        ram_target=0.50,
        worker_bonus=0,
        preferred_tick_slots=2,
        description="Laptop / background — stay light",
    ),
    "balanced": ResourceProfile(
        name="balanced",
        cpu_target=0.70,
        ram_target=0.70,
        worker_bonus=0,
        preferred_tick_slots=3,
        description="Default daily research",
    ),
    "maximum": ResourceProfile(
        name="maximum",
        cpu_target=0.95,
        ram_target=0.90,
        worker_bonus=1,
        preferred_tick_slots=4,
        description="Dedicated box — aggressive within caps",
    ),
    "overnight": ResourceProfile(
        name="overnight",
        cpu_target=0.95,
        ram_target=0.90,
        worker_bonus=2,
        preferred_tick_slots=4,
        description="Unattended — prefer +1/+2 workers inside env max; time OK",
    ),
}


def get_profile(name: str | None) -> ResourceProfile:
    key = (name or "balanced").strip().lower()
    return PROFILES.get(key, PROFILES["balanced"])
