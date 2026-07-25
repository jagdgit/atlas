"""Personal Mentor + Experience synthesis (Personal Intelligence Program)."""

from __future__ import annotations

from atlas.personal.mentor import synthesize_personal_lesson
from atlas.workers.base import TickContext
from atlas.workers.personal_mentor import PersonalMentorWorker
from atlas.missions.philosophy import philosophy_for
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.programs import get_program, MEMBER_ENABLED


def test_synthesize_idle_without_experiences():
    assert synthesize_personal_lesson([]) is None


def test_synthesize_seed_force_topic():
    lesson = synthesize_personal_lesson([], force_topic="skills")
    assert lesson is not None
    assert "skills" in lesson.title
    assert lesson.recommendations
    assert "personal" in lesson.tags


def test_synthesize_from_gap_signals():
    experiences = [
        {
            "id": "e1",
            "title": "Inferred skill still incomplete",
            "tags": ["personal", "skill", "gap", "infer"],
            "lessons": "Lesson: confirm facts",
            "domain": "personal",
        },
        {
            "id": "e2",
            "title": "Unknown timeline years",
            "tags": ["owner_knowledge", "unclear", "missing"],
            "lessons": "Lesson: ask owner",
        },
    ]
    lesson = synthesize_personal_lesson(experiences)
    assert lesson is not None
    assert "gap_signals" in lesson.outcome_summary
    assert any("confirm" in r.lower() or "personal" in r.lower() for r in lesson.recommendations)
    assert lesson.experience_payload()["domain"] == "personal"


def test_mentor_worker_writes_once():
    remembered: list[dict] = []

    class _Learning:
        def list_experiences(self, *, limit=40):
            return [
                {
                    "id": "e1",
                    "title": "Learned skill growth confirmed",
                    "tags": ["personal", "skill", "learned", "improve"],
                    "lessons": "Lesson: reinforce",
                    "domain": "personal",
                }
            ]

        def remember_experience(self, **fields):
            remembered.append(fields)
            return {"ok": True}

    worker = PersonalMentorWorker(learning=_Learning())
    r1 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "personal"},
            config_version=1,
            state={},
        )
    )
    assert "wrote=True" in r1.note
    assert remembered[0]["domain"] == "personal"
    r2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "personal"},
            config_version=1,
            state=r1.state,
        )
    )
    assert "unchanged" in r2.note


def test_personal_mentor_template_and_program():
    assert "personal_mentor" in {t["name"] for t in BUILTIN_TEMPLATES}
    phil = philosophy_for("personal_mentor")
    assert phil["mission_kind"] == "maintenance"
    assert phil["lifecycle"]["reflect"] == "active"
    prog = get_program("personal_intelligence")
    mentor = next(m for m in prog.members if m.template == "personal_mentor")
    assert mentor.status == MEMBER_ENABLED
