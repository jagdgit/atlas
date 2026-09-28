"""F&O-LAB isolated paper cycle. Live orders off. Not R1-LIVE. Not L5."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.fno_lab_loop import (
    FNO_LESSON_ID,
    LABORATORY_ID,
    PRODUCTION_FNO_LAB,
    lab_policy,
    run_synthetic_cycle,
)
from atlas.investment.lesson_influence import E001_LESSON_ID


def test_fno_lab_policy_isolates_live_capital():
    p = lab_policy()
    assert p["live_orders"] is False
    assert p["live_execution"] is False
    assert p["capital_isolated"] is True
    assert p["laboratory_id"] == LABORATORY_ID
    assert p["isolated_from"] == PRODUCTION_FNO_LAB
    assert p["sma_rsi_untouched"] is True
    assert "live_fno_execution" in p["forbids"]


def test_fno_synthetic_cycle_retrieves_lesson_on_next_decision(tmp_path: Path):
    report = run_synthetic_cycle(tmp_path)
    assert report["live_orders"] is False
    assert report["never_orders"] is True
    assert report["first_cited_e001"] is True
    assert E001_LESSON_ID in report["first_decision"]["lesson_refs"]
    assert report["outcome"]["prediction_error"] is True
    assert report["next_retrieved_fno_lesson"] is True
    assert FNO_LESSON_ID in report["next_decision_lesson_refs"]
    assert report["loop_closed"] is True
    assert report["atlas_has_learned"] is False
    assert report["r1_live"] is False
    lesson = tmp_path / "investment" / "fel" / "lessons" / f"{FNO_LESSON_ID}.json"
    assert lesson.is_file()
    # Restart/retrieve: same lesson file still matches the next query.
    from atlas.investment.fno_lab_loop import fno_lesson, retrieve_for_decision

    again = retrieve_for_decision(
        query="Condition X ATM CE volume acceleration",
        extra=[fno_lesson()],
    )
    ids = {str(x.get("id")) for x in again}
    assert FNO_LESSON_ID in ids
