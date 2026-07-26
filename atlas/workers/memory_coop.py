"""IR-RO11 cooperative memory helpers for PersistentWorkers (IRA.21 / archive).

Workers call :func:`gate_memory` between bounded units of work. On budget
breach they raise :class:`MemoryBudgetSignal`; callers checkpoint and return
``memory_action`` so WorkerManager can yield or pause.
"""

from __future__ import annotations

import gc
from typing import Any


class MemoryBudgetSignal(Exception):
    """Cooperative IR-RO11 yield/pause — not a worker failure."""

    def __init__(self, verdict: Any) -> None:
        self.verdict = verdict
        super().__init__(getattr(verdict, "reason", "memory_budget") or "memory_budget")


def gate_memory(ctx: Any, *, force: bool = False) -> None:
    """Stop the tick before RSS grows into OOM territory."""
    check = getattr(ctx, "check_memory", None)
    if not callable(check):
        return
    try:
        verdict = check(force=force)
    except TypeError:
        try:
            verdict = check()
        except Exception:  # noqa: BLE001
            return
    except Exception:  # noqa: BLE001
        return
    if verdict is None or getattr(verdict, "ok", True):
        return
    gc.collect()
    try:
        verdict2 = check(force=True)
    except TypeError:
        try:
            verdict2 = check()
        except Exception:  # noqa: BLE001
            verdict2 = verdict
    except Exception:  # noqa: BLE001
        verdict2 = verdict
    if getattr(verdict2, "ok", False):
        return
    raise MemoryBudgetSignal(verdict2 or verdict)


def apply_memory_pause_state(
    state: dict[str, Any],
    signal: MemoryBudgetSignal,
    *,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp cooperative pause fields onto checkpoint state."""
    verdict = signal.verdict
    action = getattr(verdict, "action", "yield_tick") or "yield_tick"
    reason = getattr(verdict, "reason", "") or "memory_budget"
    state["memory_action"] = action
    state["memory_reason"] = reason
    state["phase"] = "memory_budget_pause"
    state["phase_detail"] = reason
    if hasattr(verdict, "as_dict"):
        try:
            state["memory_verdict"] = verdict.as_dict()
        except Exception:  # noqa: BLE001
            pass
    if extras:
        state.update(extras)
    return state
