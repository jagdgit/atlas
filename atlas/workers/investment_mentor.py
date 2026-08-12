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


def _lesson_from_bre5_dict(payload: dict[str, Any]):
    """Adapt mentor_lesson_from_digest dict → MentorLesson."""
    from atlas.trading.mentor import MentorLesson

    return MentorLesson(
        title=str(payload.get("title") or "WSO revision digest"),
        observation=str(payload.get("observation") or ""),
        decision_summary=str(payload.get("decision_summary") or ""),
        outcome_summary=str(payload.get("outcome_summary") or ""),
        reflection=str(payload.get("reflection") or ""),
        lesson=str(payload.get("lesson") or ""),
        recommendations=[str(r) for r in (payload.get("recommendations") or []) if r],
        tags=[str(t) for t in (payload.get("tags") or []) if t],
        source_experience_ids=list(payload.get("source_experience_ids") or []),
    )


class InvestmentMentorWorker(PersistentWorker):
    type = "investment_mentor"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        learning: Any,
        experience_os: Any | None = None,
        events: Any | None = None,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._learning = learning
        self._experience_os = experience_os
        self._events = events
        self._data_dir = data_dir
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
        portfolio_key = str(cfg.get("portfolio_key") or "").strip() or None

        # BRE.5 — prefer global WSO revision digest (advice-only; A7)
        bre5_lesson = None
        advice_only = False
        if cfg.get("use_wso_revision_digest", True):
            try:
                from atlas.investment.global_mind import mentor_lesson_from_digest
                from atlas.investment.world_state import load_global_wso

                data_dir = str(cfg.get("data_dir") or self._data_dir or "")
                if not data_dir:
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = ""
                lab = str(
                    portfolio_key
                    or cfg.get("laboratory_id")
                    or "india_equity_learner"
                )
                if data_dir:
                    gw = load_global_wso(data_dir, lab)
                    payload = mentor_lesson_from_digest(gw)
                    if payload:
                        bre5_lesson = _lesson_from_bre5_dict(payload)
                        advice_only = True
            except Exception:  # noqa: BLE001
                self._logger.debug("BRE.5 mentor digest skipped", exc_info=True)

        # Hermetic seed experiences from config (tests / offline).
        seed = list(cfg.get("seed_experiences") or [])
        experiences: list[dict[str, Any]] = [e for e in seed if isinstance(e, dict)]
        if self._learning is not None and not cfg.get("seed_only") and bre5_lesson is None:
            try:
                listed = self._learning.list_experiences(limit=lookback) or []
                experiences = list(listed) + experiences
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("list_experiences failed: %s", exc)

        if portfolio_key and bre5_lesson is None:
            from atlas.investment.portfolios import filter_journals_for_portfolio

            experiences = filter_journals_for_portfolio(experiences, portfolio_key)

        lesson = bre5_lesson
        if lesson is None:
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
        experience_id: str | None = None
        if not cfg.get("dry_run"):
            try:
                if self._experience_os is not None:
                    tags = list(lesson.tags) + (
                        [f"portfolio:{portfolio_key}"] if portfolio_key else []
                    )
                    out = self._experience_os.journal(
                        title=lesson.title,
                        observation=lesson.observation,
                        decision=lesson.decision_summary,
                        outcome=lesson.outcome_summary,
                        reflection=lesson.reflection,
                        lesson=lesson.lesson,
                        domain="markets",
                        tags=tags,
                        recommendations=[
                            {"title": r, "why": lesson.lesson}
                            for r in lesson.recommendations
                        ],
                        metadata={
                            "source_experience_ids": list(lesson.source_experience_ids),
                            "advice_only": advice_only,
                            **({"portfolio_key": portfolio_key} if portfolio_key else {}),
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

        # OI-MP5 — soft-bias default for experience lessons; BRE.5 digest is advice-only (A7)
        enable_bias = bool(cfg.get("enable_soft_bias", True)) and not advice_only
        if (
            wrote
            and experience_id
            and enable_bias
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
        state["bre5_advice_only"] = advice_only

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
                        "advice_only": advice_only,
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        rec = "; ".join(lesson.recommendations[:2])
        return TickResult(
            state=state,
            note=(
                f"mentor[{focus}{'|bre5' if advice_only else ''}]: "
                f"wrote={wrote} {lesson.title[:50]} | {rec}"
            ),
        )
