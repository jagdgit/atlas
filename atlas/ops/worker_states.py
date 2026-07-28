"""Ops worker state classification (IR-OPS1).

Maps Persistent Workers to explainable Linux-style states for the Operations
dashboard. Pure functions — no I/O — so classification is unit-testable without
Postgres or the WorkerManager.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Primary ops states (mutually exclusive for the breakdown counts).
STATE_RUNNING_TICK = "running_ticks"
STATE_HOLDING_RESERVATION = "holding_reservation"
STATE_READY = "ready"
STATE_WAITING_HOST = "waiting_host"
STATE_WAITING_SCHEDULE = "waiting_schedule"
STATE_WAITING_DEPENDENCY = "waiting_dependency"
STATE_SLEEPING = "sleeping"
STATE_PAUSED = "paused"
STATE_AT_RISK = "at_risk"
STATE_STARVED = "starved"
STATE_SLOW = "slow"
STATE_COMPLETED = "completed"

OPS_STATES = (
    STATE_RUNNING_TICK,
    STATE_HOLDING_RESERVATION,
    STATE_READY,
    STATE_WAITING_HOST,
    STATE_WAITING_SCHEDULE,
    STATE_WAITING_DEPENDENCY,
    STATE_SLEEPING,
    STATE_PAUSED,
    STATE_AT_RISK,
    STATE_STARVED,
    STATE_SLOW,
    STATE_COMPLETED,
)

# Heuristic expected tick duration by worker type (ms). Templates may override via metadata.
DEFAULT_EXPECTED_TICK_MS: dict[str, int] = {
    "market_observer": 2_000,
    "decision_simulation": 5_000,
    "paper_trading": 3_000,
    "portfolio_ledger": 5_000,
    "owner_knowledge": 60_000,
    "personal_observer": 15_000,
    "hello_watcher": 1_000,
}

STARVE_AFTER_SECONDS = 6 * 3600  # 6h without productive progress while eligible
# ARMF C8 — predictive: expected cadence missed well before the 6h starved label.
AT_RISK_AFTER_SECONDS = 30 * 60  # 30 minutes with no productive tick while eligible
AT_RISK_EXPECTED_MULTIPLIER = 30.0  # or ≥ 30× expected_tick_ms
SLOW_RATIO = 5.0  # last tick > expected * ratio → Slow
RECENT_WAIT_SECONDS = 300  # host/budget deferral still "fresh" for Waiting Host
SLEEP_AFTER_TICK_SECONDS = 30  # after a successful tick, treat as Sleeping until due again


def empty_counts() -> dict[str, int]:
    return {s: 0 for s in OPS_STATES}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str) and value:
        try:
            return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def ops_meta(worker: Any) -> dict[str, Any]:
    meta = getattr(worker, "metadata", None)
    if meta is None and isinstance(worker, dict):
        meta = worker.get("metadata")
    if not isinstance(meta, dict):
        return {}
    ops = meta.get("ops")
    return dict(ops) if isinstance(ops, dict) else {}


def expected_tick_ms(
    worker_type: str,
    ops: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    if ops and ops.get("expected_tick_ms") is not None:
        try:
            return max(1, int(ops["expected_tick_ms"]))
        except (TypeError, ValueError):
            pass
    rp = (meta or {}).get("resource_profile")
    if isinstance(rp, dict) and rp.get("expected_tick_ms") is not None:
        try:
            return max(1, int(rp["expected_tick_ms"]))
        except (TypeError, ValueError):
            pass
    return int(DEFAULT_EXPECTED_TICK_MS.get(worker_type, 10_000))


def starvation_age_seconds(worker: Any, *, now: datetime) -> float | None:
    """Seconds since last productive tick (or created_at if never ticked)."""
    last = getattr(worker, "last_tick_at", None)
    if last is None and isinstance(worker, dict):
        last = worker.get("last_tick_at")
    last = _aware(last) if isinstance(last, datetime) else _parse_iso(last)
    if last is None:
        created = getattr(worker, "created_at", None)
        if created is None and isinstance(worker, dict):
            created = worker.get("created_at")
        last = _aware(created) if isinstance(created, datetime) else _parse_iso(created)
    if last is None:
        return None
    return max(0.0, (now - last).total_seconds())


def classify_worker(
    worker: Any,
    *,
    now: datetime | None = None,
    inflight_mission_ids: set[str] | frozenset[str] | None = None,
    holding_reservation: bool = False,
) -> dict[str, Any]:
    """Return primary ops state + timing / wait fields for one worker."""
    now = _aware(now) or datetime.now(timezone.utc)
    inflight = inflight_mission_ids or frozenset()

    if hasattr(worker, "to_dict"):
        # Prefer attribute access below; to_dict only for id fallbacks.
        pass

    wid = getattr(worker, "id", None) or (worker.get("id") if isinstance(worker, dict) else None)
    wtype = getattr(worker, "type", None) or (worker.get("type") if isinstance(worker, dict) else "")
    status = getattr(worker, "status", None) or (worker.get("status") if isinstance(worker, dict) else "")
    mission_id = getattr(worker, "mission_id", None) or (
        worker.get("mission_id") if isinstance(worker, dict) else None
    )
    meta = getattr(worker, "metadata", None)
    if meta is None and isinstance(worker, dict):
        meta = worker.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    ops = ops_meta(worker)
    expected = expected_tick_ms(str(wtype or ""), ops, meta)
    last_ms = ops.get("last_tick_ms")
    avg_ms = ops.get("avg_tick_ms")
    max_ms = ops.get("max_tick_ms")
    age = starvation_age_seconds(worker, now=now)
    wait_reason = ops.get("wait_reason")
    wait_since = _parse_iso(ops.get("wait_since"))

    owner = {
        "program": meta.get("program_id") or ops.get("program_id"),
        "mission": mission_id,
        "worker": wid,
        "portfolio": meta.get("portfolio_key") or meta.get("portfolio_id"),
        "operator": meta.get("operator") or meta.get("created_by"),
        "type": wtype,
    }

    # --- primary state ---------------------------------------------------
    state = STATE_SLEEPING
    reason = None

    if status == "stopped":
        state = STATE_COMPLETED
        reason = "stopped"
    elif status == "failed":
        state = STATE_PAUSED
        reason = "failed"
    elif status == "paused":
        if meta.get("queued_for_capacity"):
            state = STATE_WAITING_HOST
            reason = meta.get("queue_reason") or "queued_for_capacity"
        else:
            state = STATE_PAUSED
            reason = "operator_or_blocked"
    elif holding_reservation:
        state = STATE_HOLDING_RESERVATION
        reason = "reservation_held"
    elif mission_id and str(mission_id) in inflight:
        state = STATE_RUNNING_TICK
        reason = "tick_inflight"
    elif status == "recovering":
        state = STATE_WAITING_SCHEDULE
        reason = "crash_backoff"
    elif wait_reason in ("waiting_dependency", "dependency"):
        state = STATE_WAITING_DEPENDENCY
        reason = wait_reason
    elif wait_reason in ("host_pressure", "budget", "capacity", "queued_for_capacity") and (
        wait_since is None or (now - wait_since).total_seconds() <= RECENT_WAIT_SECONDS
    ):
        state = STATE_WAITING_HOST
        reason = wait_reason
    elif status in ("running", "recovering"):
        # Eligible tickable workers: starved / at_risk / slow / ready / sleeping
        is_starved = age is not None and age >= STARVE_AFTER_SECONDS
        expected_s = max(1.0, float(expected) / 1000.0) if expected else 10.0
        at_risk_after = max(
            float(AT_RISK_AFTER_SECONDS),
            expected_s * float(AT_RISK_EXPECTED_MULTIPLIER),
        )
        is_at_risk = (
            age is not None
            and age >= at_risk_after
            and age < STARVE_AFTER_SECONDS
        )
        is_slow = (
            last_ms is not None
            and expected > 0
            and float(last_ms) >= float(expected) * SLOW_RATIO
        )
        if is_starved:
            state = STATE_STARVED
            reason = f"no_progress_{int(age)}s"
        elif is_at_risk:
            state = STATE_AT_RISK
            reason = f"cadence_miss_{int(age)}s"
        elif is_slow:
            state = STATE_SLOW
            reason = f"tick_{last_ms}ms_gt_{expected}ms"
        elif age is not None and age < SLEEP_AFTER_TICK_SECONDS:
            state = STATE_SLEEPING
            reason = "between_ticks"
        else:
            state = STATE_READY
            reason = "eligible"
    else:
        state = STATE_PAUSED
        reason = status or "unknown"

    return {
        "id": wid,
        "type": wtype,
        "status": status,
        "ops_state": state,
        "wait_reason": reason or wait_reason,
        "service_class": meta.get("service_class") or ops.get("service_class"),
        "owner": owner,
        "last_tick_ms": last_ms,
        "avg_tick_ms": avg_ms,
        "max_tick_ms": max_ms,
        "expected_tick_ms": expected,
        "starvation_age_seconds": round(age, 1) if age is not None else None,
        "mission_id": mission_id,
    }


def summarize_workers(
    workers: list[Any],
    *,
    now: datetime | None = None,
    inflight_mission_ids: set[str] | frozenset[str] | None = None,
    holding_reservation_ids: set[str] | frozenset[str] | None = None,
    notable_limit: int = 12,
    hide_types: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Aggregate Ops breakdown + notable starved/slow/waiting rows.

    ``hide_types`` (ARMF A2) excludes worker types from counts/notable but
    reports ``filtered_out`` so inventory honesty is preserved.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    holding = holding_reservation_ids or frozenset()
    hide = hide_types or frozenset()
    counts = empty_counts()
    classified: list[dict[str, Any]] = []
    filtered_out = 0
    for w in workers:
        wid = getattr(w, "id", None) or (w.get("id") if isinstance(w, dict) else None)
        row = classify_worker(
            w,
            now=now,
            inflight_mission_ids=inflight_mission_ids,
            holding_reservation=bool(wid and str(wid) in holding),
        )
        wtype = str(row.get("type") or "")
        if wtype in hide:
            filtered_out += 1
            continue
        counts[row["ops_state"]] = counts.get(row["ops_state"], 0) + 1
        classified.append(row)

    notable_states = {
        STATE_STARVED,
        STATE_AT_RISK,
        STATE_SLOW,
        STATE_WAITING_HOST,
        STATE_WAITING_DEPENDENCY,
        STATE_HOLDING_RESERVATION,
        STATE_RUNNING_TICK,
    }
    notable = [r for r in classified if r["ops_state"] in notable_states]
    # Prefer starved/at_risk/slow first
    order = {
        STATE_STARVED: 0,
        STATE_AT_RISK: 1,
        STATE_SLOW: 2,
        STATE_WAITING_HOST: 3,
        STATE_WAITING_DEPENDENCY: 4,
        STATE_HOLDING_RESERVATION: 5,
        STATE_RUNNING_TICK: 6,
    }
    notable.sort(key=lambda r: (order.get(r["ops_state"], 9), -(r.get("starvation_age_seconds") or 0)))

    by_program: dict[str, dict[str, Any]] = {}
    for row in classified:
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        prog = str(owner.get("program") or "unassigned")
        bucket = by_program.setdefault(
            prog,
            {"program": prog, "counts": empty_counts(), "notable": []},
        )
        st = row["ops_state"]
        bucket["counts"][st] = bucket["counts"].get(st, 0) + 1
        if st in notable_states:
            bucket["notable"].append(row)
    for bucket in by_program.values():
        bucket["notable"].sort(
            key=lambda r: (order.get(r["ops_state"], 9), -(r.get("starvation_age_seconds") or 0))
        )
        bucket["notable"] = bucket["notable"][: max(0, notable_limit)]

    active = sum(
        counts[s]
        for s in OPS_STATES
        if s != STATE_COMPLETED
    )
    return {
        "counts": counts,
        "active": active,
        "inventory_running": sum(
            1
            for w in workers
            if (getattr(w, "status", None) or (w.get("status") if isinstance(w, dict) else None))
            in ("running", "recovering")
        ),
        "notable": notable[: max(0, notable_limit)],
        "by_program": by_program,
        "filtered_out": filtered_out,
        "rows": classified,
    }


def update_timing_ops(
    existing_ops: dict[str, Any] | None,
    *,
    duration_ms: float,
    expected_ms: int | None = None,
    clear_wait: bool = True,
) -> dict[str, Any]:
    """Merge tick timing into the worker metadata ``ops`` object."""
    ops = dict(existing_ops or {})
    duration_ms = max(0.0, float(duration_ms))
    prev_count = int(ops.get("tick_count") or 0)
    prev_avg = float(ops.get("avg_tick_ms") or duration_ms)
    new_count = prev_count + 1
    avg = ((prev_avg * prev_count) + duration_ms) / new_count if prev_count else duration_ms
    prev_max = float(ops.get("max_tick_ms") or 0)
    ops["last_tick_ms"] = round(duration_ms, 1)
    ops["avg_tick_ms"] = round(avg, 1)
    ops["max_tick_ms"] = round(max(prev_max, duration_ms), 1)
    ops["tick_count"] = new_count
    if expected_ms is not None:
        ops["expected_tick_ms"] = int(expected_ms)
    if clear_wait:
        ops.pop("wait_reason", None)
        ops.pop("wait_since", None)
    return ops


def update_wait_ops(
    existing_ops: dict[str, Any] | None,
    *,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(now) or datetime.now(timezone.utc)
    ops = dict(existing_ops or {})
    ops["wait_reason"] = reason
    ops["wait_since"] = now.isoformat()
    return ops
