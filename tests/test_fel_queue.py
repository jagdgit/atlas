"""FEL.C — tiny experiment queue + BATCH dispatch (wraps existing runners)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.investment.fel.experiments.dispatch import process_one
from atlas.investment.fel.experiments.store import persist_experiment
from atlas.investment.fel.queue import (
    claim_next,
    enqueue,
    get_item,
    list_items,
    recover_stale,
)
from atlas.workers.base import TickContext
from atlas.workers.fel_experiment import FelExperimentWorker


def test_enqueue_idempotent_while_queued(tmp_path):
    a = enqueue(tmp_path, kind="probe", experiment_id="E-dup")
    b = enqueue(tmp_path, kind="probe", experiment_id="E-dup")
    assert a["created_at"] == b["created_at"]
    assert len(list_items(tmp_path)) == 1


def test_one_item_per_process_one(tmp_path):
    enqueue(tmp_path, kind="probe", experiment_id="E-a")
    enqueue(tmp_path, kind="probe", experiment_id="E-b")
    n = {"n": 0}

    def probe(item, data_dir):
        n["n"] += 1
        return {
            "experiment_id": item["experiment_id"],
            "result": "no_significant",
            "promotion": "never",
        }

    process_one(str(tmp_path), handlers={"probe": probe})
    assert n["n"] == 1
    assert get_item(tmp_path, "E-a")["status"] == "COMPLETED"
    assert get_item(tmp_path, "E-b")["status"] == "QUEUED"


def test_enqueue_claim_complete(tmp_path):
    enqueue(tmp_path, kind="probe", experiment_id="E-probe")

    def probe(item, data_dir):
        return {
            "experiment_id": item["experiment_id"],
            "result": "no_significant",
            "reason": "probe",
            "promotion": "never",
            "hypothesis_id": "H-probe",
        }

    out = process_one(str(tmp_path), handlers={"probe": probe})
    assert out["status"] == "COMPLETED"
    row = get_item(tmp_path, "E-probe")
    assert row["status"] == "COMPLETED"
    assert row["result_summary"]["result"] == "no_significant"
    assert row["result_summary"]["promotion"] == "never"
    idle = process_one(str(tmp_path), handlers={"probe": probe})
    assert idle["idle"] is True
    assert idle["reason"] == "empty_queue"


def test_unknown_kind_blocked(tmp_path):
    enqueue(tmp_path, kind="nope", experiment_id="E-nope")
    out = process_one(str(tmp_path))
    assert out["status"] == "BLOCKED"
    assert get_item(tmp_path, "E-nope")["status"] == "BLOCKED"


def test_handler_crash_failed(tmp_path):
    enqueue(tmp_path, kind="boom", experiment_id="E-boom")

    def boom(item, data_dir):
        raise RuntimeError("nope")

    out = process_one(str(tmp_path), handlers={"boom": boom})
    assert out["status"] == "FAILED"
    assert "RuntimeError" in (get_item(tmp_path, "E-boom")["error"] or "")


def test_failed_can_be_requeued(tmp_path):
    enqueue(tmp_path, kind="boom", experiment_id="E-retry")

    def boom(item, data_dir):
        raise RuntimeError("nope")

    process_one(str(tmp_path), handlers={"boom": boom})
    assert get_item(tmp_path, "E-retry")["status"] == "FAILED"

    enqueue(tmp_path, kind="probe", experiment_id="E-retry")

    def probe(item, data_dir):
        return {
            "experiment_id": item["experiment_id"],
            "result": "no_significant",
            "promotion": "never",
        }

    out = process_one(str(tmp_path), handlers={"probe": probe})
    assert out["status"] == "COMPLETED"
    assert get_item(tmp_path, "E-retry")["status"] == "COMPLETED"


def test_stale_running_recovered_to_queued(tmp_path):
    enqueue(tmp_path, kind="probe", experiment_id="E-stale")
    claimed = claim_next(tmp_path)
    assert claimed["status"] == "RUNNING"
    claimed["claimed_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    from atlas.investment.fel.queue import _write, item_path

    _write(item_path(tmp_path, "E-stale"), claimed)
    n = recover_stale(tmp_path, stale_seconds=60)
    assert n == 1
    assert get_item(tmp_path, "E-stale")["status"] == "QUEUED"


def test_completed_skip_if_complete_does_not_requeue(tmp_path):
    persist_experiment(
        tmp_path,
        {
            "experiment_id": "E001-buy_name-vol-accel",
            "laboratory_id": "india_equity_learner",
            "result": "worse",
            "promotion": "never",
        },
    )
    enqueue(
        tmp_path,
        kind="e001",
        experiment_id="E001-buy_name-vol-accel",
        skip_if_complete=True,
    )
    process_one(str(tmp_path))
    assert get_item(tmp_path, "E001-buy_name-vol-accel")["status"] == "COMPLETED"
    again = enqueue(
        tmp_path,
        kind="e001",
        experiment_id="E001-buy_name-vol-accel",
        skip_if_complete=True,
    )
    assert again["status"] == "COMPLETED"
    idle = process_one(str(tmp_path))
    assert idle["idle"] is True


def test_e001_skip_if_already_complete(tmp_path):
    persist_experiment(
        tmp_path,
        {
            "experiment_id": "E001-buy_name-vol-accel",
            "laboratory_id": "india_equity_learner",
            "result": "worse",
            "reason": "already ran",
            "promotion": "never",
            "hypothesis_id": "H-buy_name-vol-accel",
            "belief": {"status": "worse"},
        },
    )
    enqueue(
        tmp_path,
        kind="e001",
        experiment_id="E001-buy_name-vol-accel",
        skip_if_complete=True,
    )
    out = process_one(str(tmp_path))
    assert out["status"] == "COMPLETED"
    assert out["summary"]["skipped"] is True
    assert out["summary"]["result"] == "worse"


def test_worker_yields_during_rth(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "atlas.investment.yahoo_fundamentals.yahoo_background_should_yield_to_live",
        lambda **k: True,
    )
    enqueue(tmp_path, kind="probe", experiment_id="E-rth")
    w = FelExperimentWorker(data_dir=str(tmp_path), allow_rth=False, seed_e001=False)
    result = w.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"seed_e001": False},
            config_version=1,
            state={},
        )
    )
    assert "RTH" in result.note
    assert get_item(tmp_path, "E-rth")["status"] == "QUEUED"


def test_worker_runs_one_queued_item(tmp_path):
    enqueue(tmp_path, kind="probe", experiment_id="E-tick")

    def probe(item, data_dir):
        return {
            "experiment_id": item["experiment_id"],
            "result": "conditional",
            "reason": "ok",
            "promotion": "candidate",
        }

    import atlas.investment.fel.experiments.dispatch as disp

    orig = disp.DEFAULT_HANDLERS
    disp.DEFAULT_HANDLERS = {**orig, "probe": probe}
    try:
        w = FelExperimentWorker(data_dir=str(tmp_path), allow_rth=True, seed_e001=False)
        result = w.do_tick(
            TickContext(
                worker_id="w",
                mission_id="m",
                config={"allow_rth": True, "seed_e001": False},
                config_version=1,
                state={},
            )
        )
    finally:
        disp.DEFAULT_HANDLERS = orig
    assert "COMPLETED" in result.note
    assert get_item(tmp_path, "E-tick")["status"] == "COMPLETED"


def test_worker_skip_complete_during_rth(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "atlas.investment.yahoo_fundamentals.yahoo_background_should_yield_to_live",
        lambda **k: True,
    )
    persist_experiment(
        tmp_path,
        {
            "experiment_id": "E001-buy_name-vol-accel",
            "laboratory_id": "india_equity_learner",
            "result": "worse",
            "promotion": "never",
            "belief": {"status": "worse"},
        },
    )
    w = FelExperimentWorker(data_dir=str(tmp_path), allow_rth=False, seed_e001=True)
    result = w.do_tick(
        TickContext(worker_id="w", mission_id="m", config={}, config_version=1, state={})
    )
    assert "COMPLETED" in result.note
    assert "skip" in result.note
    row = get_item(tmp_path, "E001-buy_name-vol-accel")
    assert row["status"] == "COMPLETED"
    again = w.do_tick(
        TickContext(worker_id="w", mission_id="m", config={}, config_version=1, state={})
    )
    assert "empty_queue" in again.note


def test_batch_profile():
    from atlas.core.resources.work_profile import SERVICE_BATCH
    from atlas.missions.templates.resources import resources_for

    assert resources_for("fel_experiment_runner").service_class == SERVICE_BATCH
