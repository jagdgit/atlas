"""Job report honesty + waiting / Next Action (RH.5–RH.8)."""

from __future__ import annotations

from atlas.evidence.models import CONFIDENCE_NOT_APPLICABLE
from atlas.jobs.service import JobService
from atlas.models.job import STEP_BLOCKED, Job, JobStep
from atlas.reports.generator import ReportGenerator
from atlas.reports.service import ReportService
from atlas.transcripts.acquisition import (
    SPEECH_STATUS_MISSING,
    default_media_recovery_strategies,
    format_next_action,
)


def test_format_next_action_job_waiting():
    text = format_next_action(
        default_media_recovery_strategies(),
        speech_status=SPEECH_STATUS_MISSING,
        audience="job",
        status="waiting",
    )
    assert text.startswith("Waiting for operator.")
    assert "Research blocked" not in text
    assert "speech_to_text status: missing" in text


def test_report_job_waiting_uses_next_action_not_verification_boilerplate():
    gen = ReportGenerator()
    termination = {
        "stage": "acquire",
        "status": "waiting",
        "reason": "interactive_recovery_required",
        "reason_code": "interactive_recovery_required",
        "knowledge_produced": 0,
        "reasoning": "not_started",
        "verification": "not_executed",
        "waiting_for": "media_asset",
        "audience": "job",
        "suggested_next_strategies": list(default_media_recovery_strategies()),
        "speech_to_text_status": SPEECH_STATUS_MISSING,
    }
    report = gen.generate("Learn from this video", claims=[], termination=termination)
    assert report["overall_confidence"] == CONFIDENCE_NOT_APPLICABLE
    conf = report["sections"]["confidence"]
    assert conf["stage"] == "acquire"
    assert conf["status"] == "waiting"
    assert conf["result"] == "waiting"
    assert conf["reasoning"] == "not_started"
    assert "Verification Engine" not in report["sections"]["methodology"]
    assert "waiting for operator" in report["sections"]["methodology"].lower()
    assert report["sections"]["next_section_title"] == "Next Action"
    assert "Waiting for operator" in report["sections"]["next_research"]
    assert "No further research required" not in report["sections"]["next_research"]
    assert "No verifiable claims" not in report["sections"]["answer"]
    md = report["markdown"]
    assert "## Next Action" in md
    assert "Waiting" in md
    assert "interactive_recovery_required" in md


def test_job_finalize_passes_termination_from_blocked_media_learn():
    """RH.5: JobService builds termination from media.learn blocked step extras."""

    class FakeRepo:
        def __init__(self):
            self.job = Job(
                id="j1",
                objective="Learn from https://youtu.be/abcdefghijk",
                status="running",
            )
            self.steps = [
                JobStep(
                    id="s1",
                    job_id="j1",
                    ordinal=0,
                    intent="media_learn",
                    capability="media_learn",
                    status=STEP_BLOCKED,
                    description="Learn from media.",
                    blocked_reason="interactive_recovery_required",
                    result={
                        "answer": (
                            "Acquisition failed before read. "
                            "Suggested next strategies: upload."
                        ),
                        "interactive_recovery": True,
                        "suggested_next_strategies": list(
                            default_media_recovery_strategies()
                        ),
                        "speech_to_text_status": SPEECH_STATUS_MISSING,
                        "acquisition": {
                            "stage": "acquire",
                            "reason_code": "robots_disallowed",
                            "strategies_tried": [
                                {
                                    "strategy": "youtube_caption_tracks",
                                    "outcome": "blocked",
                                }
                            ],
                        },
                        "strategies": [
                            {
                                "strategy": "youtube_caption_tracks",
                                "outcome": "blocked",
                            },
                            {
                                "strategy": "browser_dom_captions",
                                "outcome": "skipped",
                            },
                        ],
                    },
                )
            ]
            self.final_status = None
            self.final_result = None

        def get_job(self, job_id):
            return self.job

        def list_steps(self, job_id):
            return list(self.steps)

        def set_job_status(self, job_id, status, result=None, **kw):
            self.final_status = status
            self.final_result = result

        def recover_interrupted_steps(self):
            return 0

        def list_unfinished_jobs(self):
            return []

    repo = FakeRepo()
    reports = ReportService(generator=ReportGenerator())
    svc = JobService(repo, planner=None, runner=None, reports=reports)
    term = svc._acquire_termination_from_steps(repo.steps)
    assert term is not None
    assert term["stage"] == "acquire"
    assert term["status"] == "waiting"
    assert term["audience"] == "job"
    assert term["reason"] == "interactive_recovery_required"

    answer = svc._answer(repo.steps)
    assert "Acquisition failed" in answer or "Suggested next" in answer

    report = svc._build_report("j1", repo.steps)
    assert report is not None
    assert report["overall_confidence"] == CONFIDENCE_NOT_APPLICABLE
    assert "Next Action" in (report.get("markdown") or "")
    assert "No further research required" not in (report.get("markdown") or "")
    assert "Verification Engine" not in (report.get("sections") or {}).get(
        "methodology", ""
    )
