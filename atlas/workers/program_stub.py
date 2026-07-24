"""ProgramStubWorker — placeholder tick for planned Program members (MI.2).

Architecture is ready; capability is not. Each tick journals a clear stub note so
operators see the mission is alive and waiting — never silent, never broker login.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class ProgramStubWorker(PersistentWorker):
    type = "program_stub"
    VERSION = 1
    journal_ticks = True

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("atlas.workers.program_stub")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        role = str(cfg.get("role") or "Program member").strip()
        roadmap = str(cfg.get("roadmap") or "planned").strip()
        note = (
            f"stub: {role} waiting ({roadmap}) — template live, capability not enabled yet"
        )
        if ticks == 1:
            self._logger.info("program stub started mission=%s role=%s", ctx.mission_id, role)
        return TickResult(state=state, note=note)
