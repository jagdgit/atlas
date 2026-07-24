"""Daily Learning Governance Report (OI-MP3)."""

from __future__ import annotations

from atlas.governance import GovernanceReportService
from atlas.workers.base import TickContext
from atlas.workers.learning_governance import LearningGovernanceWorker


def test_daily_report_headline():
    class _K:
        def list_findings(self, *, limit=200):
            return [
                {"claim_type": "concept", "status": "active", "maturity": "verified"},
                {"claim_type": "concept", "status": "active", "maturity": "candidate"},
                {"claim_type": "entity", "status": "contested", "maturity": "verified"},
                {"claim_type": "relationship", "status": "active", "maturity": "verified"},
            ]

    class _L:
        def list_experiences(self, *, limit=200):
            return [
                {"tags": ["markets", "paper_trading"], "domain": "markets"},
                {"tags": ["code"], "domain": "engineering"},
            ]

    class _D:
        def list(self, *, limit=200):
            return [
                {"action_kind": "recommend"},
                {"action_kind": "capability_gap"},
            ]

        def list_gaps(self, *, limit=40):
            return [{"capability": "speech_to_text"}]

    svc = GovernanceReportService(knowledge=_K(), learning=_L(), decisions=_D())
    out = svc.daily()
    assert out["report_kind"] == "learning_governance"
    assert out["headline"]["new_concepts"] == 2
    assert out["headline"]["lessons_learned"] == 2
    assert out["headline"]["knowledge_conflicts"] == 1
    assert out["headline"]["capability_gaps"] == 1
    assert "Daily Learning Governance Report" in out["narrative"]
    assert out["version"] == "mp.3"


def test_governance_worker_idempotent():
    class _G:
        def daily(self, *, limit=200):
            return {
                "headline": {"new_concepts": 1, "lessons_learned": 0, "knowledge_conflicts": 0, "capability_gaps": 0},
                "narrative": "Daily Learning Governance Report\n  New concepts 1",
                "version": "mp.3",
            }

    worker = LearningGovernanceWorker(governance=_G())
    r1 = worker.do_tick(
        TickContext(worker_id="w", mission_id="m", config={}, config_version=1, state={})
    )
    assert "governance:" in r1.note
    r2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={},
            config_version=1,
            state=r1.state,
        )
    )
    assert "unchanged" in r2.note
