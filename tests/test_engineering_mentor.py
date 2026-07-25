"""Engineering Mentor + Experience synthesis (OI-MP4)."""

from __future__ import annotations

from atlas.engineering.mentor import synthesize_engineering_lesson
from atlas.workers.base import TickContext
from atlas.workers.engineering_mentor import EngineeringMentorWorker
from atlas.missions.philosophy import philosophy_for
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.programs import get_program, MEMBER_ENABLED


def test_synthesize_idle_without_experiences():
    assert synthesize_engineering_lesson([]) is None


def test_synthesize_seed_force_topic():
    lesson = synthesize_engineering_lesson([], force_topic="atlas-core")
    assert lesson is not None
    assert "atlas-core" in lesson.title
    assert lesson.recommendations
    assert "engineering" in lesson.tags


def test_synthesize_from_debt_signals():
    experiences = [
        {
            "id": "e1",
            "title": "Repo note: legacy workaround in ingest",
            "tags": ["engineering", "tech_debt", "legacy"],
            "lessons": "Lesson: avoid parallel hacks",
            "domain": "engineering",
        },
        {
            "id": "e2",
            "title": "Fragile duplicate path in readers",
            "tags": ["repository_learning", "debt"],
            "lessons": "Lesson: consolidate",
        },
    ]
    lesson = synthesize_engineering_lesson(experiences)
    assert lesson is not None
    assert "debt_signals" in lesson.outcome_summary
    assert any("debt" in r.lower() or "workaround" in r.lower() for r in lesson.recommendations)
    payload = lesson.experience_payload()
    assert payload["domain"] == "engineering"
    assert "Observation:" in payload["problem"]


def test_synthesize_from_mistake_signals():
    experiences = [
        {
            "id": "e1",
            "title": "Regression after refactor",
            "tags": ["engineering", "bug", "regress"],
            "lessons": "Lesson: add regression test",
            "domain": "engineering",
        },
        {
            "id": "e2",
            "title": "Had to revert architecture change",
            "tags": ["architecture", "revert", "mistake"],
            "lessons": "Lesson: blast radius",
        },
    ]
    lesson = synthesize_engineering_lesson(experiences)
    assert lesson is not None
    assert any("regression" in r.lower() or "diff" in r.lower() for r in lesson.recommendations)


def test_mentor_worker_writes_once():
    remembered: list[dict] = []

    class _Learning:
        def list_experiences(self, *, limit=40):
            return [
                {
                    "id": "e1",
                    "title": "Clean modular refactor succeeded",
                    "tags": ["engineering", "refactor", "test", "stable"],
                    "lessons": "Lesson: reinforce pattern",
                    "domain": "engineering",
                }
            ]

        def remember_experience(self, **fields):
            remembered.append(fields)
            return {"ok": True}

    worker = EngineeringMentorWorker(learning=_Learning())
    r1 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "engineering"},
            config_version=1,
            state={},
        )
    )
    assert "wrote=True" in r1.note
    assert remembered
    assert remembered[0]["domain"] == "engineering"
    r2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "engineering"},
            config_version=1,
            state=r1.state,
        )
    )
    assert "unchanged" in r2.note
    assert len(remembered) == 1


def test_mentor_enables_soft_bias_by_default():
    biased: list[str] = []

    class _Learning:
        def list_experiences(self, *, limit=40):
            return [
                {
                    "id": "e1",
                    "title": "Pattern applied successfully",
                    "tags": ["engineering", "pattern", "modular"],
                    "lessons": "Lesson: reuse",
                    "domain": "engineering",
                }
            ]

        def remember_experience(self, **fields):
            return {"event": {"id": "ev1", "ref_id": "exp-eng-1"}, "applied": True}

        def enable_bias(self, experience_id, *, enabled=True):
            biased.append(str(experience_id))
            return {"bias_enabled": enabled}

    worker = EngineeringMentorWorker(learning=_Learning())
    r = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "engineering"},
            config_version=1,
            state={},
        )
    )
    assert "wrote=True" in r.note
    assert biased == ["exp-eng-1"]


def test_engineering_mentor_template_and_program():
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    assert "engineering_mentor" in names
    phil = philosophy_for("engineering_mentor")
    assert phil["mission_kind"] == "maintenance"
    assert phil["lifecycle"]["reflect"] == "active"
    prog = get_program("engineering_intelligence")
    assert prog is not None
    mentor = next(m for m in prog.members if m.template == "engineering_mentor")
    assert mentor.status == MEMBER_ENABLED
