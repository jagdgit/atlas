"""Engineering Mentor — synthesize repo/architecture lessons into Experience OS (OI-MP4).

Platform Experience OS stays the store; this module is Engineering Program copy that
writes Observation→…→Lesson Experiences for future repository / design decisions to recall
via ``advice_for`` (same soft-bias path as Investment Mentor / OI-MP5).
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
            "domain": "engineering",
            "tags": list(self.tags),
            "recommendations": [
                {"title": r, "why": self.lesson} for r in self.recommendations
            ],
            "source_experience_ids": list(self.source_experience_ids),
        }


_ENGINEERING_TAGS = frozenset({
    "engineering",
    "repository_learning",
    "architecture",
    "engineering_mentor",
    "design_review",
    "tech_debt",
    "refactor",
})

_DEBT_HINTS = (
    "debt",
    "todo",
    "hack",
    "workaround",
    "fragile",
    "legacy",
    "smell",
    "duplicat",
)
_SUCCESS_HINTS = (
    "refactor",
    "simplif",
    "test",
    "coverage",
    "modular",
    "stable",
    "clean",
    "pattern",
)
_MISTAKE_HINTS = (
    "regress",
    "broke",
    "bug",
    "incident",
    "revert",
    "outage",
    "mistake",
    "wrong",
)


def _is_engineering(e: dict[str, Any]) -> bool:
    tags = {str(t).lower() for t in (e.get("tags") or [])}
    domain = str(e.get("domain") or "").lower()
    title = str(e.get("title") or "").lower()
    if tags & _ENGINEERING_TAGS:
        return True
    if domain in {"engineering", "architecture", "code"}:
        return True
    if any(k in title for k in ("repo", "architecture", "refactor", "engineering")):
        return True
    return False


def _blob(e: dict[str, Any]) -> str:
    parts = [
        str(e.get("title") or ""),
        str(e.get("lessons") or ""),
        str(e.get("solution") or ""),
        str(e.get("problem") or ""),
        str(e.get("reflection") or ""),
        " ".join(str(t) for t in (e.get("tags") or [])),
    ]
    return " ".join(parts).lower()


def synthesize_engineering_lesson(
    experiences: list[dict[str, Any]] | None = None,
    *,
    focus: str = "engineering",
    force_topic: str | None = None,
) -> MentorLesson | None:
    """Build a weekly-style engineering judgment lesson from recent Experiences.

    Returns ``None`` when there is nothing useful to teach (honest idle).
    """
    rows = [e for e in (experiences or []) if isinstance(e, dict)]
    eng = [e for e in rows if _is_engineering(e)]
    if not eng and not force_topic:
        return None
    if not eng and force_topic:
        return MentorLesson(
            title=f"Engineering mentor: {force_topic}",
            observation=f"Operator focus: {force_topic}",
            decision_summary="No prior engineering Experiences yet — seed lesson only.",
            outcome_summary="n/a",
            reflection=(
                "Without repository_learning journals or design-review Outcomes, "
                "recommendations stay provisional."
            ),
            lesson=(
                "Ingest a repo via repository_learning so language/framework/pattern "
                "Experiences accumulate; Mentor will synthesize those next tick."
            ),
            recommendations=[
                "Start repository_learning on a primary codebase",
                "Journal architectural decisions (why, not only what) after refactors",
            ],
            tags=["engineering", "engineering_mentor", "seed", focus.lower()],
        )

    debt = 0
    success = 0
    mistakes = 0
    topics: list[str] = []
    lesson_bits: list[str] = []
    ids: list[str] = []
    for e in eng[:25]:
        if e.get("id"):
            ids.append(str(e["id"]))
        blob = _blob(e)
        if any(h in blob for h in _DEBT_HINTS):
            debt += 1
        if any(h in blob for h in _SUCCESS_HINTS):
            success += 1
        if any(h in blob for h in _MISTAKE_HINTS):
            mistakes += 1
        for t in e.get("tags") or []:
            tl = str(t).lower()
            if tl not in _ENGINEERING_TAGS and tl not in {
                "experience_journal",
                "weekly",
                "seed",
            }:
                topics.append(tl)
        bit = (e.get("lessons") or e.get("solution") or "").strip()
        if bit:
            lesson_bits.append(bit[:200])

    top_topics = sorted({t for t in topics})[:8]
    observation = (
        f"Reviewed {len(eng)} engineering Experience(s); "
        f"debt_signals={debt} success_signals={success} mistake_signals={mistakes}"
        + (f"; topics={', '.join(top_topics)}" if top_topics else "")
    )

    if mistakes >= max(2, success):
        reflection = (
            "Recent engineering journal entries skew toward regressions / reverts — "
            "changes may ship without enough architectural checks."
        )
        lesson = (
            "Before similar refactors, require a short design note (why + blast radius) "
            "and a regression test for the failure mode that already happened."
        )
        recs = [
            "Prefer smaller diffs when mentor_advice cites repeating mistake signals",
            "Add a focused regression test before retrying the same change shape",
            "Re-learn the repo after large moves so pattern Experiences stay current",
        ]
    elif debt > success:
        reflection = (
            "Technical-debt language dominates recent Experiences — Atlas is noticing "
            "accumulated shortcuts more than successful cleanups."
        )
        lesson = (
            "Schedule deliberate debt pay-down next to feature work; do not add "
            "parallel hacks in the same modules flagged by Mentor."
        )
        recs = [
            "Pick one debt hotspot and journal Outcome after a cleanup",
            "Avoid new workarounds in modules already tagged tech_debt",
            "Keep repository_learning ticking so debt signals stay fresh",
        ]
    elif success > debt:
        reflection = (
            "Recent Experiences show successful patterns (tests, refactors, modularity)."
        )
        lesson = (
            "Reinforce setups that worked; still record *why* architectural choices "
            "succeeded so judgment survives the next rewrite."
        )
        recs = [
            "Journal successful architecture decisions with Outcome + Lesson",
            "Reuse proven patterns instead of inventing a parallel stack",
        ]
    else:
        reflection = "Signals are mixed — engineering judgment evidence is still thin."
        lesson = (
            "Treat this window as observe time: learn primary repos and write "
            "design-review Experiences after non-trivial changes."
        )
        recs = [
            "Run repository_learning on core projects",
            "After a non-trivial PR, journal Observation→Decision→Outcome→Lesson",
        ]

    if lesson_bits:
        reflection += " Prior lessons: " + " | ".join(lesson_bits[:3])

    topic = force_topic or (top_topics[0] if top_topics else focus)
    return MentorLesson(
        title=f"Engineering mentor weekly: {topic}",
        observation=observation,
        decision_summary="Aggregate of repository / architecture Experiences",
        outcome_summary=(
            f"debt_signals={debt} success_signals={success} mistake_signals={mistakes}"
        ),
        reflection=reflection,
        lesson=lesson,
        recommendations=recs,
        tags=["engineering", "engineering_mentor", "weekly", focus.lower()],
        source_experience_ids=ids[:20],
    )
