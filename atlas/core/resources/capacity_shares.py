"""ARMF Phase C — program capacity shares + borrowing (above Host Guard).

Reserves a **floor** of effective tick slots per Intelligence Program when that
program has demand. Idle programs loan unused floor (borrowing). Host Guard
remains the machine-safety veto; this module only answers *who deserves the
next yes* among admitted candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Locked illustrative shares (OPS plan §8b) — fractions of *effective* tick budget.
DEFAULT_PROGRAM_SHARES: dict[str, float] = {
    "market_intelligence": 0.25,
    "engineering_intelligence": 0.25,
    "personal_intelligence": 0.15,
    "knowledge": 0.15,
    "archive": 0.10,
    "emergency": 0.10,
}

# Programs that always get a floor of at least 1 when they have demand and eff≥1.
FLOOR_MIN_PROGRAMS: frozenset[str] = frozenset(
    {
        "market_intelligence",
        "engineering_intelligence",
        "personal_intelligence",
    }
)


def normalize_program_id(raw: str | None) -> str:
    p = (raw or "").strip()
    if not p:
        return "unassigned"
    if "knowledge" in p and "market" not in p and "engineering" not in p:
        return "knowledge"
    return p


@dataclass(frozen=True, slots=True)
class ProgramCapacityPolicy:
    """Compute floors and whether an admit would steal another program's floor."""

    shares: Mapping[str, float] = None  # type: ignore[assignment]
    floor_min_programs: frozenset[str] = FLOOR_MIN_PROGRAMS
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "shares",
            dict(self.shares) if self.shares is not None else dict(DEFAULT_PROGRAM_SHARES),
        )

    def floor_slots(self, program_id: str, effective_slots: int) -> int:
        """Reserved slots for ``program_id`` when it has demand (0 = no floor)."""
        if not self.enabled or effective_slots <= 0:
            return 0
        prog = normalize_program_id(program_id)
        share = float(self.shares.get(prog, 0.0) or 0.0)
        if share <= 0:
            return 0
        raw = int(effective_slots * share)
        if prog in self.floor_min_programs:
            return max(1, raw) if effective_slots >= 1 else 0
        return max(0, raw)

    def floors(self, effective_slots: int) -> dict[str, int]:
        return {
            p: self.floor_slots(p, effective_slots)
            for p in self.shares
            if self.floor_slots(p, effective_slots) > 0
        }

    def reserved_for_others(
        self,
        *,
        admit_program: str,
        effective_slots: int,
        program_inflight: Mapping[str, int],
        programs_with_demand: set[str] | frozenset[str],
    ) -> int:
        """Slots that must stay free for other under-floor programs with demand.

        Idle programs (no demand) contribute **0** — their share is borrowable.
        """
        if not self.enabled or effective_slots <= 0:
            return 0
        admit = normalize_program_id(admit_program)
        reserved = 0
        for prog, floor in self.floors(effective_slots).items():
            if prog == admit:
                continue
            if prog not in programs_with_demand:
                continue  # borrow
            under = floor - int(program_inflight.get(prog, 0) or 0)
            if under > 0:
                reserved += under
        return reserved

    def blocks_admit(
        self,
        *,
        admit_program: str,
        effective_slots: int,
        total_inflight: int,
        program_inflight: Mapping[str, int],
        programs_with_demand: set[str] | frozenset[str],
    ) -> str | None:
        """Return deferral reason if admit would violate another program's floor."""
        if not self.enabled or effective_slots <= 0:
            return None
        prog = normalize_program_id(admit_program)
        my_floor = self.floor_slots(prog, effective_slots)
        my_in = int(program_inflight.get(prog, 0) or 0)
        # Claiming own floor is always allowed (Host Guard / global cap still apply).
        if my_floor > 0 and my_in < my_floor:
            return None
        reserved = self.reserved_for_others(
            admit_program=prog,
            effective_slots=effective_slots,
            program_inflight=program_inflight,
            programs_with_demand=programs_with_demand,
        )
        if reserved <= 0:
            return None
        # After this admit, remaining free slots would be eff - (total+1).
        remaining_after = effective_slots - (int(total_inflight) + 1)
        if remaining_after < reserved:
            return (
                f"program_floor {prog} inflight={my_in}/{my_floor or 0} "
                f"reserved_for_peers={reserved}"
            )
        return None

    def as_dict(self, *, effective_slots: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": "armf.c1",
            "enabled": self.enabled,
            "shares": dict(self.shares),
            "floor_min_programs": sorted(self.floor_min_programs),
        }
        if effective_slots is not None:
            out["floors"] = self.floors(int(effective_slots))
            out["effective_slots"] = int(effective_slots)
        return out


def policy_from_config(raw: Mapping[str, Any] | None) -> ProgramCapacityPolicy:
    """Build policy from ``resources.program_shares`` config blob."""
    raw = raw or {}
    enabled = bool(raw.get("enabled", True))
    shares = raw.get("shares")
    if not isinstance(shares, dict) or not shares:
        shares = DEFAULT_PROGRAM_SHARES
    cleaned = {
        str(k): float(v)
        for k, v in shares.items()
        if v is not None and float(v) >= 0
    }
    return ProgramCapacityPolicy(shares=cleaned, enabled=enabled)
