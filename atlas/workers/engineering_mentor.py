"""EngineeringMentorWorker — Engineering Intelligence (OI-MP4).

Periodically synthesizes engineering Experiences into a mentor Lesson written back
to Experience OS. Soft-bias (default on) teaches future ``advice_for`` recall (OI-MP5).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.engineering.mentor import synthesize_engineering_lesson
from atlas.workers.base import PersistentWorker, TickContext, TickResult


def _experience_id_from_write(result: Any) -> str | None:
    """Pull the new experience id from remember_experience / journal result."""
    if not isinstance(result, dict):
        return None
    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    for key in ("ref_id", "id"):
        val = event.get(key) if event else None
        if val:
            return str(val)
    exp = result.get("experience")
    if isinstance(exp, dict) and exp.get("id"):
        return str(exp["id"])
    if result.get("ref_id"):
        return str(result["ref_id"])
    return None


class EngineeringMentorWorker(PersistentWorker):
    type = "engineering_mentor"
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
        self._logger = logger or logging.getLogger("atlas.workers.engineering_mentor")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        focus = str(cfg.get("focus") or "engineering").strip() or "engineering"
        force = bool(cfg.get("force"))
        force_topic = str(cfg.get("force_topic") or "").strip() or None
        lookback = max(5, int(cfg.get("lookback") or 40))

        seed = list(cfg.get("seed_experiences") or [])
        experiences: list[dict[str, Any]] = [e for e in seed if isinstance(e, dict)]
        if self._learning is not None and not cfg.get("seed_only"):
            try:
                listed = self._learning.list_experiences(limit=lookback) or []
                experiences = list(listed) + experiences
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("list_experiences failed: %s", exc)

        lesson = synthesize_engineering_lesson(
            experiences, focus=focus, force_topic=force_topic
        )
        if lesson is None:
            return TickResult(
                state=state,
                note=(
                    "mentor idle: no engineering Experiences yet — learn a repo "
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
        experience_id: str | None = None
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
                        domain="engineering",
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
                    experience_id = _experience_id_from_write(out.get("result"))
                elif self._learning is not None:
                    payload = lesson.experience_payload()
                    result = self._learning.remember_experience(**payload)
                    wrote = True
                    experience_id = _experience_id_from_write(result)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("remember_experience failed: %s", exc)
                return TickResult(
                    state=state,
                    note=f"mentor write failed: {exc}",
                )

        if (
            wrote
            and experience_id
            and cfg.get("enable_soft_bias", True)
            and self._learning is not None
            and hasattr(self._learning, "enable_bias")
        ):
            try:
                self._learning.enable_bias(str(experience_id), enabled=True)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("enable_bias skipped: %s", exc)

        state["last_lesson_fp"] = fingerprint
        state["last_lesson_title"] = lesson.title
        state["lessons_written"] = int(state.get("lessons_written") or 0) + (1 if wrote else 0)

        if self._events is not None:
            try:
                self._events.emit(
                    "EngineeringMentorLesson",
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
