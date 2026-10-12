"""Phase 8 / C8 — ops self-diagnosis learning is consumed by later registration."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.agent_kernel.ops_learning import (
    IDEMPOTENT_STATEMENT,
    accept_from_candidate,
    behavioural_delta_ops,
    belief_context_for_ops,
    list_candidates,
    note_identity_reuse,
    prove_c8_consume,
)
from atlas.scheduler.schedules import ScheduleService
from tests.test_schedules import FakeScheduleRepo, FakeTaskRepo


def _seed_candidate(data_dir: Path) -> Path:
    root = data_dir / "agent_kernel" / "learning_candidates"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "AK-phase7-fixture.json"
    path.write_text(
        json.dumps(
            {
                "kind": "ops_learning_candidate",
                "work_id": "AK-phase7-fixture",
                "statement": (
                    "Scheduled-task mass failures must be classified by error signature "
                    "before treating volume as learning."
                ),
                "evidence": {
                    "top_error": "no handler registered for task_type 'retention_prune'",
                    "row_count": 12,
                },
                "next_question": (
                    "Should retention_prune stay disabled until schedule identity "
                    "is uniquely indexed?"
                ),
                "provisional": True,
                "not_a_lesson": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_accept_ops_belief_from_candidate(tmp_path: Path):
    _seed_candidate(tmp_path)
    before = belief_context_for_ops(tmp_path)
    assert before["n_accepted"] == 0
    out = accept_from_candidate(tmp_path)
    assert out["ok"], out
    assert out["belief"]["statement"] == IDEMPOTENT_STATEMENT
    after = belief_context_for_ops(tmp_path)
    assert after["n_accepted"] == 1
    delta = behavioural_delta_ops(before, after)
    assert delta["changed"] is True


def test_ensure_schedule_cites_ops_belief_on_identity_reuse(tmp_path: Path):
    _seed_candidate(tmp_path)
    assert accept_from_candidate(tmp_path)["ok"]
    srepo = FakeScheduleRepo()
    trepo = FakeTaskRepo()
    svc = ScheduleService(srepo, trepo, data_dir=tmp_path)
    svc.bind_ops_learning(tmp_path)
    a = svc.ensure_schedule("host_guard_tick", 60, payload={})
    b = svc.ensure_schedule("host_guard_tick", 60, payload={})
    assert a.id == b.id
    receipts = list((tmp_path / "agent_kernel" / "ops_consume_receipts").glob("*.json"))
    assert receipts, "identity reuse must write a consume receipt"
    doc = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert doc["reused_existing"] is True
    assert doc["behaviour"] == "identity_first"
    assert doc["consumed_learning"]
    assert "idempotent" in doc["statement"].lower()


def test_prove_c8_helper(tmp_path: Path):
    _seed_candidate(tmp_path)
    svc = ScheduleService(FakeScheduleRepo(), FakeTaskRepo(), data_dir=tmp_path)
    svc.bind_ops_learning(tmp_path)
    proof = prove_c8_consume(tmp_path, schedule_service=svc)
    assert proof["ok"], proof
    assert proof["delta"]["changed"]
    assert proof["ensure"]["same_id"]
    assert proof["cite"]["cited"]


def test_list_candidates_reads_phase7_shape(tmp_path: Path):
    _seed_candidate(tmp_path)
    rows = list_candidates(tmp_path)
    assert len(rows) == 1
    assert rows[0]["_id"] == "AK-phase7-fixture"
