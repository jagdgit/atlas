"""Persistent Worker base (Phase A · PHASE_A_PLAN §A.4, A-new1).

A Persistent Worker runs as a **short-task + checkpoint** loop, never a long-lived thread that
holds state in memory: each tick is one bounded unit of work driven by a schedule (0023). The
``WorkerManager`` handles all durability (checkpoint load/save, crash backoff, version upgrade,
input draining); a concrete worker only implements :meth:`do_tick`, a pure function of its
``TickContext`` returning a ``TickResult`` (the next checkpoint state + optional done/note).

This keeps workers trivial and testable, and means every worker automatically gets
kill-9/reboot resume, live operator input, and explainable journaling for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TickContext:
    """Everything a worker needs for one tick — assembled durably by the manager."""

    worker_id: str
    mission_id: str
    config: dict[str, Any]                 # active, validated config document (or {})
    config_version: int | None             # which config version `config` came from
    state: dict[str, Any]                  # last checkpoint state ({} on first tick)
    inputs: list[dict[str, Any]] = field(default_factory=list)  # drained operator inputs


@dataclass(frozen=True)
class TickResult:
    """The outcome of one tick: the state to checkpoint + control signals."""

    state: dict[str, Any]
    done: bool = False                      # mission-completing: manager stops the worker
    note: str = ""                          # short human reason for the journal (P9)


class PersistentWorker:
    """Base class for all persistent workers.

    Subclasses set ``type`` + ``VERSION`` and implement :meth:`do_tick`. ``VERSION`` is an
    integer stamped onto the worker row + checkpoints (B8): bump it when the tick's behaviour
    or state shape changes so a resumed worker records "resumed using worker vN".
    """

    type: str = "base"
    VERSION: int = 1

    def do_tick(self, ctx: TickContext) -> TickResult:  # pragma: no cover - abstract
        raise NotImplementedError
