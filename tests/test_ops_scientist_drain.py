"""Ops scientist drain indicator (OI-SCI-DRAIN0 UI)."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.ops.scientist_drain import scientist_drain_snapshot


def test_scientist_drain_counts_reviewed_and_pending(tmp_path: Path):
    lab = "india_equity_learner"
    by = tmp_path / "investment" / "scientist_notes" / lab / "by_id"
    by.mkdir(parents=True)
    (by / "a.json").write_text(
        json.dumps(
            {
                "llm_status": "pending",
                "notes": {"review_status": "DETERMINISTIC"},
            }
        ),
        encoding="utf-8",
    )
    (by / "b.json").write_text(
        json.dumps(
            {
                "llm_status": "done",
                "notes": {"review_status": "REVIEWED"},
            }
        ),
        encoding="utf-8",
    )
    (by / "c.json").write_text(
        json.dumps(
            {
                "llm_status": "failed_permanent",
                "fail_reason": "failed:AttributeError",
                "notes": {"review_status": "UNREVIEWED"},
            }
        ),
        encoding="utf-8",
    )
    fit = tmp_path / "investment" / "llm_fitness"
    fit.mkdir(parents=True)
    (fit / "2026-08-23.jsonl").write_text(
        json.dumps({"purpose": "icr5_scientist_notes", "outcome": "ok"}) + "\n",
        encoding="utf-8",
    )
    snap = scientist_drain_snapshot(tmp_path, as_of_ist="2026-08-23")
    assert snap["version"].startswith("ops.scientist_drain")
    assert snap["REVIEWED"] == 1
    assert snap["pending"] >= 1
    assert snap["failed_permanent"] == 1
    assert snap["retriable"] == 1  # pending only — permanent excluded
    assert snap["fitness_today"]["ok"] == 1
    assert snap["advice_only"] is True


def test_retire_attribute_error_without_llm_burn(tmp_path: Path):
    from atlas.investment.incumbent_scientist import (
        list_pending_llm,
        retire_exhausted_scientist_notes,
    )

    lab = "india_equity_learner"
    by = tmp_path / "investment" / "scientist_notes" / lab / "by_id"
    by.mkdir(parents=True)
    (by / "old.json").write_text(
        json.dumps(
            {
                "notes_id": "n1",
                "symbol": "PRAJIND.NS",
                "llm_status": "failed:AttributeError",
                "notes": {"review_status": "UNREVIEWED"},
            }
        ),
        encoding="utf-8",
    )
    (by / "json.json").write_text(
        json.dumps(
            {
                "notes_id": "n2",
                "symbol": "EICHERMOT.NS",
                "llm_status": "failed_non_json",
                "notes": {"review_status": "UNREVIEWED"},
            }
        ),
        encoding="utf-8",
    )
    out = retire_exhausted_scientist_notes(tmp_path, laboratory_id=lab)
    assert out["retired_n"] == 2
    assert list_pending_llm(tmp_path, laboratory_id=lab) == []
    snap = scientist_drain_snapshot(tmp_path)
    assert snap["failed_permanent"] == 2
    assert snap["retriable"] == 0
