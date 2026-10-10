"""Loop 0 — Operational Health (O1–O5): classify, recover, escalate, learn."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.investment import ops_health as oh

IST = ZoneInfo("Asia/Kolkata")
DAY = "2026-10-06"
READY = {"status": "READY", "trading_date": DAY}


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 10, 6, hh, mm, tzinfo=IST).astimezone(timezone.utc)


def _packs(tmp: Path, *, status: str, reason: str, at: datetime, n: int = 29) -> None:
    root = tmp / "investment" / "fno" / "packs"
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"SYM{i}_{DAY}.json").write_text(
            json.dumps({"underlying": f"SYM{i}", "status": status, "reason": reason, "as_of": at.isoformat()}),
            encoding="utf-8",
        )


def _nfo_state(tmp: Path, futures: str, options: str = "READY") -> None:
    path = tmp / "investment" / "zerodha" / "nfo_master_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "futures": {"state": futures, "ist_day": DAY, "reason": "fetch_error:RuntimeError"},
                "options": {"state": options, "ist_day": DAY},
            }
        ),
        encoding="utf-8",
    )


class _Feed:
    def __init__(self, tmp: Path, *, succeed: bool) -> None:
        self.tmp = tmp
        self.succeed = succeed
        self.calls = 0

    def refresh_nfo_masters(self):
        self.calls += 1
        fut = "READY" if self.succeed else "FAILED"
        _nfo_state(self.tmp, fut)
        return {"futures": {"state": fut}, "options": {"state": "READY"}}


class _Mail:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> bool:
        self.sent.append((subject, body))
        return True


def _run(tmp, health, at, feed, mail, **kw):
    return oh.ops_health_tick(tmp, health, now=at, feed=feed, sender=mail, **kw)


def test_todays_incident_recovers_three_times_then_emails_p0(tmp_path: Path):
    """2026-10-06: futures master empty all session, 29/29 packs expiry_missing, no alert."""
    _packs(tmp_path, status="NOT_READY", reason="expiry_missing", at=_at(9, 27))
    feed, mail = _Feed(tmp_path, succeed=False), _Mail()
    t = _at(9, 30)
    for _ in range(6):
        _run(tmp_path, READY, t, feed, mail)
        t += timedelta(minutes=2)
    assert feed.calls == 3, "recovery is bounded at three attempts"
    assert len(mail.sent) == 1
    subject, body = mail.sent[0]
    assert "P0" in subject and "F&O DATA PLANE" in subject
    for section in ("WHAT FAILED", "WHY", "IMPACT", "WHAT ATLAS TRIED", "CURRENT STATE", "WHAT YOU CAN DO"):
        assert section in body
    assert "Automatic recovery: EXHAUSTED" in body
    assert "Safety: No orders were submitted." in body
    assert "29/29 F&O packs NOT_READY" in body

    for _ in range(5):
        _run(tmp_path, READY, t, feed, mail)
        t += timedelta(minutes=2)
    assert len(mail.sent) == 1, "one alert per incident"
    state = oh.load_state(tmp_path, DAY)
    assert state["windows"][oh.FNO_LAB]["minutes"][oh.IDLE_INFRA] > 0
    assert oh.silent_degraded_windows(tmp_path, DAY) == []


def test_successful_recovery_closes_incident_and_records_lesson(tmp_path: Path):
    _packs(tmp_path, status="NOT_READY", reason="futures_master_missing", at=_at(9, 27))
    _nfo_state(tmp_path, "FAILED")
    feed, mail = _Feed(tmp_path, succeed=True), _Mail()
    _run(tmp_path, READY, _at(9, 30), feed, mail)
    assert feed.calls == 1
    _packs(tmp_path, status="READY", reason="ok", at=_at(9, 32))
    for m in (32, 34, 36):
        out = _run(tmp_path, READY, _at(9, m), feed, mail)
    assert out["fno_category"] == oh.OPERATING
    assert mail.sent == [], "recovered before escalation — nothing to tell the operator"
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:futures_master"]
    assert inc["status"] == "RESOLVED" and inc["recovery"] == "RECOVERED"
    rows = [json.loads(l) for l in (tmp_path / "investment" / "ops_health" / "experience.jsonl").read_text().splitlines()]
    assert rows[-1]["lesson"].startswith("An empty futures response following provider failure")
    assert rows[-1]["outcome"] == "automatic recovery confirmed"


def test_login_recovery_refreshes_masters_and_names_failed_dependency(tmp_path: Path):
    feed, mail = _Feed(tmp_path, succeed=False), _Mail()
    _run(tmp_path, {"status": "LOGIN_REQUIRED"}, _at(6, 30), feed, mail)
    out = _run(tmp_path, READY, _at(6, 40), feed, mail)
    assert feed.calls == 1
    assert out["fno_readiness"] == oh.FNO_DEGRADED
    state = oh.load_state(tmp_path, DAY)
    assert state["fno_readiness"]["failed"] == ["futures_master"]
    assert state["events"][-1]["event"] == "ZERODHA_LOGIN_RECOVERED"

    ok_feed = _Feed(tmp_path, succeed=True)
    _run(tmp_path, {"status": "LOGIN_REQUIRED"}, _at(6, 50), ok_feed, mail)
    out = _run(tmp_path, READY, _at(6, 52), ok_feed, mail)
    assert out["fno_readiness"] == oh.FNO_LAB_READY


def test_login_required_is_owned_by_the_mdph_email(tmp_path: Path):
    mail = _Mail()
    for m in range(0, 40, 2):
        _run(tmp_path, {"status": "LOGIN_REQUIRED"}, _at(9, 20) + timedelta(minutes=m), None, mail)
    assert mail.sent == []
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:zerodha_login"]
    assert inc["severity"] == oh.P0 and inc["alert_owner"] == "mdph_login_email"
    assert oh.silent_degraded_windows(tmp_path, DAY) == []


def test_capability_gap_is_p1_only_after_persisting(tmp_path: Path):
    _packs(tmp_path, status="NOT_READY", reason="atm_not_computable", at=_at(10, 0))
    _nfo_state(tmp_path, "READY")
    mail = _Mail()
    t = _at(10, 0)
    for _ in range(9):
        _packs(tmp_path, status="NOT_READY", reason="atm_not_computable", at=t)
        _run(tmp_path, READY, t, None, mail)
        t += timedelta(minutes=2)
    assert mail.sent == [], "P1 waits for persistence"
    for _ in range(3):
        _packs(tmp_path, status="NOT_READY", reason="atm_not_computable", at=t)
        _run(tmp_path, READY, t, None, mail)
        t += timedelta(minutes=2)
    assert len(mail.sent) == 1 and "P1" in mail.sent[0][0]
    assert oh.load_state(tmp_path, DAY)["incidents"]["fno:capability"]["category"] == oh.IDLE_CAPABILITY


def test_outside_window_is_genuine_idle(tmp_path: Path):
    out = _run(tmp_path, READY, _at(20, 0), None, _Mail())
    assert out["fno_category"] == oh.IDLE_GENUINE
    assert out["open_incidents"] == []


def test_paper_worker_outage_not_cleared_by_market_close(tmp_path: Path):
    """Window end with packs=0 must not claim the F&O worker recovered."""
    _nfo_state(tmp_path, "READY")
    mail = _Mail()
    # Open P0 during window with no packs (worker not ticking).
    t = _at(10, 20)
    for _ in range(3):
        _run(tmp_path, READY, t, None, mail)
        t += timedelta(minutes=2)
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:paper_worker"]
    assert inc["status"] == oh.STATUS_OPEN
    assert inc["category"] == oh.IDLE_WORKER

    # Market closed — finding disappears. Must stay unresolved, not "condition cleared".
    for hh in (15, 40), (15, 42), (15, 44), (16, 0):
        _run(tmp_path, READY, _at(*hh), None, mail)
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:paper_worker"]
    assert inc["status"] == oh.STATUS_UNRESOLVED
    assert inc["resolution"] == "market_window_ended_without_recovery"
    assert "fno:paper_worker" in oh.load_state(tmp_path, DAY)["open_incidents"]


def test_paper_worker_recovered_only_when_pack_written(tmp_path: Path):
    _nfo_state(tmp_path, "READY")
    mail = _Mail()
    resumes: list[int] = []

    def _resume():
        resumes.append(1)
        return {"ok": True, "phase5_stale": True, "pause_reason": "phase5:STALE:duplicate"}

    t = _at(10, 20)
    for _ in range(2):
        oh.ops_health_tick(
            tmp_path, READY, now=t, feed=None, sender=mail, resume_paper_worker=_resume
        )
        t += timedelta(minutes=2)
    assert resumes, "worker resume binder should be invoked"
    # Still no packs — not verified yet.
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:paper_worker"]
    assert inc["recovery"] == "RECOVERED_PENDING_CONFIRM"
    # Pack appears → verified.
    _packs(tmp_path, status="READY", reason="ok", at=_at(10, 30), n=1)
    out = oh.ops_health_tick(
        tmp_path, READY, now=_at(10, 30), feed=None, sender=mail, resume_paper_worker=_resume
    )
    assert out["fno_category"] == oh.OPERATING
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:paper_worker"]
    assert inc["status"] == oh.STATUS_RECOVERED_VERIFIED
    assert "fno:paper_worker" not in oh.load_state(tmp_path, DAY)["open_incidents"]


def _pipeline(tmp: Path, day: str, counts: dict, rows: list) -> None:
    root = tmp / "investment" / "decisions" / "pipeline" / oh.EQUITY_LAB
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{day}.json").write_text(json.dumps({"counts": counts, "rows": rows}), encoding="utf-8")


def test_systemic_fundamentals_block_is_alerted_never_weakened(tmp_path: Path):
    rows = [
        {"symbol": s, "final": "plc_a_incomplete", "research_status": "fundamentals_incomplete"}
        for s in ("ITC.NS", "DRREDDY.NS", "ICICIGI.NS", "INDHOTEL.NS")
    ]
    counts = {"plc_a_incomplete": 4, "research_hold": 1, "engine_hold": 28}
    _pipeline(tmp_path, "2026-10-05", {"plc_a_incomplete": 4, "engine_hold": 29}, rows)
    _pipeline(tmp_path, DAY, counts, rows)
    found = oh.assess_systemic_blocks(tmp_path, day=DAY)["findings"]
    assert [f["key"] for f in found] == ["equity:systemic:fundamentals_incomplete"]
    assert "80%" in found[0]["what"] and "No gate change" in found[0]["actions"][0]

    mail = _Mail()
    t = _at(15, 35)
    for _ in range(12):
        _run(tmp_path, READY, t, None, mail)
        t += timedelta(minutes=2)
    assert len(mail.sent) == 1 and "EQUITY SAFETY GATES" in mail.sent[0][0]


def test_single_session_block_is_only_recorded(tmp_path: Path):
    rows = [{"symbol": "ITC.NS", "final": "plc_a_incomplete"}]
    _pipeline(tmp_path, "2026-10-05", {"plc_a_incomplete": 0, "authorized_buy": 4}, [])
    _pipeline(tmp_path, DAY, {"plc_a_incomplete": 4, "research_hold": 1}, rows * 4)
    assert oh.assess_systemic_blocks(tmp_path, day=DAY)["findings"] == []


def test_permanent_task_failures_surface_as_category_e(tmp_path: Path):
    for i in range(3):
        oh.record_task_failure(
            tmp_path, task_type="worker_tick:abc", task_id=f"t{i}",
            error="TypeError: Object of type set is not JSON serializable", now=_at(10, i),
        )
    mail = _Mail()
    t = _at(10, 5)
    for _ in range(12):
        _run(tmp_path, {"status": "READY"}, t, None, mail)
        t += timedelta(minutes=2)
    inc = oh.load_state(tmp_path, DAY)["incidents"]["ops:scheduler_failures"]
    assert inc["category"] == oh.IDLE_WORKER
    assert any("WORKERS / SCHEDULER" in s for s, _ in mail.sent)


def test_digest_lists_incidents_and_flags_silent_degradation(tmp_path: Path):
    _packs(tmp_path, status="NOT_READY", reason="expiry_missing", at=_at(9, 27))
    feed = _Feed(tmp_path, succeed=False)
    t = _at(9, 30)
    for _ in range(12):
        oh.ops_health_tick(tmp_path, READY, now=t, feed=feed, sender=None, email=False)
        t += timedelta(minutes=2)
    lines = oh.digest_lines(tmp_path, DAY)
    assert lines[0] == "OPERATIONAL HEALTH (Loop 0)"
    assert any("Futures master" in line for line in lines)
    assert oh.silent_degraded_windows(tmp_path, DAY) == ["fno:futures_master"]
    assert any("ACCEPTANCE VIOLATION" in line for line in lines)


def test_tick_never_raises(tmp_path: Path):
    class _Boom:
        def refresh_nfo_masters(self):
            raise RuntimeError("kite down")

    _packs(tmp_path, status="NOT_READY", reason="expiry_missing", at=_at(9, 27))
    out = oh.ops_health_tick(tmp_path, READY, now=_at(9, 30), feed=_Boom(), sender=_Mail())
    assert out["ok"] is True
    inc = oh.load_state(tmp_path, DAY)["incidents"]["fno:futures_master"]
    assert inc["attempts"][0]["result"].startswith("FAILED")


def test_scheduler_records_permanent_failures_only_when_wired(tmp_path: Path):
    from atlas.scheduler.handlers import HandlerRegistry
    from atlas.scheduler.service import SchedulerService
    from tests.test_scheduler import FakeRepo, _task

    handlers = HandlerRegistry()
    handlers.register("worker_tick", lambda p: (_ for _ in ()).throw(TypeError("set")))
    task = _task(task_type="worker_tick", payload={"worker_id": "w-1"}, retry_count=3, max_retries=3)

    SchedulerService(FakeRepo(), handlers, events=None)._run_task(dict(task), "w")
    assert not (tmp_path / "investment" / "ops_health" / "task_failures.jsonl").exists()

    wired = SchedulerService(FakeRepo(), handlers, events=None, failure_data_dir=str(tmp_path))
    wired._run_task(dict(task), "w")
    rows = oh.task_failures_for_day(tmp_path, datetime.now(IST).date().isoformat())
    assert [r["task_type"] for r in rows] == ["worker_tick:w-1"]


def test_checkpoint_state_with_sets_serializes(monkeypatch):
    from atlas.repositories.recovery_repo import CheckpointRepository

    captured = {}

    def _fetch_one(self, sql, params):
        captured["state"] = params[3].obj
        return {}

    monkeypatch.setattr(CheckpointRepository, "fetch_one", _fetch_one)
    repo = CheckpointRepository.__new__(CheckpointRepository)
    repo.save("worker", "w1", {"seen": {"b", "a"}, "frozen": frozenset({"x"}), "nested": {"s": {1}}})
    assert captured["state"] == {"seen": ["a", "b"], "frozen": ["x"], "nested": {"s": [1]}}
    json.dumps(captured["state"])
