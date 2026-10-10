"""P4 — resume_paused_paper_lab allowlist."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.workers.lifecycle import resume_paused_paper_lab


class _FakeWorkers:
    def __init__(self, workers):
        self.workers = workers
        self.resumed = []

    def list_workers(self, status=None, limit=200):
        out = self.workers
        if status:
            out = [w for w in out if w.status == status]
        return out[:limit]

    def resume(self, worker_id, reason=""):
        self.resumed.append((str(worker_id), reason))
        for w in self.workers:
            if str(w.id) == str(worker_id):
                w.status = "running"
                return w
        raise KeyError(worker_id)


def test_resume_phase5_stale_fno():
    w = SimpleNamespace(
        id="d6c9a9fc-8145-444a-85f7-9c25c81e126b",
        type="paper_trading",
        status="paused",
        schedule_id="2da6e972-84c6-4b5e-ae9f-1246613ed646",
        mission_id="m-fno",
        metadata={"portfolio_key": "india_fno_learner"},
    )
    mgr = _FakeWorkers([w])
    out = resume_paused_paper_lab(
        workers=mgr,
        laboratory_id="india_fno_learner",
        journal_rows=[
            {"action": "worker_paused", "reason": "phase5:STALE:duplicate role"}
        ],
    )
    assert out["ok"] is True
    assert out["status"] == "running"
    assert mgr.resumed


def test_refuse_non_phase5_pause():
    w = SimpleNamespace(
        id="w1",
        type="paper_trading",
        status="paused",
        schedule_id="s1",
        mission_id="m1",
        metadata={"portfolio_key": "india_fno_learner"},
    )
    mgr = _FakeWorkers([w])
    out = resume_paused_paper_lab(
        workers=mgr,
        laboratory_id="india_fno_learner",
        journal_rows=[{"action": "worker_paused", "reason": "operator:manual"}],
    )
    assert out["ok"] is False
    assert out["error"] == "pause_reason_not_phase5_stale"
    assert mgr.resumed == []


def test_refuse_unknown_lab():
    out = resume_paused_paper_lab(workers=_FakeWorkers([]), laboratory_id="random_lab")
    assert out["ok"] is False
    assert out["error"] == "laboratory_not_allowed"
