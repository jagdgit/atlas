"""ARMF Phase D/E — archive lane opt-in + Ops summary first paint."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.ops.dashboard import OperationsDashboard
from atlas.system.host import HostMetrics


class _FakeApp:
    def status(self):
        return {
            "healthy": True,
            "degraded": False,
            "version": "test",
            "uptime_seconds": 30,
            "subsystem_counts": {"ok": 3, "degraded": 0, "failed": 0},
        }

    def container(self):  # pragma: no cover - unused in these tests
        return SimpleNamespace(resolve=lambda *_a, **_k: None)


def test_archive_lane_opt_in_when_max_ge_2():
    dash = OperationsDashboard(_FakeApp(), HostMetrics(check_internet=lambda: True))
    lane = dash._archive_lane({"max_archive_workers": 2, "archive_workers_running": 0})
    assert lane["opt_in_second_slot"] is True
    assert lane["max_slots"] == 2
    assert "opt-in ON" in lane["second_slot_note"]


def test_archive_lane_gated_at_one():
    dash = OperationsDashboard(_FakeApp(), HostMetrics(check_internet=lambda: True))
    lane = dash._archive_lane({"max_archive_workers": 1, "archive_workers_running": 1})
    assert lane["opt_in_second_slot"] is False
    assert lane["free"] == 0


def test_summary_first_paint_shape():
    dash = OperationsDashboard(_FakeApp(), HostMetrics(check_internet=lambda: True))
    out = dash.summary()
    assert out["version"] == "armf.e1"
    assert out["atlas"]["healthy"] is True
    assert out["startup"]["warming"] is True
    assert out["startup"]["message"]
    assert out["leave_running"]["ok_to_leave"] is True
    assert out["archive_lane"]["version"] == "armf.d1"


def test_startup_banner_clears_after_warmup():
    dash = OperationsDashboard(_FakeApp(), HostMetrics(check_internet=lambda: True))
    cold = dash._startup_banner({"uptime_seconds": 600})
    assert cold["warming"] is False
    assert cold["message"] is None
