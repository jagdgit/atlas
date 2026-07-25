"""OI-F4 standardized post-decision feedback loops."""

from __future__ import annotations

from atlas.decision.feedback import (
    DIFF_MATCHED,
    DIFF_MISSED,
    DIFF_UNKNOWN,
    build_feedback_journal,
    collect_outcome_feedback,
    difference_label,
    record_feedback_loop,
    should_enable_feedback_bias,
)
from atlas.workers.base import TickContext
from atlas.workers.job_watcher import JobWatcher
from atlas.workers.tech_security import TechSecurityWatcher


def test_difference_and_bias_gate():
    assert difference_label("recommend", "applied") == DIFF_MATCHED
    assert difference_label("recommend", "ignored") == DIFF_MISSED
    assert difference_label("recommend", "unknown") == DIFF_UNKNOWN
    assert should_enable_feedback_bias(DIFF_MATCHED) is True
    assert should_enable_feedback_bias(DIFF_MISSED) is True
    assert should_enable_feedback_bias(DIFF_UNKNOWN) is False


def test_record_feedback_loop_enables_bias_on_matched():
    class FakeOS:
        def __init__(self):
            self.last = None

        def journal(self, **kw):
            self.last = kw
            return {"ok": True, "result": {"event": {"ref_id": "exp-fb"}, "applied": True}}

    class FakeLearning:
        def __init__(self):
            self.enabled = []

        def enable_bias(self, experience_id, *, enabled=True):
            self.enabled.append((experience_id, enabled))

    os_ = FakeOS()
    learn = FakeLearning()
    kw = build_feedback_journal(
        title="Job feedback",
        recommendation="recommend posting X",
        outcome="ignored",
        difference=DIFF_MISSED,
        mission_type="job_hunting",
        decision_id="dec-9",
        subject="post-1",
    )
    out = record_feedback_loop(
        experience_os=os_,
        learning=learn,
        journal_kwargs=kw,
        enable_bias=True,
        difference=DIFF_MISSED,
    )
    assert out["ok"] is True
    assert out["bias_enabled"] is True
    assert learn.enabled == [("exp-fb", True)]
    assert os_.last["metadata"]["feedback_loop"] is True
    assert os_.last["metadata"]["decision_id"] == "dec-9"
    assert "feedback_loop" in os_.last["tags"]


def test_collect_outcome_feedback_from_inputs_and_cfg():
    items = collect_outcome_feedback(
        [{"outcome_feedback": True, "outcome": "applied", "decision_id": "d1"}],
        {"outcome_feedback": [{"outcome": "ignored", "decision_id": "d2"}]},
    )
    assert len(items) == 2
    assert items[0]["decision_id"] == "d1"
    assert items[1]["decision_id"] == "d2"


def test_job_watcher_journals_outcome_feedback():
    class FakeOS:
        def __init__(self):
            self.journals = []

        def journal(self, **kw):
            self.journals.append(kw)
            return {"ok": True, "result": {"event": {"ref_id": "exp-job"}, "applied": True}}

    class FakeLearning:
        def __init__(self):
            self.enabled = []

        def enable_bias(self, experience_id, *, enabled=True):
            self.enabled.append(experience_id)

    os_ = FakeOS()
    learn = FakeLearning()
    worker = JobWatcher(
        assets=None,
        postings_reader=None,
        decision_engine=None,
        experience_os=os_,
        learning=learn,
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={},
            config_version=1,
            state={"last_decision_id": "dec-job"},
            inputs=[
                {
                    "outcome_feedback": True,
                    "recommendation": "recommend Senior SWE",
                    "outcome": "ignored",
                    "subject": "post-42",
                }
            ],
        )
    )
    assert "feedback=1" in (result.note or "")
    assert len(os_.journals) == 1
    assert os_.journals[0]["metadata"]["feedback_loop"] is True
    assert os_.journals[0]["metadata"]["difference"] == DIFF_MISSED
    assert learn.enabled == ["exp-job"]


def test_tech_security_journals_outcome_feedback():
    class FakeOS:
        def __init__(self):
            self.journals = []

        def journal(self, **kw):
            self.journals.append(kw)
            return {"ok": True, "result": {"event": {"ref_id": "exp-sec"}, "applied": True}}

    class FakeLearning:
        def enable_bias(self, experience_id, *, enabled=True):
            return None

    worker = TechSecurityWatcher(
        assets=None,
        advisory_reader=None,
        decision_engine=None,
        experience_os=FakeOS(),
        learning=FakeLearning(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"mode": "security"},
            config_version=1,
            state={},
            inputs=[
                {
                    "kind": "outcome_feedback",
                    "recommendation": "upgrade openssl",
                    "outcome": "applied",
                    "decision_id": "dec-sec",
                }
            ],
        )
    )
    assert "feedback=1" in (result.note or "")
    assert worker._experience_os.journals[0]["metadata"]["difference"] == DIFF_MATCHED
