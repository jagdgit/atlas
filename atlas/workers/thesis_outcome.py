"""ThesisOutcomeWorker — IRA.14/15 timed checkpoints + mentor writeback.

IRA.21: cooperative IR-RO11 memory gates between symbol checkpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult
from atlas.workers.memory_coop import (
    MemoryBudgetSignal,
    apply_memory_pause_state,
    gate_memory,
)


class ThesisOutcomeWorker(PersistentWorker):
    type = "thesis_outcome"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        research: Any | None = None,
        experience_os: Any | None = None,
        mailer: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._research = research
        self._experience = experience_os
        self._mailer = mailer
        self._logger = logger or logging.getLogger("atlas.workers.thesis_outcome")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        program_id = str(cfg.get("program_id") or "market_intelligence")
        portfolio_key = str(cfg.get("portfolio_key") or "").strip() or None
        max_symbols = max(1, min(int(cfg.get("max_symbols") or 10), 20))
        hours = float(cfg.get("checkpoint_hours") or 24.0)

        if self._research is None:
            return TickResult(state=state, note="idle: investment_research not wired")

        try:
            gate_memory(ctx)
            evaluated = self._research.evaluate_outcomes(
                program_id=program_id,
                max_symbols=max_symbols,
                checkpoint_hours=hours,
                before_each=lambda _sym: gate_memory(ctx),
            )
        except MemoryBudgetSignal as signal:
            apply_memory_pause_state(state, signal)
            return TickResult(
                state=state,
                note=f"IR-RO11 {state.get('memory_action')}: {state.get('memory_reason')}",
            )

        written: dict[str, Any] = {"written": 0}
        if bool(cfg.get("mentor_writeback", True)) and self._experience is not None:
            try:
                gate_memory(ctx)
                written = self._research.writeback_lessons_to_mentor(
                    experience_os=self._experience,
                    program_id=program_id,
                    limit=int(cfg.get("mentor_limit") or 8),
                    portfolio_key=portfolio_key,
                )
            except MemoryBudgetSignal as signal:
                apply_memory_pause_state(
                    state,
                    signal,
                    extras={
                        "last_evaluated": evaluated.get("count") or 0,
                        "last_mentor_written": 0,
                    },
                )
                return TickResult(
                    state=state,
                    note=(
                        f"IR-RO11 {state.get('memory_action')}: {state.get('memory_reason')} "
                        f"(checkpoints={evaluated.get('count') or 0})"
                    ).strip(),
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("mentor writeback failed: %s", exc)
                written = {"written": 0, "reason": str(exc)}

        weekly = None
        if bool(cfg.get("send_weekly", False)) and self._mailer is not None:
            try:
                weekly = self._mailer.send_weekly_research(
                    program_id=program_id,
                    force=bool(cfg.get("force_weekly")),
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("weekly research email skipped: %s", exc)

        state["last_evaluated"] = evaluated.get("count") or 0
        state["last_mentor_written"] = written.get("written") or 0
        state.pop("memory_action", None)
        state.pop("memory_reason", None)
        note = (
            f"checkpoints={evaluated.get('count') or 0}; "
            f"mentor_lessons={written.get('written') or 0}"
        )
        if weekly and weekly.get("sent"):
            note += "; weekly_email=sent"
        return TickResult(state=state, note=note)
