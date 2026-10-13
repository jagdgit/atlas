"""Per-lab tick admission ledger + ops-health stale-lab alert (2026-10-13 starvation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.investment import lab_ticks
from atlas.investment import ops_health as oh

IST = ZoneInfo("Asia/Kolkata")
DAY = "2026-10-13"
READY = {"status": "READY", "trading_date": DAY}
FNO, SWING = "india_fno_learner", "india_equity_learner"


def _at(hh: int, mm: int, day: int = 13) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=IST).astimezone(timezone.utc)


class _Mail:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> bool:
        self.sent.append((subject, body))
        return True


def _tick_labs(tmp: Path, start: datetime, end: datetime, labs=(FNO, SWING)) -> None:
    t = start
    while t <= end:
        for lab in labs:
            lab_ticks.record_admitted_tick(tmp, laboratory_id=lab, worker_id=f"w-{lab}", now=t)
        t += timedelta(minutes=5)


def _defer_labs(tmp: Path, start: datetime, end: datetime, labs=(FNO, SWING)) -> None:
    t = start
    while t <= end:
        for lab in labs:
            lab_ticks.record_deferred_tick(
                tmp, worker_id=f"w-{lab}", cause="host_pressure", reason="ram_free 2810MB < need 3072MB", now=t
            )
        t += timedelta(minutes=5)


def _ops(tmp: Path, at: datetime, mail: _Mail):
    return oh.ops_health_tick(tmp, READY, now=at, feed=None, sender=mail)


def test_counters_split_session_and_offhours(tmp_path: Path):
    lab_ticks.record_admitted_tick(tmp_path, laboratory_id=SWING, worker_id="w1", now=_at(2, 0))
    lab_ticks.record_admitted_tick(tmp_path, laboratory_id=SWING, worker_id="w1", now=_at(10, 0))
    lab_ticks.record_deferred_tick(tmp_path, worker_id="w1", cause="host_pressure", reason="x", now=_at(10, 5))
    lab_ticks.record_deferred_tick(tmp_path, worker_id="w1", cause="schedule", now=_at(20, 0))
    doc = lab_ticks.load_day(tmp_path, DAY)
    row = doc["labs"][SWING]
    assert row["admitted"] == 2 and row["in_session"] == 1
    assert row["last_in_session_at"] == _at(10, 0).isoformat()
    dfr = lab_ticks.deferrals_for_lab(doc, SWING)
    assert dfr["total"] == 2 and dfr["in_session"] == 1
    assert dfr["by_cause"] == {"host_pressure": 1, "schedule": 1}


def test_starved_labs_alert_p0_and_stay_unresolved_after_close(tmp_path: Path):
    _tick_labs(tmp_path, _at(9, 20), _at(11, 13))
    _defer_labs(tmp_path, _at(11, 15), _at(11, 35))
    mail = _Mail()
    _ops(tmp_path, _at(11, 36), mail)
    state = oh.load_state(tmp_path, DAY)
    for lab in (FNO, SWING):
        inc = state["incidents"][f"lab:{lab}:ticks"]
        assert inc["status"] == oh.STATUS_OPEN and inc["severity"] == oh.P0
    lab_mails = [s for s, _ in mail.sent if "admitted tick" in s or "admitted tick" in _]
    assert len(lab_mails) == 2
    assert any("host_pressure" in body for _, body in mail.sent)

    for hh, mm in ((15, 30), (15, 32), (15, 34), (16, 0)):
        _ops(tmp_path, _at(hh, mm), mail)
    state = oh.load_state(tmp_path, DAY)
    for lab in (FNO, SWING):
        inc = state["incidents"][f"lab:{lab}:ticks"]
        assert inc["status"] == oh.STATUS_UNRESOLVED
        assert inc["resolution"] == "market_window_ended_without_recovery"
    assert not any("RESOLVED" in s for s, _ in mail.sent)
    digest = "\n".join(oh.digest_lines(tmp_path, DAY))
    assert f"Lab ticks in session — {FNO}: admitted 23, deferred 5, last 11:10" in digest


def test_fresh_tick_after_open_verifies_recovery(tmp_path: Path):
    _tick_labs(tmp_path, _at(9, 20), _at(11, 13), labs=(FNO,))
    mail = _Mail()
    _ops(tmp_path, _at(11, 36), mail)
    _tick_labs(tmp_path, _at(11, 40), _at(11, 45), labs=(FNO,))
    _ops(tmp_path, _at(11, 46), mail)
    _ops(tmp_path, _at(11, 48), mail)
    inc = oh.load_state(tmp_path, DAY)["incidents"][f"lab:{FNO}:ticks"]
    assert inc["status"] == oh.STATUS_RECOVERED_VERIFIED
    assert inc["resolution"] == "admitted_tick_confirmed"


def test_healthy_labs_raise_nothing(tmp_path: Path):
    _tick_labs(tmp_path, _at(9, 20), _at(12, 0))
    out = _ops(tmp_path, _at(12, 2), _Mail())
    assert not any(k.startswith("lab:") for k in out["open_incidents"])


def test_lab_seen_yesterday_but_silent_today_is_flagged(tmp_path: Path):
    _tick_labs(tmp_path, _at(10, 0, day=12), _at(10, 10, day=12), labs=(SWING,))
    mail = _Mail()
    _ops(tmp_path, _at(9, 40), mail)
    inc = oh.load_state(tmp_path, DAY)["incidents"][f"lab:{SWING}:ticks"]
    assert inc["what"] == f"{SWING}: no admitted tick this session"


def test_no_check_before_0935_or_outside_session(tmp_path: Path):
    _tick_labs(tmp_path, _at(10, 0, day=12), _at(10, 10, day=12), labs=(SWING,))
    for at in (_at(9, 20), _at(18, 0)):
        out = _ops(tmp_path, at, _Mail())
        assert not any(k.startswith("lab:") for k in out["open_incidents"])
