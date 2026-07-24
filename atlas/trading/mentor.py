"""Investment Mentor — synthesize market lessons into Experience OS (MI.7 / MI15).

Platform Experience OS stays the store; this module is Market Program copy that
writes Observation→…→Lesson Experiences (OI-MP1) for Decision Simulation to recall.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MentorLesson:
    """One mentor synthesis ready for Experience OS + journal."""

    title: str
    observation: str
    decision_summary: str
    outcome_summary: str
    reflection: str
    lesson: str
    recommendations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_experience_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def experience_payload(self) -> dict[str, Any]:
        problem = (
            f"Observation: {self.observation}\n"
            f"Decision: {self.decision_summary}\n"
            f"Outcome: {self.outcome_summary}"
        )
        solution = f"Reflection: {self.reflection}"
        lessons = f"Lesson: {self.lesson}"
        if self.recommendations:
            lessons += "\nRecommendations: " + "; ".join(self.recommendations)
        return {
            "title": self.title,
            "problem": problem,
            "solution": solution,
            "lessons": lessons,
            "domain": "markets",
            "tags": list(self.tags),
            "recommendations": [
                {"title": r, "why": self.lesson} for r in self.recommendations
            ],
            "source_experience_ids": list(self.source_experience_ids),
        }


def synthesize_mentor_lesson(
    experiences: list[dict[str, Any]] | None = None,
    *,
    focus: str = "markets",
    force_topic: str | None = None,
) -> MentorLesson | None:
    """Build a weekly-style lesson from recent market Experiences.

    Returns ``None`` when there is nothing useful to teach (honest idle).
    """
    rows = [e for e in (experiences or []) if isinstance(e, dict)]
    # Prefer markets / paper_trading tagged rows
    marketish: list[dict[str, Any]] = []
    for e in rows:
        tags = {str(t).lower() for t in (e.get("tags") or [])}
        domain = str(e.get("domain") or "").lower()
        title = str(e.get("title") or "").lower()
        if (
            "markets" in tags
            or "paper_trading" in tags
            or "investment_mentor" in tags
            or domain == "markets"
            or "paper trade" in title
            or "mentor" in title
        ):
            marketish.append(e)
    if not marketish and not force_topic:
        return None
    if not marketish and force_topic:
        return MentorLesson(
            title=f"Investment mentor: {force_topic}",
            observation=f"Operator focus: {force_topic}",
            decision_summary="No prior market Experiences yet — seed lesson only.",
            outcome_summary="n/a",
            reflection=(
                "Without closed trades or journaled Outcomes, recommendations stay "
                "provisional."
            ),
            lesson=(
                "Run Decision Simulation with instruments so sells write Experience "
                "journal rows; Mentor will synthesize those next tick."
            ),
            recommendations=[
                "Register sample market_data and start decision_simulation",
                "Keep broker_profile set when comparing fee impact (MI.6)",
            ],
            tags=["markets", "investment_mentor", "seed", focus.lower()],
        )

    profits = 0
    losses = 0
    flats = 0
    symbols: list[str] = []
    lesson_bits: list[str] = []
    ids: list[str] = []
    for e in marketish[:20]:
        if e.get("id"):
            ids.append(str(e["id"]))
        tags = {str(t).lower() for t in (e.get("tags") or [])}
        if "profit" in tags:
            profits += 1
        elif "loss" in tags:
            losses += 1
        elif "flat" in tags:
            flats += 1
        for t in tags:
            if t not in {
                "paper_trading",
                "experience_journal",
                "profit",
                "loss",
                "flat",
                "markets",
                "investment_mentor",
            }:
                symbols.append(t)
        bit = (e.get("lessons") or e.get("solution") or "").strip()
        if bit:
            lesson_bits.append(bit[:200])

    n = max(1, profits + losses + flats)
    win_rate = profits / n if (profits + losses + flats) else 0.0
    top_syms = sorted({s for s in symbols})[:8]
    observation = (
        f"Reviewed {len(marketish)} market Experience(s); "
        f"closed outcomes profit={profits} loss={losses} flat={flats}"
        + (f"; symbols={', '.join(top_syms)}" if top_syms else "")
    )
    if losses > profits:
        reflection = (
            "Recent closed trades skew to losses — entries may chase signals "
            "without catalyst checks."
        )
        lesson = (
            "Before similar buys, re-check risk events and position size; "
            "do not treat a single indicator crossover as sufficient."
        )
        recs = [
            "Prefer hold when mentor_advice cites recent losses on the symbol",
            "Lower trade_fraction until expectancy recovers",
            "Use Event Research on high-score MarketInterestingMove before adding size",
        ]
    elif profits > losses:
        reflection = (
            "Recent closed trades show positive expectancy under current constraints."
        )
        lesson = (
            "Reinforce setups that worked; still size within max_exposure_pct and "
            "journal every exit (OI-MP1)."
        )
        recs = [
            "Keep journaling sells into Experience OS",
            "Avoid overfitting to one DEMO fixture path",
        ]
    else:
        reflection = "Outcomes are mixed or flat — signal-to-noise is low."
        lesson = (
            "Treat inconclusive periods as research time: verify news claims and "
            "company facts before changing strategy params."
        )
        recs = [
            "Run company_intelligence / news_intelligence on focus names",
            "Avoid raising trade_fraction on flat expectancy",
        ]

    if lesson_bits:
        reflection += " Prior lessons: " + " | ".join(lesson_bits[:3])

    topic = force_topic or (top_syms[0] if top_syms else focus)
    return MentorLesson(
        title=f"Investment mentor weekly: {topic} (win≈{win_rate:.0%})",
        observation=observation,
        decision_summary="Aggregate of Decision Simulation / paper_trading closes",
        outcome_summary=f"profit={profits} loss={losses} flat={flats}",
        reflection=reflection,
        lesson=lesson,
        recommendations=recs,
        tags=["markets", "investment_mentor", "weekly", focus.lower()],
        source_experience_ids=ids[:20],
    )
