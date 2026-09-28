"""OI-CU0 A1/A2/A3 — inference lanes, admit priority, durable LLM failure records."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.learning_objects import ist_today, record_learning_event

VERSION = "cu0.llm_lanes.v1"
_log = logging.getLogger("atlas.investment.llm_lanes")
_IST = ZoneInfo("Asia/Kolkata")

# Role / caller → CU.A lane
ROLE_TO_CU_LANE: dict[str, str] = {
    "chat": "chat",
    "planner": "chat",
    "summarizer": "background",
    "researcher": "research",
    "research": "research",
    "scientist": "research",
    "code": "background",
    "vision": "background",
    "embed": "background",
    "generate": "background",
    "market": "market",
    "background": "background",
}

CU_LANES = frozenset({"chat", "market", "research", "background"})

# Higher = more important. Do not raise Ollama concurrency to "fix" contention.
LANE_PRIORITY: dict[str, int] = {
    "chat": 100,
    "market": 90,
    "research": 40,
    "background": 10,
}

# May wait for a free slot. Research/background fail-fast when saturated (daytime).
PROTECTED_LANES = frozenset({"chat", "market"})
LOW_LANES = frozenset({"research", "background"})

# CU.C overnight window (IST) — low lanes may block among themselves here only.
OVERNIGHT_START = time(18, 30)
OVERNIGHT_END = time(7, 30)

# DP-LLM1 — during NSE RTH keep ≥1 slot free for chat/market when concurrency≥2.
RTH_RESERVED_FOR_PROTECTED = 1


class LLMLaneBusy(RuntimeError):
    """Raised when a non-protected lane cannot acquire without waiting."""

    def __init__(self, lane: str, detail: str = "") -> None:
        self.lane = str(lane)
        msg = detail or f"LLM lane busy — {self.lane} deferred (CU.A2, no concurrency bump)"
        super().__init__(msg)


def cu_lane_for_role(role: str | None) -> str:
    r = str(role or "chat").strip().lower()
    return ROLE_TO_CU_LANE.get(r, "background" if r not in CU_LANES else r)


def lane_priority(lane_or_role: str | None) -> int:
    return int(LANE_PRIORITY.get(cu_lane_for_role(lane_or_role), 10))


def in_overnight_window(now: datetime | None = None) -> bool:
    """True during 18:30–07:30 IST (CU.C densify window)."""
    dt = now
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    else:
        dt = dt.astimezone(_IST)
    t = dt.timetz().replace(tzinfo=None)
    return t >= OVERNIGHT_START or t < OVERNIGHT_END


def in_nse_rth(now: datetime | None = None) -> bool:
    """True during NSE cash regular hours (live labs must keep working)."""
    try:
        from atlas.trading.sessions import is_session_open

        return bool(is_session_open("nse_equity", now=now))
    except Exception:  # noqa: BLE001
        return False


def rth_reserved_slots(limit: int, *, now: datetime | None = None) -> int:
    """Slots held for chat/market during RTH when concurrency ≥ 2."""
    lim = max(1, int(limit))
    if lim < 2 or not in_nse_rth(now=now):
        return 0
    return min(RTH_RESERVED_FOR_PROTECTED, lim - 1)


def lane_acquire_blocking(lane_or_role: str | None, *, now: datetime | None = None) -> bool:
    """A2 — True if this lane may wait for capacity; False = try/fail immediately.

    Only protected chat/market wait. Research/background always fail-fast when
    saturated (including overnight) so they never queue ahead of operator chat.
    Overnight window gates *whether densify work is scheduled* (CU.C), not
    whether a low lane may block the semaphore.
    """
    del now  # reserved for callers / future schedule hints
    return cu_lane_for_role(lane_or_role) in PROTECTED_LANES


def admit_llm_lane(
    lane_or_role: str | None,
    *,
    in_use: int,
    limit: int,
    now: datetime | None = None,
    low_lane_in_use: int | None = None,
) -> dict[str, Any]:
    """Pure admit decision for tests / preflight (does not raise concurrency)."""
    cu = cu_lane_for_role(lane_or_role)
    lim = max(1, int(limit))
    used = max(0, int(in_use))
    free = max(0, lim - used)
    blocking = lane_acquire_blocking(cu, now=now)
    reserved = rth_reserved_slots(lim, now=now)
    low_used = (
        max(0, int(low_lane_in_use))
        if low_lane_in_use is not None
        else 0
    )

    # DP-LLM1 — during RTH, low lanes cannot eat the reserved protected slot(s).
    if cu in LOW_LANES and reserved > 0:
        low_cap = max(0, lim - reserved)
        if low_used >= low_cap or free <= reserved:
            return {
                "allowed": False,
                "lane": cu,
                "priority": lane_priority(cu),
                "blocking": False,
                "reason": "rth_reserve_for_live",
                "rth_reserved": reserved,
            }

    if free > 0:
        return {
            "allowed": True,
            "lane": cu,
            "priority": lane_priority(cu),
            "blocking": blocking,
            "reason": "capacity_available",
            "rth_reserved": reserved,
        }
    if blocking:
        return {
            "allowed": True,
            "lane": cu,
            "priority": lane_priority(cu),
            "blocking": True,
            "reason": "protected_may_wait",
            "rth_reserved": reserved,
        }
    return {
        "allowed": False,
        "lane": cu,
        "priority": lane_priority(cu),
        "blocking": False,
        "reason": "saturated_defer_low_lane",
        "rth_reserved": reserved,
    }


def record_llm_lane_failure(
    data_dir: str | Path | None,
    *,
    lane: str,
    reason: str,
    detail: str | None = None,
    laboratory_id: str = "india_equity_learner",
    source: str = "chat",
) -> dict[str, Any]:
    """Persist llm_failure so evening 'LLM failures' matches reality (incl. chat)."""
    lab = laboratory_id or "india_equity_learner"
    cu = cu_lane_for_role(lane) if lane not in CU_LANES else str(lane)
    event = {
        "version": VERSION,
        "kind": "LEARNING_EVENT",
        "event_kind": "llm_failure",
        "laboratory_id": lab,
        "as_of_ist": ist_today(),
        "symbol": None,
        "trigger": "llm_unavailable",
        "strategy_tag": "llm_unavailable",
        "llm_lane": cu,
        "source": source,
        "reason": str(reason or "unavailable")[:200],
        "detail": (detail or "")[:500],
        "honesty": (
            "Lane-aware LLM failure — chat timeouts count here; "
            "not the same as belief unchanged."
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        return record_learning_event(data_dir, event)
    except Exception:  # noqa: BLE001
        _log.debug("llm_lane failure record skipped", exc_info=True)
        return {"ok": False, "reason": "persist_failed"}
