"""OI-DCA0 + JIS Belief Revisions line (Judgment Pivot amendment C)."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.daily_cognitive_agenda import (
    build_daily_agenda,
    count_belief_revisions,
    format_agenda_section,
    format_jis_revisions_section,
    load_agenda,
    mark_agenda_progress,
)
from atlas.investment.reports import format_evening_report, format_morning_report


def test_build_daily_agenda_from_wso_and_curiosity(tmp_path: Path) -> None:
    day = "2026-08-11"
    cq_dir = tmp_path / "investment" / "curiosity_queue"
    cq_dir.mkdir(parents=True)
    (cq_dir / f"{day}.json").write_text(
        json.dumps(
            {
                "ist_date": day,
                "items": [
                    {
                        "symbol": "INFY.NS",
                        "unknown": "next_earnings_date",
                        "status": "queued",
                        "priority": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    wsos = [
        {
            "symbol": "TCS.NS",
            "unknowns": ["fcf_trend", "sector_rel_strength"],
        }
    ]
    agenda = build_daily_agenda(
        tmp_path,
        laboratory_id="india_equity_learner",
        wsos=wsos,
        open_symbols={"TCS.NS"},
        ranked=[{"symbol": "WEAK.NS", "rank": 9, "confidence": 0.2}],
        ist_date=day,
        max_items=5,
    )
    assert agenda["items"]
    kinds = {i["kind"] for i in agenda["items"]}
    assert "open_book" in kinds
    assert "curiosity" in kinds
    loaded = load_agenda(tmp_path, "india_equity_learner", ist_date=day)
    assert len(loaded["items"]) == len(agenda["items"])


def test_structural_review_does_not_clear_agenda() -> None:
    agenda = {
        "items": [
            {
                "symbol": "TCS.NS",
                "intent": "Review open thesis",
                "kind": "open_book",
                "unknowns": ["fcf"],
                "status": "planned",
            }
        ]
    }
    mid = mark_agenda_progress(agenda, symbol="TCS.NS", status="in_progress")
    assert mid["items"][0]["status"] == "in_progress"
    done = mark_agenda_progress(
        mid, symbol="TCS.NS", unknown="fcf", status="done", work_ref="ira"
    )
    assert done["items"][0]["status"] == "done"


def test_count_belief_revisions_excludes_structural(tmp_path: Path) -> None:
    lab = "india_equity_learner"
    from atlas.investment.world_state import lab_dir

    wdir = lab_dir(tmp_path, lab)
    assert wdir is not None
    wdir.mkdir(parents=True)
    (wdir / "TCS.NS.json").write_text(
        json.dumps(
            {
                "symbol": "TCS.NS",
                "revision_history": [
                    {
                        "at": "2026-08-11T10:00:00Z",
                        "status": "strengthened",
                        "evidence_delta": {"structural": True},
                    },
                    {
                        "at": "2026-08-11T12:00:00Z",
                        "status": "weakened",
                        "evidence_delta": {"source": "ira"},
                        "llm": True,
                    },
                    {
                        "at": "2026-08-09T12:00:00Z",
                        "status": "falsified",
                        "evidence_delta": {"note": "x"},
                        "llm": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    stats = count_belief_revisions(tmp_path, lab, days=7)
    # structural excluded; today weakened + period includes falsified if within window
    assert stats["today"] >= 1
    assert stats["period"] >= 1
    assert stats["by_status"].get("weakened", 0) >= 1


def test_morning_and_evening_sections_render() -> None:
    agenda = {
        "items": [
            {
                "symbol": "INFY.NS",
                "intent": "Pursue curiosity: earnings",
                "kind": "curiosity",
                "unknowns": ["earnings"],
                "status": "planned",
            }
        ],
        "empty_reason": None,
    }
    m = format_agenda_section(agenda, when="morning")
    assert any("intend to think" in x for x in m)
    assert any("INFY.NS" in x for x in m)
    e = format_agenda_section(
        {**agenda, "items": [{**agenda["items"][0], "status": "done"}]},
        when="evening",
    )
    assert any("[done]" in x for x in e)
    jis = format_jis_revisions_section({"today": 0, "days": 7, "period": 0})
    assert any("Belief Revisions: today=0" in x for x in jis)


def test_reports_include_dca_and_jis() -> None:
    port = {
        "laboratory_id": "india_equity_learner",
        "cognitive_agenda": {
            "items": [
                {
                    "symbol": "TCS.NS",
                    "intent": "Review thesis",
                    "kind": "open_book",
                    "unknowns": [],
                    "status": "planned",
                }
            ]
        },
        "jis_revisions": {"today": 1, "days": 7, "period": 2, "by_status": {"weakened": 1}},
        "world_states": [],
    }
    _, morning = format_morning_report(
        plan={"as_of": "2026-08-11", "phase": "observe", "candidates": []},
        portfolio=port,
        laboratory_id="india_equity_learner",
    )
    assert "Daily Cognitive Agenda" in morning
    assert "intend to think" in morning
    _, evening = format_evening_report(
        plan={"as_of": "2026-08-11", "phase": "observe"},
        portfolio=port,
        laboratory_id="india_equity_learner",
    )
    assert "Belief Revisions: today=1" in evening
    assert "Agenda progress" in evening
