"""Media Report Honesty (RH.1–RH.3) — acquire-stop report UX."""

from __future__ import annotations

from atlas.evidence.models import CONFIDENCE_HIGH, CONFIDENCE_INSUFFICIENT, CONFIDENCE_NOT_APPLICABLE
from atlas.reports.generator import ReportGenerator
from atlas.transcripts.acquisition import (
    REASON_ROBOTS_DISALLOWED,
    STRATEGY_ENABLE_SPEECH_TO_TEXT,
    STRATEGY_UPLOAD_LOCAL_MEDIA,
    STRATEGY_UPLOAD_TRANSCRIPT,
    STRATEGY_YOUTUBE_CAPTION_TRACKS,
    AcquisitionAttempt,
    AcquisitionRecord,
    SPEECH_STATUS_DISABLED,
    SPEECH_STATUS_MISSING,
    SPEECH_STATUS_READY,
    default_media_recovery_strategies,
    format_next_research_blocked,
    speech_to_text_status,
)


def test_speech_status_distinguishes_disabled_vs_missing():
    assert speech_to_text_status(enabled=False, available=True) == SPEECH_STATUS_DISABLED
    assert speech_to_text_status(enabled=True, available=False) == SPEECH_STATUS_MISSING
    assert speech_to_text_status(enabled=False, available=False) == SPEECH_STATUS_MISSING
    assert speech_to_text_status(enabled=True, available=True) == SPEECH_STATUS_READY


def test_acquisition_record_prefers_operator_strategies_in_summary():
    attempt = AcquisitionAttempt(
        STRATEGY_YOUTUBE_CAPTION_TRACKS,
        "skipped",
        reason="robots.txt disallows this URL",
        reason_code=REASON_ROBOTS_DISALLOWED,
    )
    acq = AcquisitionRecord.from_attempts(
        [attempt],
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        suggested_next_capability="speech_to_text",
        suggested_next_strategies=default_media_recovery_strategies(),
        speech_to_text_status=SPEECH_STATUS_DISABLED,
    )
    summary = acq.operator_summary
    assert "Acquisition failed before read" in summary
    assert "Suggested next strategies:" in summary
    assert "upload" in summary.lower() or "transcript" in summary.lower()
    assert "speech_to_text status: disabled" in summary
    d = acq.as_dict()
    assert STRATEGY_UPLOAD_TRANSCRIPT in d["suggested_next_strategies"]
    assert STRATEGY_ENABLE_SPEECH_TO_TEXT in d["suggested_next_strategies"]


def test_report_acquire_stop_not_insufficient_and_not_no_further_research():
    gen = ReportGenerator()
    termination = {
        "stage": "acquire",
        "reason_code": REASON_ROBOTS_DISALLOWED,
        "reason": "robots.txt disallows this URL",
        "knowledge_produced": 0,
        "suggested_next_strategies": list(default_media_recovery_strategies()),
        "speech_to_text_status": SPEECH_STATUS_DISABLED,
    }
    report = gen.generate(
        "Summarize the lecture video",
        claims=[],
        pipeline={"found": 1, "acquired": 0, "read": 0, "chars_read": 0},
        termination=termination,
    )
    assert report["overall_confidence"] == CONFIDENCE_NOT_APPLICABLE
    conf = report["sections"]["confidence"]
    assert conf["result"] == "acquisition_failed"
    assert conf["reason_code"] == REASON_ROBOTS_DISALLOWED
    assert conf["knowledge_produced"] == 0
    assert conf["reasoning"] == "not_started"
    assert conf["verification"] == "not_executed"
    methodology = report["sections"]["methodology"]
    assert "terminated during acquisition" in methodology.lower()
    assert "Verification was not executed" in methodology
    assert "No Evidence Budget or convergence assessment was performed" in methodology
    assert "Verification Engine: sources were graded" not in methodology
    next_r = report["sections"]["next_research"]
    assert "Research blocked" in next_r
    assert "No further research required" not in next_r
    assert "local media" in next_r
    assert "speech_to_text status: disabled" in next_r
    assert "Acquisition failed before read" in report["sections"]["executive_summary"]
    md = report["markdown"]
    assert "Blocked" in md or "Acquisition" in md
    assert "NOT_APPLICABLE" in md


def test_report_normal_path_unchanged_when_claims_exist():
    gen = ReportGenerator()
    report = gen.generate(
        "Estimate X",
        claims=[{
            "statement": "X is 4%",
            "confidence": CONFIDENCE_HIGH,
            "convergence": 1.0,
            "supporting_sources": [{"source_id": "s1", "evidence_level": 4}],
            "contradicting_sources": [],
        }],
    )
    assert report["overall_confidence"] == CONFIDENCE_HIGH
    assert "Verification Engine" in report["sections"]["methodology"]
    assert report["sections"]["confidence"]["overall"] == CONFIDENCE_HIGH


def test_format_next_research_blocked_lists_operator_actions():
    text = format_next_research_blocked(
        default_media_recovery_strategies(),
        speech_status=SPEECH_STATUS_MISSING,
    )
    assert text.startswith("Research blocked.")
    assert "Continue after one of:" in text
    assert "speech_to_text status: missing" in text


def test_empty_claims_without_termination_still_insufficient():
    """Evidence insufficiency (no claims, no acquire-stop) stays INSUFFICIENT."""
    report = ReportGenerator().generate("X", claims=[])
    assert report["overall_confidence"] == CONFIDENCE_INSUFFICIENT
    assert "No further research required" in report["sections"]["next_research"]
