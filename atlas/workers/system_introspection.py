"""SystemIntrospectionWorker — periodic self-analysis journal (OI-F3).

Aggregates D.10 / P15 / coverage / arbiter / policy into one Experience-friendly
report. Fingerprints the narrative so unchanged ticks stay quiet.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class SystemIntrospectionWorker(PersistentWorker):
    type = "system_introspection"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        introspection: Any,
        experience_os: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._introspection = introspection
        self._experience_os = experience_os
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.system_introspection")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        state["ticks"] = int(state.get("ticks", 0)) + 1

        force = bool(cfg.get("force"))
        report = self._introspection.report(limit=int(cfg.get("limit") or 200))
        narrative = str(report.get("narrative") or "")
        fp = hashlib.sha256(narrative.encode()).hexdigest()[:16]
        if fp == state.get("last_report_fp") and not force:
            return TickResult(
                state=state,
                note="introspection unchanged — same System Introspection snapshot",
            )

        state["last_report_fp"] = fp
        sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
        unc = sections.get("uncertainty") or {}
        gaps = sections.get("gaps") or {}
        improve = sections.get("improve_next") or {}

        if self._experience_os is not None and bool(cfg.get("journal_experience", True)):
            try:
                self._experience_os.journal(
                    title="System Introspection snapshot",
                    observation=narrative[:2000],
                    reasoning="Periodic self-analysis across knowledge, readers, missions, policies, gaps.",
                    decision="Surface open improvement and capability gaps to the operator",
                    outcome=(
                        f"uncertain={unc.get('uncertain_total', 0)} "
                        f"decision_gaps={gaps.get('decision_gap_count', 0)} "
                        f"open_recs={improve.get('open_recommendations', 0)}"
                    ),
                    reflection=(
                        "Atlas should prioritize contested knowledge, failing readers, "
                        "and catalog/decision capability gaps before adding features."
                    ),
                    lesson=(
                        "Use System Introspection before broad self-improvement proposals; "
                        "treat capability gaps as operator recommendations (P15)."
                    ),
                    domain="engineering",
                    tags=[
                        "system_introspection",
                        "maintenance",
                        "experience_journal",
                    ],
                    metadata={
                        "system_introspection": True,
                        "version": report.get("version"),
                        "mission_id": ctx.mission_id,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("introspection journal failed: %s", exc)

        if self._events is not None:
            try:
                self._events.emit(
                    "SystemIntrospectionReport",
                    {
                        "mission_id": ctx.mission_id,
                        "version": report.get("version"),
                        "uncertain_total": unc.get("uncertain_total"),
                        "decision_gaps": gaps.get("decision_gap_count"),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        note = (
            f"introspection: findings={(sections.get('knowledge') or {}).get('findings_scanned', 0)} "
            f"uncertain={unc.get('uncertain_total', 0)} "
            f"gaps={gaps.get('decision_gap_count', 0)} "
            f"recs={improve.get('open_recommendations', 0)}"
        )
        return TickResult(state=state, note=note)
