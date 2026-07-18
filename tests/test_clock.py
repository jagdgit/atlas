"""Tests for the Clock / Time service (Phase 0 · ATLAS_OS_ROADMAP §5.7).

No live network: NTP behaviour is exercised by monkeypatching the SNTP query, so
these tests are deterministic and offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.services.base import SEVERITY_DEGRADED, SEVERITY_OK
from atlas.system.time import ClockService


def _clock(**kw) -> ClockService:
    kw.setdefault("ntp_enabled", False)
    return ClockService(**kw)


def test_now_utc_is_timezone_aware_utc():
    clock = _clock()
    now = clock.now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(None)


def test_monotonic_is_non_decreasing():
    clock = _clock()
    a = clock.monotonic()
    b = clock.monotonic()
    assert b >= a


def test_to_local_utc_is_identity_offset():
    clock = _clock(timezone_name="UTC")
    dt = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    assert clock.to_local(dt).utcoffset().total_seconds() == 0


def test_to_local_naive_is_assumed_utc():
    clock = _clock(timezone_name="UTC")
    naive = datetime(2026, 7, 18, 12, 0)
    local = clock.to_local(naive)
    assert local.tzinfo is not None
    assert local.hour == 12


def test_to_local_applies_named_timezone():
    # Kolkata is UTC+5:30 with no DST, so the offset is stable.
    clock = _clock(timezone_name="Asia/Kolkata")
    dt = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    local = clock.to_local(dt)
    assert local.utcoffset().total_seconds() == 5.5 * 3600


def test_unknown_timezone_falls_back_to_utc():
    clock = _clock(timezone_name="Not/AZone")
    dt = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    assert clock.to_local(dt).utcoffset().total_seconds() == 0


def test_iso_roundtrips():
    clock = _clock()
    dt = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    assert clock.iso(dt) == dt.isoformat()


def test_ntp_disabled_health_is_ok():
    clock = _clock(ntp_enabled=False)
    status = clock.check_drift()
    assert status.enabled is False
    assert status.synced is False
    health = clock.health_check()
    assert health.healthy is True
    assert health.level == SEVERITY_OK


def test_ntp_synced_small_offset_is_ok(monkeypatch):
    clock = ClockService(ntp_enabled=True, drift_warn_seconds=2.0, check_interval=0)
    monkeypatch.setattr(clock, "_query_offset", lambda server: 0.05)
    status = clock.check_drift()
    assert status.synced is True
    assert status.offset_seconds == 0.05
    assert clock.drift_seconds() == 0.05
    assert clock.health_check().level == SEVERITY_OK


def test_ntp_large_drift_degrades_but_stays_healthy(monkeypatch):
    clock = ClockService(ntp_enabled=True, drift_warn_seconds=2.0, check_interval=0)
    monkeypatch.setattr(clock, "_query_offset", lambda server: 9.9)
    clock.check_drift()
    health = clock.health_check()
    assert health.healthy is True  # never fail the system (R1/Q9)
    assert health.level == SEVERITY_DEGRADED


def test_ntp_unreachable_degrades_and_falls_back(monkeypatch):
    clock = ClockService(
        ntp_enabled=True,
        ntp_servers=["a.invalid", "b.invalid"],
        check_interval=0,
    )
    monkeypatch.setattr(clock, "_query_offset", lambda server: None)
    status = clock.check_drift()
    assert status.synced is False
    assert status.error is not None
    health = clock.health_check()
    assert health.healthy is True
    assert health.level == SEVERITY_DEGRADED


def test_query_offset_tries_each_server_until_one_answers(monkeypatch):
    clock = ClockService(
        ntp_enabled=True,
        ntp_servers=["dead.invalid", "good.invalid"],
        check_interval=0,
    )
    calls: list[str] = []

    def fake_query(server: str):
        calls.append(server)
        return 0.1 if server == "good.invalid" else None

    monkeypatch.setattr(clock, "_query_offset", fake_query)
    status = clock.check_drift()
    assert status.server == "good.invalid"
    assert calls == ["dead.invalid", "good.invalid"]


def test_start_without_ntp_spawns_no_thread():
    clock = _clock(ntp_enabled=False)
    clock.start()
    assert clock._thread is None  # noqa: SLF001 - white-box: no monitor thread
    clock.stop()


def test_status_as_dict_is_serializable():
    clock = _clock(ntp_enabled=False)
    clock.check_drift()
    data = clock.ntp_status().as_dict()
    assert set(data) == {
        "enabled", "synced", "offset_seconds", "server", "checked_at", "error"
    }
