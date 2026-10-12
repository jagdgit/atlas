"""J3 — a step that produced nothing must not report success.

The live failure this closes: job `b370b60a` logged "completed — 4/4 step(s) done,
failed: 0" while its answer was four no-op replies concatenated, 0 documents and 0
citations. A clean run that yields no evidence is neither success nor an exception.
"""

from __future__ import annotations

from atlas.models.job import STEP_DONE, STEP_FAILED, STEP_PENDING
from atlas.services.assistant_service import _Outcome


class FakeExecutor:
    def __init__(self, data):
        self._data = data

    def execute(self, tool, args):
        class _R:
            ok = True
            error = None
            data = self._data

        return _R()


_DEFAULT_ARGS = {"sql": "SELECT 1"}


def _sql_outcome(data, args=_DEFAULT_ARGS):
    """Drive `_do_sql` with a stubbed executor, as the dispatcher would."""
    from atlas.services.assistant_service import AssistantService

    svc = object.__new__(AssistantService)
    svc._executor = FakeExecutor(data)  # noqa: SLF001 - exercising one handler in isolation
    svc._sql_tool = "sql.query"  # noqa: SLF001
    return AssistantService._do_sql(svc, args, None, [])


# --- the outcome contract ---------------------------------------------------


def test_rows_are_productive():
    out = _sql_outcome({"outcome": "ok", "columns": ["n"], "rows": [{"n": 1}]})
    assert out.productive is True
    assert out.gap_reason is None


def test_zero_rows_is_a_gap_not_a_success():
    out = _sql_outcome({"outcome": "ok", "columns": ["n"], "rows": []})
    assert out.productive is False
    assert "matched no rows" in out.gap_reason


def test_explicit_empty_outcome_is_a_gap():
    out = _sql_outcome({"outcome": "empty", "columns": [], "rows": []})
    assert out.productive is False


def test_a_step_planned_without_sql_is_a_gap():
    # This is verbatim the step that reported `done` in job b370b60a.
    out = _sql_outcome({"outcome": "ok", "rows": []}, args={})
    assert out.answer == "What SQL query should I run?"
    assert out.productive is False
    assert "no SQL was planned" in out.gap_reason


def test_outcome_defaults_stay_productive():
    # Every other handler keeps today's behaviour without being touched.
    assert _Outcome(answer="hi").productive is True


# --- the Job Engine reaction ------------------------------------------------


class FakeRepo:
    def __init__(self):
        self.calls: list[dict] = []

    def set_step_status(self, step_id, status, **kw):
        self.calls.append({"id": step_id, "status": status, **kw})


class FakeRecorder:
    def __init__(self):
        self.records: list[tuple] = []

    def record(self, phase, message, **kw):
        self.records.append((phase, message, kw))


class FakeStep:
    def __init__(self, attempts=0):
        self.id = "step-1"
        self.ordinal = 1
        self.intent = "sql_query"
        self.capability = "sql"
        self.description = "find the failures"
        self.attempts = attempts
        self.status = STEP_PENDING
        self.result = None


class FakeJob:
    id = "job-1"


def _service(max_retries=2):
    from atlas.jobs.service import JobService

    svc = object.__new__(JobService)
    svc._repo = FakeRepo()  # noqa: SLF001
    svc._step_max_retries = max_retries  # noqa: SLF001
    import logging

    svc._logger = logging.getLogger("test.j3")  # noqa: SLF001
    return svc


def test_a_gap_retries_before_it_gives_up():
    svc = _service(max_retries=2)
    rec = FakeRecorder()
    step = FakeStep(attempts=0)
    svc._on_step_gap(FakeJob(), step, rec, _Outcome(answer="none"), [], "the query matched no rows")
    call = svc._repo.calls[-1]
    assert call["status"] == STEP_PENDING
    assert call["result"]["productive"] is False
    assert "retrying" in rec.records[-1][1]


def test_a_gap_lands_in_failed_not_done_once_retries_are_spent():
    svc = _service(max_retries=2)
    rec = FakeRecorder()
    step = FakeStep(attempts=1)
    svc._on_step_gap(FakeJob(), step, rec, _Outcome(answer="none"), [], "the query matched no rows")
    call = svc._repo.calls[-1]
    assert call["status"] == STEP_FAILED
    assert call["status"] != STEP_DONE
    assert "no usable result" in call["error"]
    assert "matched no rows" in call["error"]


def test_the_gap_reason_is_recorded_on_the_activity_feed():
    svc = _service()
    rec = FakeRecorder()
    svc._on_step_gap(FakeJob(), FakeStep(attempts=1), rec, _Outcome(answer="n"), [], "no rows")
    _phase, message, kw = rec.records[-1]
    assert kw["state"] == "gap"
    assert kw["reason"] == "no rows"
    assert "produced no usable result" in message


def test_extras_survive_onto_the_gap_result():
    svc = _service()
    rec = FakeRecorder()
    outcome = _Outcome(answer="n", extras={"usage": {"documents_count": 0}})
    svc._on_step_gap(FakeJob(), FakeStep(attempts=1), rec, outcome, [], "no rows")
    assert svc._repo.calls[-1]["result"]["usage"] == {"documents_count": 0}


# --- the finalized job ------------------------------------------------------


class DoneStep(FakeStep):
    def __init__(self, result):
        super().__init__()
        self.result = result


def test_gaps_are_named_in_the_job_result():
    from atlas.jobs.service import JobService

    steps = [
        DoneStep({"productive": False, "gap_reason": "the query matched no rows"}),
        DoneStep({"answer": "real evidence"}),
    ]
    gaps = JobService._gaps(steps)
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "the query matched no rows"
    assert gaps[0]["intent"] == "sql_query"


def test_a_job_with_no_gaps_reports_none():
    from atlas.jobs.service import JobService

    assert JobService._gaps([DoneStep({"answer": "x"}), DoneStep(None)]) == []
