"""Tests for Stage 3.2c Resource Manager (profiles, caps, detect→slow)."""

from __future__ import annotations

from atlas.core.resources import ResourceManager, get_profile, read_snapshot
from atlas.core.resources.manager import PoolRecommendation
from atlas.core.resources.monitor import SystemSnapshot


def test_profiles_exist():
    assert get_profile("balanced").name == "balanced"
    assert get_profile("overnight").worker_bonus == 2
    assert get_profile("unknown").name == "balanced"


def test_recommend_respects_hard_cap():
    rm = ResourceManager(
        profile="overnight",
        max_worker_threads=4,
        max_download_workers=4,
        max_reader_workers=4,
        max_extract_workers=2,
        llm_max_concurrency=1,
    )
    rec = rm.recommend_pool_sizes()
    assert isinstance(rec, PoolRecommendation)
    assert rec.global_max == 4
    assert rec.acquire_workers <= 4
    assert rec.extract_workers <= 1  # LLM lane
    # Overnight bonus cannot exceed hard max
    assert rec.download_workers <= 4


def test_posture_is_honest():
    rm = ResourceManager(profile="balanced", max_worker_threads=4)
    posture = rm.posture()
    assert posture["caps_enforced"] is True
    assert "message" in posture
    assert "thermal" in posture["message"]
    assert posture["power_monitored"] is False


def test_throttle_on_high_load(monkeypatch):
    rm = ResourceManager(
        profile="balanced",
        max_worker_threads=4,
        max_download_workers=4,
        max_reader_workers=4,
        max_extract_workers=2,
        llm_max_concurrency=2,
    )

    def fake_snap(_logger=None):
        return SystemSnapshot(
            load_1m=16.0,
            cpu_count=4,
            load_pressure=4.0,
            ram_used_fraction=0.5,
            thermal_monitored=False,
            power_monitored=False,
            notes=["thermal sensors not monitored", "power/battery not monitored"],
        )

    monkeypatch.setattr("atlas.core.resources.manager.read_snapshot", fake_snap)
    rec = rm.recommend_pool_sizes()
    assert rec.throttled is True
    assert rec.acquire_workers == 1
    assert rec.extract_workers == 1
    assert "load" in rec.throttle_reason.lower() or "pressure" in rec.throttle_reason.lower()


def test_throttle_on_thermal(monkeypatch):
    rm = ResourceManager(profile="maximum", max_worker_threads=4)

    def fake_snap(_logger=None):
        return SystemSnapshot(
            load_1m=1.0,
            cpu_count=8,
            load_pressure=0.12,
            ram_used_fraction=0.4,
            thermal_c=90.0,
            thermal_monitored=True,
            power_monitored=False,
            notes=["power/battery not monitored"],
        )

    monkeypatch.setattr("atlas.core.resources.manager.read_snapshot", fake_snap)
    rec = rm.recommend_pool_sizes()
    assert rec.throttled is True
    assert "thermal" in rec.throttle_reason.lower()


def test_request_release_never_fails_when_full():
    rm = ResourceManager(profile="conservative", max_worker_threads=2)
    t1, g1 = rm.request(workers=2, kind="acquire")
    assert g1 >= 1
    t2, g2 = rm.request(workers=2, kind="acquire")
    assert g2 >= 1  # still grants ≥1 — queue/slow, don't fail
    rm.release(t1)
    rm.release(t2)


def test_read_snapshot_returns_object():
    snap = read_snapshot()
    assert isinstance(snap, SystemSnapshot)
    assert isinstance(snap.notes, list)
