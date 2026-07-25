"""OI-F3 System Introspection service + worker."""

from __future__ import annotations

from atlas.introspection.service import IntrospectionService
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.workers.base import TickContext
from atlas.workers.system_introspection import SystemIntrospectionWorker


def test_report_sections_and_reader_ranking():
    class _Knowledge:
        def list_findings(self, *, limit=200):
            return [
                {"status": "active", "maturity": "established", "domain": "markets"},
                {"status": "contested", "maturity": "candidate", "domain": "markets"},
                {"status": "active", "maturity": "candidate", "domain": "engineering"},
            ]

    class _Coverage:
        def summary(self):
            return {"overall": {"coverage_pct": 72.5, "assets_read": 10, "assets_total": 14}}

        def reader_failures(self):
            return [
                {"reader": "speech_to_text", "failed": 5, "unsupported": 1, "trouble": 6},
                {"reader": "pdf", "failed": 1, "unsupported": 0, "trouble": 1},
            ]

    class _Caps:
        def self_report_gaps(self):
            return {"summary": {"catalog_gaps": 2}, "catalog_gaps": ["x"]}

    class _Decisions:
        def list_gaps(self, *, limit=200):
            return [{"capability": "live_broker"}, {"capability": "cad_parser"}]

    class _Board:
        def snapshot(self):
            return {
                "finding_count": 1,
                "open_recommendations": 2,
                "recommendations": [{"title": "raise floor"}],
                "findings": [{"metric": "recall"}],
                "last_run": {"at": "2026-07-25"},
            }

    class _Arbiter:
        def snapshot(self):
            return {
                "total_inflight": 2,
                "global_max": 8,
                "inflight": {"m-costly": 1},
                "deferrals": {"m-costly": 4, "m-other": 1},
                "llm_units_in_window": {"m-costly": 12, "m-other": 2},
            }

    class _Policy:
        def list_rules(self, *, enabled=True, limit=200):
            return [
                {"id": "1", "rule": "forbid", "scope": "global", "name": "no live orders"},
                {"id": "2", "rule": "prefer", "scope": "global", "name": "prefer local"},
                {"id": "3", "rule": "limit", "scope": "mission:x", "name": "cap llm"},
            ]

    svc = IntrospectionService(
        knowledge=_Knowledge(),
        coverage=_Coverage(),
        capabilities=_Caps(),
        decisions=_Decisions(),
        improvement_board=_Board(),
        arbiter=_Arbiter(),
        policy=_Policy(),
    )
    out = svc.report()
    assert out["report_kind"] == "system_introspection"
    assert out["version"] == "f3.1"
    sections = out["sections"]
    assert sections["knowledge"]["findings_scanned"] == 3
    assert sections["uncertainty"]["contested"] == 1
    assert sections["uncertainty"]["uncertain_total"] >= 2
    assert sections["readers"]["ranked"][0]["reader"] == "speech_to_text"
    assert sections["missions"]["cost_ranked"][0]["mission_id"] == "m-costly"
    assert len(sections["policies"]["blocking"]) == 2
    assert sections["gaps"]["decision_gap_count"] == 2
    assert sections["improve_next"]["open_recommendations"] == 2
    assert "System Introspection Report" in out["narrative"]
    assert "speech_to_text" in out["narrative"]


def test_worker_fingerprints_and_journals():
    class _Intro:
        def __init__(self):
            self.calls = 0

        def report(self, *, limit=200):
            self.calls += 1
            return {
                "version": "f3.1",
                "narrative": "System Introspection Report\n  Findings known 1",
                "sections": {
                    "knowledge": {"findings_scanned": 1},
                    "uncertainty": {"uncertain_total": 0},
                    "gaps": {"decision_gap_count": 0},
                    "improve_next": {"open_recommendations": 0},
                },
            }

    class _OS:
        def __init__(self):
            self.journals = []

        def journal(self, **kw):
            self.journals.append(kw)
            return {"ok": True}

    intro = _Intro()
    os_ = _OS()
    worker = SystemIntrospectionWorker(introspection=intro, experience_os=os_)
    ctx = TickContext(
        mission_id="m1",
        worker_id="w1",
        config={},
        config_version=1,
        state={},
    )
    r1 = worker.do_tick(ctx)
    assert "introspection:" in (r1.note or "")
    assert len(os_.journals) == 1
    assert "system_introspection" in os_.journals[0]["tags"]

    ctx2 = TickContext(
        mission_id="m1",
        worker_id="w1",
        config={},
        config_version=1,
        state=dict(r1.state or {}),
    )
    r2 = worker.do_tick(ctx2)
    assert "unchanged" in (r2.note or "")
    assert len(os_.journals) == 1


def test_builtin_template_registered():
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    assert "system_introspection" in names
