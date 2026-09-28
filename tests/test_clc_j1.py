"""CLC.J1 — JobService investigation. No SMA/RSI mutation. Not R1-LIVE."""

from __future__ import annotations

from atlas.investment.clc_j1 import J1_OBJECTIVE, j1_constraints, start_j1
from atlas.jobs.planner import DecomposedStep
from atlas.jobs.service import PLAN_TASK
from tests.test_jobs import ScriptedRunner, _drive, _make


def test_j1_objective_forbids_orders_and_sma():
    assert "Do not mutate SMA/RSI" in J1_OBJECTIVE
    assert "Do not place BUY/SELL" in J1_OBJECTIVE
    c = j1_constraints()
    assert c["sma_rsi_untouched"] is True
    assert c["never_orders"] is True
    assert c["live_execution"] is False
    assert "no_further_test" in c["allowed_conclusions"]


def test_j1_creates_real_job_and_research_plan():
    steps = [
        DecomposedStep(
            "research",
            "research",
            {"objective": J1_OBJECTIVE},
            "Research E001 volume-acceleration failure.",
        )
    ]
    _repo, service, log = _make(steps, ScriptedRunner())
    out = start_j1(jobs=service)
    assert out["started"] is True
    assert out["job_id"]
    assert out["sma_rsi_untouched"] is True
    assert out["never_orders"] is True
    jid = out["job_id"]
    assert any(t == PLAN_TASK and j == jid for t, j, *_ in log)
    detail = service.job_detail(jid)
    assert "CLC.J1" in detail["job"].objective
    assert "SMA/RSI" in detail["job"].objective
    _drive(service, jid, log)
    after = service.job_detail(jid)
    assert after["progress"]["total"] >= 1
    intents = [s.intent for s in after["steps"]]
    assert "research" in intents
    meta = after["job"].metadata or {}
    assert meta.get("clc_j1") is True
    assert meta.get("never_orders") is True


def test_j1_conclude_from_fel_disk_no_further_test(tmp_path):
    """Disk-backed J1: overall worse + no better regime → no_further_test (not L5)."""
    import json
    from pathlib import Path

    from atlas.investment.clc_j1 import conclude_j1_from_fel_disk

    exp_dir = tmp_path / "investment" / "fel" / "experiments" / "india_equity_learner"
    exp_dir.mkdir(parents=True)
    lesson_dir = tmp_path / "investment" / "fel" / "lessons"
    lesson_dir.mkdir(parents=True)
    (exp_dir / "E001-buy_name-vol-accel.json").write_text(
        json.dumps(
            {
                "experiment_id": "E001-buy_name-vol-accel",
                "hypothesis_id": "H-buy_name-vol-accel",
                "result": "worse",
                "promotion": "never",
                "evaluation": {
                    "result": "worse",
                    "n_folds": 79,
                    "delta_economic": -0.000636,
                },
                "regimes": {
                    "high_momentum": {"evaluation": {"result": "no_significant"}},
                    "low_momentum": {"evaluation": {"result": "worse"}},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (lesson_dir / "L-E001-buy_name-vol-accel.json").write_text(
        json.dumps(
            {
                "id": "L-E001-buy_name-vol-accel",
                "statement": "Volume acceleration did not add economic information.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = conclude_j1_from_fel_disk(tmp_path, persist=True)
    assert out["ok"] is True
    assert out["conclusion"] == "no_further_test"
    assert out["sma_rsi_untouched"] is True
    assert out["never_orders"] is True
    assert out["not_l5"] is True
    assert "No further vol-accel" in out["narrative"]
    path = Path(out["path"])
    assert path.is_file()
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["conclusion"] == "no_further_test"
