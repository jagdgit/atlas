"""InvestmentMentorWorker — Market Intelligence M7 (MI.7).

Periodically synthesizes market Experiences into a mentor Lesson written back
to Experience OS (MI15). Decision Simulation recalls via ``advice_for`` (OI-MP5).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.trading.mentor import synthesize_mentor_lesson
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class InvestmentMentorWorker(PersistentWorker):
    type = "investment_mentor"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        learning: Any,
        experience_os: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._learning = learning
        self._experience_os = experience_os
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.investment_mentor")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        focus = str(cfg.get("focus") or "markets").strip() or "markets"
        force = bool(cfg.get("force"))
        force_topic = str(cfg.get("force_topic") or "").strip() or None
        lookback = max(5, int(cfg.get("lookback") or 40))

        # Hermetic seed experiences from config (tests / offline).
        seed = list(cfg.get("seed_experiences") or [])
        experiences: list[dict[str, Any]] = [e for e in seed if isinstance(e, dict)]
        if self._learning is not None and not cfg.get("seed_only"):
            try:
                listed = self._learning.list_experiences(limit=lookback) or []
                experiences = list(listed) + experiences
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("list_experiences failed: %s", exc)

        lesson = synthesize_mentor_lesson(
            experiences, focus=focus, force_topic=force_topic
        )
        if lesson is None:
            return TickResult(
                state=state,
                note=(
                    "mentor idle: no market Experiences yet — close sim trades "
                    "or set force_topic / seed_experiences"
                ),
            )

        fingerprint = hashlib.sha256(
            f"{lesson.title}|{lesson.lesson}|{lesson.outcome_summary}".encode()
        ).hexdigest()[:16]
        if fingerprint == state.get("last_lesson_fp") and not force:
            return TickResult(
                state=state,
                note=f"mentor unchanged[{focus}]: {lesson.title[:60]}",
            )

        wrote = False
        if not cfg.get("dry_run"):
            try:
                if self._experience_os is not None:
                    out = self._experience_os.journal(
                        title=lesson.title,
                        observation=lesson.observation,
                        decision=lesson.decision_summary,
                        outcome=lesson.outcome_summary,
                        reflection=lesson.reflection,
                        lesson=lesson.lesson,
                        domain="markets",
                        tags=list(lesson.tags),
                        recommendations=[
                            {"title": r, "why": lesson.lesson}
                            for r in lesson.recommendations
                        ],
                        metadata={
                            "source_experience_ids": list(lesson.source_experience_ids),
                        },
                    )
                    wrote = bool(out.get("ok"))
                    if not wrote:
                        return TickResult(
                            state=state,
                            note=f"mentor write failed: {out.get('error') or out}",
                        )
                elif self._learning is not None:
                    payload = lesson.experience_payload()
                    self._learning.remember_experience(**payload)
                    wrote = True
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("remember_experience failed: %s", exc)
                return TickResult(
                    state=state,
                    note=f"mentor write failed: {exc}",
                )

        state["last_lesson_fp"] = fingerprint
        state["last_lesson_title"] = lesson.title
        state["lessons_written"] = int(state.get("lessons_written") or 0) + (1 if wrote else 0)

        if self._events is not None:
            try:
                self._events.emit(
                    "InvestmentMentorLesson",
                    {
                        "mission_id": ctx.mission_id,
                        "title": lesson.title,
                        "lesson": lesson.lesson,
                        "recommendations": lesson.recommendations,
                        "wrote": wrote,
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        rec = "; ".join(lesson.recommendations[:2])
        return TickResult(
            state=state,
            note=(
                f"mentor[{focus}]: wrote={wrote} {lesson.title[:50]} | {rec}"
            ),
        )
