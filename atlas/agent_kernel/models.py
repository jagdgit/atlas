"""Normalized work records for the Agent Kernel.

Operational state only. Experiences are written through Experience OS when it
is wired; this module does not open a second experience database.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

VERSION = "a0.agent_kernel.v1"

STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUS_CAPABILITY_GAP = "CAPABILITY_GAP"
STATUS_WAITING = "WAITING_FOR_EVENT"
STATUS_DEFERRED = "DEFERRED"
STATUS_RETRY = "RETRY_SCHEDULED"
STATUS_FAILED = "FAILED"
STATUS_ABANDONED = "ABANDONED"
STATUS_PLANNING_FAILED = "PLANNING_FAILED"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_ACTIVE = "ACTIVE"

TERMINAL_OR_WAITING = frozenset(
    {
        STATUS_SUCCESS,
        STATUS_PARTIAL,
        STATUS_BLOCKED,
        STATUS_CAPABILITY_GAP,
        STATUS_WAITING,
        STATUS_DEFERRED,
        STATUS_RETRY,
        STATUS_FAILED,
        STATUS_ABANDONED,
        STATUS_PLANNING_FAILED,
        STATUS_UNVERIFIED,
    }
)

NON_SUCCESS = TERMINAL_OR_WAITING - {STATUS_SUCCESS}

PRIORITY_RANK = {"P0": 400, "P1": 300, "P2": 200, "P3": 100}

# Fields required on every non-success record so nothing sits unexplained.
DIAGNOSTIC_FIELDS = (
    "reason",
    "attempt_count",
    "attempted_capabilities",
    "last_error",
    "missing_requirement",
    "next_action",
    "next_retry_at",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def fingerprint(
    *,
    symbol: str,
    objective: str,
    required: list[str],
    domain: str,
) -> str:
    raw = "|".join(
        [
            (domain or "").strip().lower(),
            (symbol or "").strip().upper(),
            " ".join((objective or "").split()).lower(),
            ",".join(sorted(str(r) for r in required)),
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def empty_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "current_goal": None,
        "current_work": None,
        "tasks": {},
        "capability_gaps": [],
        "recent_failures": [],
        "recent_successes": [],
        "open_questions": [],
        "active_hypotheses": [],
        "pending_verifications": [],
        "next_actions": [],
        "episodes": [],
        "experiences": [],
        "failure_memory": {},
        "external_searches": [],
        "updated_at": None,
    }


def lineage(episode_id: str, work_id: str, decision_id: str | None = None) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "work_id": work_id,
        "decision_id": decision_id,
        "cognitive_result_id": None,
        "prediction_id": None,
        "experience_id": None,
        "learning_record_id": None,
        "lesson_id": None,
    }


def blank_diagnostics() -> dict[str, Any]:
    return {
        "reason": "",
        "attempt_count": 0,
        "attempted_capabilities": [],
        "last_error": None,
        "missing_requirement": None,
        "next_action": "execute_on_next_tick",
        "next_retry_at": None,
        "retry_policy": "on_tick",
    }
