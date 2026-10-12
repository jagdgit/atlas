"""Cognitive Loop C0 — nightly cognition runs off the mail path.

The timely evening digest skips WSO sync, belief revision, global mind, memory
distill, reflection and CWS so SMTP leaves on time. These tests pin the two halves
of the fix: the stages run in their own window after the digest is already out, and
the digest reads the resulting receipt instead of recomputing anything.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.investment.nightly_cognition import (
    build_receipt,
    format_nightly_cognition_section,
    load_receipt,
    persist_receipt,
)
from atlas.workers.base import TickContext
from atlas.workers.investor_reports import InvestorReportsWorker

_IST = ZoneInfo("Asia/Kolkata")
_DAY = "2026-10-06"
_LAB = "india_equity_learner"


class _Mailer:
    """Records how it was called; never sends."""

    def __init__(self, *, evening_sent: bool = True) -> None:
        self._evening_sent = evening_sent
        self.preview_calls: list[bool] = []

    def already_sent_morning(self, ist_date=None, *, laboratory_id=None) -> bool:
        return True

    def already_sent_evening(self, ist_date=None, *, laboratory_id=None) -> bool:
        return self._evening_sent

    def already_sent_hourly(self, *a, **kw) -> bool:
        return True

    def preview_evening(self, *, program_id, portfolio=None, timely=False, **kw):
        self.preview_calls.append(bool(timely))
        return {
            "subject": "s",
            "body": "b",
            "nightly_cognition": build_receipt(
                {
                    "world_states": [{"symbol": "CIPLA.NS"}],
                    "reflection": {"jis": 1},
                    "global_wso": {"version": "g"},
                },
                laboratory_id=_LAB,
                as_of_ist=_DAY,
            ),
        }


def _worker(tmp_path: Path, mailer: _Mailer) -> InvestorReportsWorker:
    return InvestorReportsWorker(
        mailer=mailer, data_dir=str(tmp_path), portfolio=None, market_reader=None
    )


def _due(worker, mailer, *, hour: int, evening_pending: bool = False) -> bool:
    return worker._nightly_cognition_due(
        cfg={},
        now_ist=datetime(2026, 10, 6, hour, 30, tzinfo=_IST),
        ist_date=_DAY,
        laboratory_id=_LAB,
        evening_pending=evening_pending,
    )


def test_nightly_waits_for_the_digest_to_be_sent(tmp_path: Path):
    mailer = _Mailer(evening_sent=False)
    worker = _worker(tmp_path, mailer)
    assert _due(worker, mailer, hour=20) is False


def test_nightly_never_shares_a_tick_with_an_unsent_evening_mail(tmp_path: Path):
    mailer = _Mailer(evening_sent=True)
    worker = _worker(tmp_path, mailer)
    assert _due(worker, mailer, hour=20, evening_pending=True) is False


def test_nightly_window_is_after_the_mail_window(tmp_path: Path):
    mailer = _Mailer(evening_sent=True)
    worker = _worker(tmp_path, mailer)
    assert _due(worker, mailer, hour=16) is False  # evening mail window
    assert _due(worker, mailer, hour=20) is True
    assert _due(worker, mailer, hour=23) is False


def test_nightly_runs_once_per_day(tmp_path: Path):
    mailer = _Mailer(evening_sent=True)
    worker = _worker(tmp_path, mailer)
    assert _due(worker, mailer, hour=20) is True

    result = worker._run_nightly_cognition(
        {}, program_id="market_intelligence", portfolio_key=_LAB, ist_date=_DAY
    )
    assert "nightly cognition" in str(result.note)
    # Stages are driven through the non-timely path.
    assert mailer.preview_calls == [False]

    receipt = load_receipt(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)
    assert receipt is not None
    assert receipt["ran"] is True
    assert "reflection" in receipt["stages_ran"]
    assert "global_mind" in receipt["stages_ran"]

    # A persisted receipt closes the window for the rest of the day.
    assert _due(worker, mailer, hour=21) is False


def test_nightly_can_be_killed_without_a_deploy(tmp_path: Path):
    mailer = _Mailer(evening_sent=True)
    worker = _worker(tmp_path, mailer)
    assert (
        worker._nightly_cognition_due(
            cfg={"nightly_cognition": False},
            now_ist=datetime(2026, 10, 6, 20, 30, tzinfo=_IST),
            ist_date=_DAY,
            laboratory_id=_LAB,
            evening_pending=False,
        )
        is False
    )


def test_failure_is_recorded_not_swallowed(tmp_path: Path):
    class Boom(_Mailer):
        def preview_evening(self, **kw):
            raise RuntimeError("llm lane busy")

    worker = _worker(tmp_path, Boom())
    worker._run_nightly_cognition(
        {}, program_id="market_intelligence", portfolio_key=_LAB, ist_date=_DAY
    )
    receipt = load_receipt(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)
    assert receipt["ran"] is False
    assert receipt["skipped_reason"] == "error:RuntimeError"


def test_digest_section_states_when_cognition_has_not_run():
    lines = format_nightly_cognition_section(None)
    assert any("not run yet today" in ln for ln in lines)


def test_tick_outside_all_windows_still_reports_idle(tmp_path: Path):
    mailer = _Mailer(evening_sent=True)
    worker = _worker(tmp_path, mailer)
    persist_receipt(
        tmp_path,
        build_receipt(None, laboratory_id=_LAB, as_of_ist=_DAY, skipped_reason="x"),
    )
    ctx = TickContext(
        worker_id="w1",
        mission_id="m1",
        config_version=1,
        state={},
        # Close every window explicitly. Reading the wall clock made this test mean
        # different things at different times of day: run inside the real morning
        # window it took the send_morning branch, which is not what it is checking.
        config={
            "portfolio_key": _LAB,
            # Non-zero: the worker reads these as `cfg.get(...) or <default>`, so a
            # 0 here is falsy and silently restores the real 07–10 window.
            "morning_hour_start": 23,
            "morning_hour_end": 23,
            "evening_hour_start": 25,
            "evening_minute_start": 0,
            "evening_hour_end": 25,
            "hourly_digests": False,
            "catch_up_until_hour": -1,
            "nightly_cognition_hour_start": 25,
            "nightly_cognition_hour_end": 25,
        },
        inputs=[],
    )
    result = worker.do_tick(ctx)
    assert result is not None
    assert (result.state or {}).get("skipped") == "outside_report_windows_ist"
