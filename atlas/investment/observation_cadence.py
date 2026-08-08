"""LI.3a / LQ.2 — resource-aware observation & evolution cadence (Host Guard)."""

from __future__ import annotations

from typing import Any

VERSION = "li.3a.observation_cadence"
EVOLUTION_VERSION = "lq.2.evolution_cadence"


def observation_cadence_budget(
    host_guard: Any | None,
    *,
    worker_type: str = "market_observer",
    requested: int = 20,
    reduced: int = 5,
) -> dict[str, Any]:
    """Return how many mark-snapshots this tick may record.

    When Host Guard defers, return a reduced (or zero) budget with an honest reason.
    """
    return _cadence_budget(
        host_guard,
        worker_type=worker_type,
        requested=requested,
        reduced=reduced,
        version=VERSION,
    )


def evolution_cadence_budget(
    host_guard: Any | None,
    *,
    worker_type: str = "decision_evolution",
    requested: int = 20,
    reduced: int = 5,
) -> dict[str, Any]:
    """LQ.2 — how many due revisits this tick may complete (never invent coverage)."""
    return _cadence_budget(
        host_guard,
        worker_type=worker_type,
        requested=requested,
        reduced=reduced,
        version=EVOLUTION_VERSION,
    )


def _cadence_budget(
    host_guard: Any | None,
    *,
    worker_type: str,
    requested: int,
    reduced: int,
    version: str,
) -> dict[str, Any]:
    req = max(0, int(requested))
    red = max(0, min(req, int(reduced)))
    if host_guard is None:
        return {
            "allowed": True,
            "budget": req,
            "reason": "no_host_guard",
            "version": version,
        }
    try:
        ok, reason = host_guard.can_run_tick(worker_type=worker_type)
    except Exception:  # noqa: BLE001
        return {
            "allowed": True,
            "budget": red,
            "reason": "host_guard_error_degraded",
            "version": version,
        }
    if ok:
        return {
            "allowed": True,
            "budget": req,
            "reason": str(reason or "ok"),
            "version": version,
        }
    return {
        "allowed": False,
        "budget": 0 if "critical" in str(reason).lower() else red,
        "reason": f"host_guard:{reason}",
        "version": version,
    }
