"""Learning Report mode (LR1–LR8) — media.learn ≠ Research verification template."""

from __future__ import annotations

from atlas.reports.generator import (
    LEARNING_STATUS_COMPLETE,
    LEARNING_STATUS_PARTIAL,
    ReportGenerator,
)


def test_learning_report_not_research_insufficient():
    report = ReportGenerator().generate(
        "https://youtu.be/zHt5Mdr0QFk learn from this video",
        claims=[],
        answer="Learned from media (knowledge_produced=1).",
        termination={
            "mode": "learning",
            "stage": "learn",
            "status": "partial",
            "learning_status": LEARNING_STATUS_PARTIAL,
            "audience": "job",
            "knowledge_produced": 1,
            "asset_id": "asset-54mb",
            "asset_kind": "audio",
            "source": "https://youtu.be/zHt5Mdr0QFk",
            "title": "Demo",
            "metadata_fields": {"title": "Demo", "uploader": "Atlas"},
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "waiting",
                "speech": "waiting",
                "knowledge": "success",
            },
            "strategies_tried": [
                {
                    "strategy": "youtube_media",
                    "outcome": "ok",
                    "reason_code": "asset_registered",
                    "asset_id": "asset-54mb",
                },
                {
                    "strategy": "media_metadata",
                    "outcome": "ok",
                    "reason_code": "artifact_produced",
                    "asset_id": "asset-54mb",
                },
                {
                    "strategy": "speech_to_text",
                    "outcome": "skipped",
                    "reason_code": "missing",
                },
                {
                    "strategy": "knowledge",
                    "outcome": "ok",
                    "reason_code": "metadata_ingested",
                },
            ],
            "suggested_next_strategies": ["enable_speech_to_text", "upload_transcript"],
            "speech_to_text_status": "missing",
            "verification": "not_executed",
            "reasoning": "not_started",
        },
    )
    md = report["markdown"]
    assert report["report_kind"] == "learning"
    assert report["overall_confidence"] == LEARNING_STATUS_PARTIAL
    assert md.startswith("# Learning Report:")
    assert "INSUFFICIENT" not in md
    assert "No sources yielded verifiable claims" not in md
    assert "No verified claims" not in md
    assert "Each claim was assessed" not in md  # research methodology
    assert "governed by a per-job Evidence Budget" not in md
    assert "Learning Status" in md
    assert "PARTIAL" in md
    assert "metadata" in report["sections"]["executive_summary"].lower() or (
        "Knowledge categories" in md
    )
    # Prefer category table when breakdown present
    assert "Spoken content has not yet been learned" in report["sections"]["executive_summary"]
    assert "Knowledge Produced" in md
    assert "Observations" in md
    assert "asset_id" in md.lower() or "asset-54mb" in md
    assert "Next Action" in md
    assert "Research Funnel" not in md
    conf = report["sections"]["confidence"]
    assert conf["result"] == "learning"
    assert conf["verification"] == "not_executed"


def test_learning_complete_when_speech_success():
    report = ReportGenerator().generate(
        "learn local lecture",
        termination={
            "mode": "learning",
            "learning_status": LEARNING_STATUS_COMPLETE,
            "knowledge_produced": 2,
            "source": "/tmp/talk.mp3",
            "asset_id": "a9",
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "success",
                "speech": "success",
                "knowledge": "success",
            },
        },
    )
    assert report["overall_confidence"] == LEARNING_STATUS_COMPLETE
    assert "COMPLETE" in report["markdown"]


def test_acquire_stop_unchanged_lr8():
    report = ReportGenerator().generate(
        "learn video",
        claims=[],
        termination={
            "stage": "acquire",
            "status": "waiting",
            "reason": "interactive_recovery_required",
            "audience": "job",
            "waiting_for": "media_asset",
            "knowledge_produced": 0,
            "suggested_next_strategies": ["upload_transcript"],
        },
    )
    assert "Research Report:" in report["markdown"] or "Acquire" in report["markdown"]
    assert report["sections"]["confidence"].get("result") == "waiting"
    assert "Learning Report:" not in report["markdown"]


def test_ls1_learning_status_capability_summary():
    report = ReportGenerator().generate(
        "learn video",
        termination={
            "mode": "learning",
            "learning_status": LEARNING_STATUS_PARTIAL,
            "knowledge_produced": 1,
            "source": "https://youtu.be/zHt5Mdr0QFk",
            "asset_id": "a1",
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "waiting",
                "speech": "waiting",
                "knowledge": "success",
            },
        },
    )
    md = report["markdown"]
    assert "| Metadata | ✓ Learned |" in md
    assert "| Transcript | Pending |" in md
    assert "| Speech | Pending |" in md
    assert "| Knowledge | ✓ Learned |" in md or "| Knowledge |" in md


def test_knowledge_categories_in_learning_report():
    report = ReportGenerator().generate(
        "learn investing video",
        termination={
            "mode": "learning",
            "learning_status": LEARNING_STATUS_PARTIAL,
            "knowledge_produced": 1,
            "knowledge_breakdown": {
                "metadata": 1,
                "transcript": 0,
                "transcript_chunks": 0,
                "concepts": 0,
                "entities": 0,
                "relationships": 0,
                "facts": 0,
                "summaries": 0,
            },
            "source": "https://youtu.be/zHt5Mdr0QFk",
            "asset_id": "a1",
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "waiting",
                "speech": "waiting",
                "knowledge": "success",
            },
        },
    )
    md = report["markdown"]
    assert "### Knowledge categories" in md
    assert "| metadata | 1 |" in md
    assert "| transcript | 0 |" in md
    assert "| concepts | 0 |" in md
    assert "Metadata learned successfully" in report["sections"]["answer"] or (
        "Spoken content has not yet been learned" in report["sections"]["answer"]
    )
    assert "Learned from '" not in report["sections"]["answer"] or "Spoken content" in report["sections"]["answer"]
