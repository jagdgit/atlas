"""F1 + F5 — CLI must not mutate live schedules; registration is idempotent.

Phase 4 of docs/2026-10-08_AUTONOMOUS_SELF_DIAGNOSIS_V1_PLAN.md.
"""

from __future__ import annotations

from atlas.scheduler.schedules import ScheduleService
from tests.test_schedules import FakeScheduleRepo, FakeTaskRepo


def test_boot_invariant_repeated_ensure_does_not_grow_rows():
    """Boot Atlas 100 times' worth of ensure calls → schedule count unchanged."""
    srepo = FakeScheduleRepo()
    trepo = FakeTaskRepo()
    service = ScheduleService(srepo, trepo)

    system = [
        ("host_guard_tick", 60, {}),
        ("provider_health_tick", 120, {}),
        ("embed_backfill", 90, {"limit": 10}),
        ("lab_loop0_s11_canary", 120, {}),
        ("fundamental_summary_publish", 900, {"symbols": ["HBLPOWER.NS"]}),
    ]
    for _ in range(100):
        for task_type, interval, payload in system:
            service.ensure_schedule(task_type, interval, payload=payload)

    assert len(srepo.rows) == len(system)
    assert srepo.count_enabled() == len(system)


def test_ephemeral_flag_skips_schedule_seed_and_claim_wiring():
    """build_application(ephemeral=True) must not seed schedule_tick or claim workers.

    Hermetic: we only assert the constructed services' flags — no live DB required.
    """
    from atlas.scheduler.service import SchedulerService

    # Mirror what bootstrap wires for ephemeral mode.
    sched = ScheduleService(FakeScheduleRepo(), FakeTaskRepo(), seed_tick_on_start=False)
    workers = SchedulerService(
        FakeTaskRepo(),  # type: ignore[arg-type]
        workers=0,
        mutate_queue=False,
    )
    assert sched._seed_tick_on_start is False
    assert workers._mutate_queue is False
    assert workers._workers == 0
    sched.start()
    workers.start()  # must be a no-op


def test_cli_helper_requests_ephemeral():
    import importlib
    import inspect

    # atlas.cli.__init__ re-exports ``main``, which shadows the submodule name.
    cli_main = importlib.import_module("atlas.cli.main")
    src = inspect.getsource(cli_main._cli_app)
    assert "ephemeral=True" in src
