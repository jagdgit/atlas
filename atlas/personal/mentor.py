"""Personal Mentor — synthesize owner/career lessons into Experience OS.

Completes the Personal Intelligence Program mentor stub (mirrors Investment /
Engineering mentors). Writes Observation→…→Lesson Experiences that ``advice_for``
and soft-bias can recall for career / owner-knowledge decisions.
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
            "domain": "personal",
            "tags": list(self.tags),
            "recommendations": [
                {"title": r, "why": self.lesson} for r in self.recommendations
            ],
            "source_experience_ids": list(self.source_experience_ids),
        }


_PERSONAL_TAGS = frozenset({
    "personal",
    "career",
    "owner_knowledge",
    "personal_mentor",
    "job_hunting",
    "skill",
    "skills",
    "timeline",
    "identity",
    "professional",
})

_GROWTH_HINTS = (
    "learned",
    "skill",
    "promot",
    "shipped",
    "published",
    "mentor",
    "grew",
    "improve",
)
_GAP_HINTS = (
    "gap",
    "missing",
    "unknown",
    "unclear",
    "stale",
    "incomplete",
    "infer",
)
_CAREER_HINTS = (
    "job",
    "role",
    "interview",
    "resume",
    "career",
    "offer",
    "apply",
)


def _is_personal(e: dict[str, Any]) -> bool:
    tags = {str(t).lower() for t in (e.get("tags") or [])}
    domain = str(e.get("domain") or "").lower()
    title = str(e.get("title") or "").lower()
    if tags & _PERSONAL_TAGS:
        return True
    if domain in {"personal", "career", "experience", "owner"}:
        return True
    if any(k in title for k in ("career", "skill", "resume", "owner", "personal")):
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


def synthesize_personal_lesson(
    experiences: list[dict[str, Any]] | None = None,
    *,
    focus: str = "personal",
    force_topic: str | None = None,
) -> MentorLesson | None:
    """Build a weekly-style personal/career judgment lesson from Experiences.

    Returns ``None`` when there is nothing useful to teach (honest idle).
    """
    rows = [e for e in (experiences or []) if isinstance(e, dict)]
    personal = [e for e in rows if _is_personal(e)]
    if not personal and not force_topic:
        return None
    if not personal and force_topic:
        return MentorLesson(
            title=f"Personal mentor: {force_topic}",
            observation=f"Operator focus: {force_topic}",
            decision_summary="No prior personal Experiences yet — seed lesson only.",
            outcome_summary="n/a",
            reflection=(
                "Without owner_knowledge ticks or career journals, recommendations "
                "stay provisional."
            ),
            lesson=(
                "Run owner_knowledge on the archive and confirm inferred Personal "
                "facts; Mentor will synthesize those next tick."
            ),
            recommendations=[
                "Start owner_knowledge and confirm inferred skills in /ui Personal",
                "Journal career decisions (why apply / why hold) after job_hunting ticks",
            ],
            tags=["personal", "personal_mentor", "seed", focus.lower()],
        )

    growth = 0
    gaps = 0
    career = 0
    topics: list[str] = []
    lesson_bits: list[str] = []
    ids: list[str] = []
    for e in personal[:25]:
        if e.get("id"):
            ids.append(str(e["id"]))
        blob = _blob(e)
        if any(h in blob for h in _GROWTH_HINTS):
            growth += 1
        if any(h in blob for h in _GAP_HINTS):
            gaps += 1
        if any(h in blob for h in _CAREER_HINTS):
            career += 1
        for t in e.get("tags") or []:
            tl = str(t).lower()
            if tl not in _PERSONAL_TAGS and tl not in {
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
        f"Reviewed {len(personal)} personal Experience(s); "
        f"growth_signals={growth} gap_signals={gaps} career_signals={career}"
        + (f"; topics={', '.join(top_topics)}" if top_topics else "")
    )

    if gaps >= max(2, growth):
        reflection = (
            "Profile coverage still has gaps — inferred facts outpace confirmed "
            "owner truth."
        )
        lesson = (
            "Before career moves, confirm high-impact inferred skills/timeline in "
            "the Personal dashboard; do not draft resumes from unverified facts alone."
        )
        recs = [
            "Open /ui Personal and Confirm or Reject inferred facts",
            "Run personal infer after owner_knowledge has new archive material",
            "Draft resume only from verified facts (include_inferred=false)",
        ]
    elif career > growth:
        reflection = (
            "Career / job-hunt signals dominate — decisions are active but growth "
            "journal is thinner."
        )
        lesson = (
            "Pair each job_hunting recommendation with a short Outcome journal "
            "(applied / skipped / why) so Mentor can judge fit over time."
        )
        recs = [
            "Journal Outcome after acting on a Career Advisor recommendation",
            "Keep skills list current before raising apply urgency",
        ]
    elif growth > gaps:
        reflection = (
            "Recent Experiences show skill growth and confirmed owner knowledge."
        )
        lesson = (
            "Reinforce what is verified; still record *why* career choices succeeded "
            "so judgment survives the next role change."
        )
        recs = [
            "Keep confirming new inferred skills after archive ticks",
            "Use draft resume periodically as a coverage smoke test",
        ]
    else:
        reflection = "Signals are mixed — personal judgment evidence is still thin."
        lesson = (
            "Treat this window as observe time: learn the archive, confirm the "
            "profile, then journal one career decision end-to-end."
        )
        recs = [
            "Start owner_knowledge if idle",
            "Confirm at least one inferred skill this week",
        ]

    if lesson_bits:
        reflection += " Prior lessons: " + " | ".join(lesson_bits[:3])

    topic = force_topic or (top_topics[0] if top_topics else focus)
    return MentorLesson(
        title=f"Personal mentor weekly: {topic}",
        observation=observation,
        decision_summary="Aggregate of owner / career Experiences",
        outcome_summary=(
            f"growth_signals={growth} gap_signals={gaps} career_signals={career}"
        ),
        reflection=reflection,
        lesson=lesson,
        recommendations=recs,
        tags=["personal", "personal_mentor", "weekly", focus.lower()],
        source_experience_ids=ids[:20],
    )
