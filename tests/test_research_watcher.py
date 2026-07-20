"""Hermetic tests for the ResearchWatcher worker (Phase D · §D.7).

Wires a real DecisionEngine (+ ResearchDecisionRule) over fakes for ResearchService,
Knowledge, and events. Proves the full tick: research → promote → decide → notify,
plus topic-fingerprint skip, reboot resume, config-version pickup, and policy prefer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.research.decision_rule import ResearchDecisionRule
from atlas.workers.base import TickContext
from atlas.workers.research_watcher import ResearchWatcher


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def record(self, decision):
        self.rows.append(decision)
        return {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc)}

    def list(self, **kw):
        return [d.to_dict() for d in self.rows]


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


class _FakeKnowledge:
    def __init__(self) -> None:
        self.ingested: list[dict] = []

    def ingest_text(self, source, content, **kw):
        self.ingested.append({"source": source, "content": content, **kw})
        return {"document_id": f"d-{len(self.ingested)}", "status": "chunked",
                "chunks": 1, "deduped": False}


class _FakeResearch:
    """Returns a canned research result; records calls for assertions."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[dict] = []
        self._result = result or {
            "outcome": "ok",
            "objective": "soiling",
            "graph": {"sources": [], "claims": []},
            "claim": {"statement": "soiling is 0.3%/day", "confidence": "high"},
            "recommendations": [
                {"id": "s1", "title": "IEEE Soiling Study", "url": "https://ieeexplore.ieee.org/1",
                 "evidence_level": 3, "kind": "scholar",
                 "why": "Could fill the peer-reviewed gap."},
                {"id": "s2", "title": "Blog note", "url": "https://example.com/blog",
                 "evidence_level": 1, "kind": "web", "why": "Additional independent source."},
            ],
            "findings": [
                {"id": "f-high", "statement": "Soiling loss averages 0.3%/day",
                 "confidence": "high"},
            ],
            "gaps": {"gaps": [], "met": {}},
        }

    def research(self, objective, **kw):
        self.calls.append({"objective": objective, **kw})
        out = dict(self._result)
        out["objective"] = objective
        # Persist a claim file into the workspace so promote_research has something to ingest.
        ws = kw.get("workspace")
        if ws is not None and out.get("outcome") == "ok":
            ws.write_json("claims.json", [out["claim"]])
            ws.write_json("evidence.json", out.get("graph") or {})
            path = ws.document_path("paper1")
            path.write_text("Abstract\nMeasured soiling loss of 0.35 percent per day.\n" * 3)
        return out


class _PreferPolicy:
    def __init__(self, *terms: str, weight: float = 2.0) -> None:
        self._inf = [{"id": "pol-prefer", "terms": list(terms), "weight": weight}]

    def advice_influence(self, *, scope=None):
        return list(self._inf)


def _engine(policy=None) -> DecisionEngine:
    reg = DecisionRuleRegistry()
    reg.register(ResearchDecisionRule())
    return DecisionEngine(_FakeDecisionRepo(), rules=reg, policy=policy)


def _worker(tmp_path, *, research=None, engine=None, events=None, knowledge=None):
    return ResearchWatcher(
        research=research or _FakeResearch(),
        decision_engine=engine or _engine(),
        knowledge=knowledge or _FakeKnowledge(),
        events=events,
        data_dir=str(tmp_path),
    )


def _ctx(config, state=None, *, version=1, inputs=None, mission_id=None):
    return TickContext(
        worker_id="w1",
        mission_id=mission_id or str(uuid.uuid4()),
        config=config,
        config_version=version,
        state=state or {},
        inputs=inputs or [],
    )


_CFG = {
    "topic": "soiling loss rates",
    "max_iterations": 2,
    "per_query": 3,
    "alert_min_confidence": "medium",
}


def test_full_tick_promotes_decides_and_notifies(tmp_path):
    events = _FakeEvents()
    knowledge = _FakeKnowledge()
    engine = _engine()
    research = _FakeResearch()
    worker = _worker(tmp_path, research=research, engine=engine, events=events, knowledge=knowledge)

    result = worker.do_tick(_ctx(_CFG))
    assert research.calls and research.calls[0]["objective"] == "soiling loss rates"
    assert knowledge.ingested  # promote_research ingested workspace docs/claims
    assert engine._repo.rows  # decision journaled
    assert any(t == "ResearchFinding" for t, _ in events.emitted)
    assert any(t == "ResearchRecommendation" for t, _ in events.emitted)
    rec = next(p for t, p in events.emitted if t == "ResearchRecommendation")
    assert rec["source"]["id"] == "s1"  # peer-reviewed ranked first
    assert "IEEE" in result.note or "next:" in result.note
    assert result.state["topic_fingerprint"]


def test_unchanged_topic_skips_research(tmp_path):
    research = _FakeResearch()
    worker = _worker(tmp_path, research=research)
    r1 = worker.do_tick(_ctx(_CFG))
    assert len(research.calls) == 1
    r2 = worker.do_tick(_ctx(_CFG, state=r1.state))
    assert len(research.calls) == 1  # skipped
    assert r2.note == "" or "no change" in r2.note


def test_force_input_reruns(tmp_path):
    research = _FakeResearch()
    worker = _worker(tmp_path, research=research)
    r1 = worker.do_tick(_ctx(_CFG))
    worker.do_tick(_ctx(_CFG, state=r1.state, inputs=[{"force": True}]))
    assert len(research.calls) == 2


def test_reboot_resumes_seen_findings(tmp_path):
    events = _FakeEvents()
    research = _FakeResearch()
    w1 = _worker(tmp_path, research=research, events=events)
    r1 = w1.do_tick(_ctx(_CFG))
    assert r1.state["seen_finding_ids"]
    # Fresh worker + force re-run: same finding id must not re-notify.
    events2 = _FakeEvents()
    w2 = _worker(tmp_path, research=research, events=events2)
    w2.do_tick(_ctx(_CFG, state=r1.state, inputs=[{"force": True}]))
    findings = [p for t, p in events2.emitted if t == "ResearchFinding"]
    assert findings == []


def test_config_version_pickup(tmp_path):
    worker = _worker(tmp_path)
    result = worker.do_tick(_ctx(_CFG, version=4))
    assert result.state["config_version"] == 4
    assert "config v4 picked up" in result.note


def test_unavailable_emits_and_skips_promote(tmp_path):
    events = _FakeEvents()
    knowledge = _FakeKnowledge()
    research = _FakeResearch({"outcome": "unavailable", "reason": "no scholar"})
    worker = _worker(tmp_path, research=research, events=events, knowledge=knowledge)
    result = worker.do_tick(_ctx(_CFG))
    assert "unavailable" in result.note
    assert knowledge.ingested == []
    assert any(t == "ResearchUnavailable" for t, _ in events.emitted)


def test_idle_without_topic(tmp_path):
    research = _FakeResearch()
    worker = _worker(tmp_path, research=research)
    result = worker.do_tick(_ctx({"topic": ""}))
    assert result.note == ""
    assert research.calls == []


def test_policy_prefer_arbitrates_recommendation(tmp_path):
    # Prefer the weaker blog via policy so it outranks the peer-reviewed default winner.
    events = _FakeEvents()
    engine = _engine(policy=_PreferPolicy("blog", "example", weight=5.0))
    worker = _worker(tmp_path, engine=engine, events=events)
    worker.do_tick(_ctx(_CFG))
    rec = next(p for t, p in events.emitted if t == "ResearchRecommendation")
    assert rec["source"]["id"] == "s2"
