"""ARMF Phase A — program health strip (heuristic v0).

Rolls worker + mission-queue signals into per-program status chips for Ops.
Phase C will add capacity shares, Research Velocity, and true at-risk detection.
"""

from __future__ import annotations

from typing import Any

from atlas.ops.worker_states import (
    STATE_AT_RISK,
    STATE_READY,
    STATE_RUNNING_TICK,
    STATE_STARVED,
    STATE_WAITING_HOST,
)

# Display order for the Ops strip.
PROGRAM_ORDER: tuple[str, ...] = (
    "market_intelligence",
    "engineering_intelligence",
    "personal_intelligence",
    "archive",
    "knowledge",
    "unassigned",
)

PROGRAM_LABELS: dict[str, str] = {
    "market_intelligence": "Market",
    "engineering_intelligence": "Engineering",
    "personal_intelligence": "Personal",
    "archive": "Archive",
    "knowledge": "Knowledge",
    "unassigned": "Unassigned",
}

STATUS_HEALTHY = "healthy"
STATUS_AT_RISK = "at_risk"
STATUS_CONGESTED = "congested"
STATUS_IDLE = "idle"
STATUS_QUIET = "quiet"


def _program_key(owner: dict[str, Any] | None, *, service_class: str | None = None) -> str:
    prog = None
    if isinstance(owner, dict):
        prog = owner.get("program") or owner.get("program_id")
    if prog:
        p = str(prog)
        if "knowledge" in p and "market" not in p:
            return "knowledge"
        return p
    sc = (service_class or "").lower()
    if "archive" in sc:
        return "archive"
    return "unassigned"


def _empty_bucket(program_id: str) -> dict[str, Any]:
    return {
        "program": program_id,
        "label": PROGRAM_LABELS.get(program_id, program_id),
        "status": STATUS_IDLE,
        "starved": 0,
        "at_risk": 0,
        "waiting_host": 0,
        "ready": 0,
        "running_ticks": 0,
        "workers": 0,
        "missions_waiting_host": 0,
        "missions_running": 0,
        "detail": "",
    }


def summarize_program_health(
    worker_rows: list[dict[str, Any]] | None = None,
    queue_items: list[dict[str, Any]] | None = None,
    *,
    host_guard: dict[str, Any] | None = None,
    hide_types: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Heuristic v0 program health for Ops (A5).

    Status rules (simple, explainable):
    - **congested** (Archive): archive slots full and something waiting on archive.
    - **at_risk**: starved workers ≥ 1, or mission WAITING_HOST ≥ 3 for that program.
    - **healthy**: activity without starved / heavy waits.
    - **quiet**: workers present, no starved/waiting pressure.
    - **idle**: nothing classified for that program.
    """
    hide = hide_types or frozenset()
    buckets: dict[str, dict[str, Any]] = {
        pid: _empty_bucket(pid) for pid in PROGRAM_ORDER
    }

    for row in worker_rows or []:
        if not isinstance(row, dict):
            continue
        wtype = str(row.get("type") or "")
        if wtype in hide:
            continue
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        key = _program_key(owner, service_class=row.get("service_class"))
        if key not in buckets:
            buckets[key] = _empty_bucket(key)
        b = buckets[key]
        b["workers"] += 1
        state = row.get("ops_state")
        if state == STATE_STARVED:
            b["starved"] += 1
        elif state == STATE_AT_RISK:
            b["at_risk"] += 1
        elif state == STATE_WAITING_HOST:
            b["waiting_host"] += 1
        elif state == STATE_READY:
            b["ready"] += 1
        elif state == STATE_RUNNING_TICK:
            b["running_ticks"] += 1

    for item in queue_items or []:
        if not isinstance(item, dict):
            continue
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        reason = str(item.get("reason") or item.get("wait_reason") or "").lower()
        key = _program_key(owner, service_class=item.get("service_class"))
        if "archive" in reason:
            key = "archive"
        if key not in buckets:
            buckets[key] = _empty_bucket(key)
        b = buckets[key]
        state = str(item.get("state") or "")
        if state == "WAITING_HOST":
            b["missions_waiting_host"] += 1
        elif state == "RUNNING":
            b["missions_running"] += 1

    hg = host_guard or {}
    archive_running = int(hg.get("archive_workers_running") or 0)
    archive_max = int(hg.get("max_archive_workers") or 1)
    archive_full = archive_max > 0 and archive_running >= archive_max

    programs: list[dict[str, Any]] = []
    for pid in list(PROGRAM_ORDER) + [
        k for k in buckets if k not in PROGRAM_ORDER
    ]:
        b = buckets.get(pid)
        if b is None:
            continue
        starved = int(b["starved"])
        at_risk_n = int(b.get("at_risk") or 0)
        wh_w = int(b["waiting_host"])
        wh_m = int(b["missions_waiting_host"])
        workers = int(b["workers"])
        activity = workers + wh_m + int(b["missions_running"]) + int(b["running_ticks"])

        if pid == "archive" and archive_full and (wh_m > 0 or wh_w > 0):
            status = STATUS_CONGESTED
            detail = f"slot full ({archive_running}/{archive_max})"
        elif starved >= 1 or at_risk_n >= 1 or wh_m >= 3 or (wh_w >= 2 and starved == 0 and wh_m >= 1):
            status = STATUS_AT_RISK
            parts = []
            if starved:
                parts.append(f"{starved} starved")
            if at_risk_n:
                parts.append(f"{at_risk_n} at risk")
            if wh_m:
                parts.append(f"{wh_m} WAITING_HOST")
            elif wh_w:
                parts.append(f"{wh_w} waiting host")
            detail = ", ".join(parts) or "pressure"
        elif activity == 0:
            status = STATUS_IDLE
            detail = "no active work"
        elif starved == 0 and wh_m == 0 and wh_w == 0:
            status = STATUS_HEALTHY if (b["running_ticks"] or b["ready"] or b["missions_running"]) else STATUS_QUIET
            detail = "ok"
        else:
            status = STATUS_QUIET
            detail = f"{wh_w} waiting host" if wh_w else "ok"

        b["status"] = status
        b["detail"] = detail
        # Always show core programs; hide empty unassigned/knowledge noise.
        if pid in ("unassigned", "knowledge") and activity == 0 and starved == 0:
            continue
        if pid == "archive" and activity == 0 and not archive_full:
            # Still show archive so operators see the lane.
            b["status"] = STATUS_QUIET if archive_running else STATUS_IDLE
            b["detail"] = f"{archive_running}/{archive_max} slots"
        programs.append(b)

    # Ensure Market/Eng/Personal always appear.
    shown = {p["program"] for p in programs}
    for pid in ("market_intelligence", "engineering_intelligence", "personal_intelligence", "archive"):
        if pid not in shown:
            programs.append(buckets[pid])

    order_idx = {pid: i for i, pid in enumerate(PROGRAM_ORDER)}
    programs.sort(key=lambda p: order_idx.get(p["program"], 50))

    at_risk_n = sum(1 for p in programs if p["status"] in (STATUS_AT_RISK, STATUS_CONGESTED))
    return {
        "version": "armf.a5",
        "programs": programs,
        "at_risk_count": at_risk_n,
        "note": "heuristic v0 — capacity shares & Research Velocity in Phase C",
    }


def capacity_idle_signal(
    *,
    tick_inflight: int,
    waiting_host_missions: int,
    waiting_host_workers: int = 0,
    host_deferring: bool | None = None,
) -> dict[str, Any]:
    """A3 — RUNNING ticks empty but work waiting on Host Guard / budget."""
    active = int(tick_inflight) == 0 and (
        int(waiting_host_missions) > 0 or int(waiting_host_workers) > 0
    )
    return {
        "active": active,
        "tick_inflight": int(tick_inflight),
        "waiting_host_missions": int(waiting_host_missions),
        "waiting_host_workers": int(waiting_host_workers),
        "host_deferring": host_deferring,
        "message": (
            "Atlas is not off — capacity policy / Host Guard is deferring work "
            "(WAITING_HOST with no ticks in flight)."
            if active
            else ""
        ),
    }
