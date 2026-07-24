"""LearningGovernanceWorker — periodic Layer 2 governance journal (OI-MP3).

Default daily cadence. Journals the Daily Learning Governance Report narrative
onto the mission so operators see Layer 2 without asking.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class LearningGovernanceWorker(PersistentWorker):
    type = "learning_governance"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        governance: Any,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._governance = governance
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.learning_governance")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        force = bool(cfg.get("force"))
        report = self._governance.daily(limit=int(cfg.get("limit") or 200))
        narrative = str(report.get("narrative") or "")
        fp = hashlib.sha256(narrative.encode()).hexdigest()[:16]
        if fp == state.get("last_report_fp") and not force:
            return TickResult(
                state=state,
                note="governance unchanged — same Layer 2 snapshot",
            )

        state["last_report_fp"] = fp
        state["last_headline"] = report.get("headline")
        if self._events is not None:
            try:
                self._events.emit(
                    "LearningGovernanceReport",
                    {
                        "mission_id": ctx.mission_id,
                        "headline": report.get("headline"),
                        "version": report.get("version"),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        # Keep journal note compact; full report via API.
        head = report.get("headline") or {}
        note = (
            f"governance: concepts={head.get('new_concepts', 0)} "
            f"lessons={head.get('lessons_learned', 0)} "
            f"conflicts={head.get('knowledge_conflicts', 0)} "
            f"gaps={head.get('capability_gaps', 0)}"
        )
        return TickResult(state=state, note=note)
