"""Hermetic tests for the JobWatcher worker (Phase D · §D.8).

Real DecisionEngine + JobDecisionRule over fakes for assets/reader/events. Proves:
read → match → decide → notify, fingerprint skip, reboot resume, config pickup, policy avoid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas.career.decision_rule import JobDecisionRule
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.workers.base import TickContext
from atlas.workers.job_watcher import JobWatcher


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def record(self, decision):
        self.rows.append(decision)
        return {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc)}


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


class _FakeAssets:
    def __init__(self, feeds: dict[str, list[dict[str, Any]]]) -> None:
        self._ids = {name: str(uuid.uuid4()) for name in feeds}
        self._by_id = {self._ids[name]: name for name in feeds}
        self._feeds = feeds

    def get_by_name(self, kind, name):
        aid = self._ids.get(name)
        return {"id": aid, "name": name} if aid else None

    def name_for(self, asset_id):
        return self._by_id[asset_id]


class _FakeReader:
    def __init__(self, assets: _FakeAssets) -> None:
        self._assets = assets

    def read(self, asset_id, asset_version=None, *, filename=None, force=False):
        name = self._assets.name_for(asset_id)
        posts = self._assets._feeds[name]
        return {"outcome": "ok", "postings": posts, "count": len(posts)}


class _FakePersonal:
    def __init__(self, skills: list[str]) -> None:
        self._skills = skills

    def skills(self, *, include_inferred=True):
        return [{"key": s.lower(), "value": {"skill": s}} for s in self._skills]


class _AvoidPolicy:
    def __init__(self, *terms: str, weight: float = -5.0) -> None:
        self._inf = [{"id": "pol-avoid", "terms": list(terms), "weight": weight}]

    def advice_influence(self, *, scope=None):
        return list(self._inf)


_POSTINGS = [
    {
        "id": "j1", "title": "Senior Python Engineer", "company": "Acme",
        "location": "Berlin", "skills": ["python", "django"], "salary": 120000,
        "url": "https://example.com/j1",
    },
    {
        "id": "j2", "title": "Rust Systems Engineer", "company": "OtherCo",
        "location": "Remote", "skills": ["rust"], "salary": 130000,
    },
]


def _engine(policy=None) -> DecisionEngine:
    reg = DecisionRuleRegistry()
    reg.register(JobDecisionRule())
    return DecisionEngine(_FakeDecisionRepo(), rules=reg, policy=policy)


def _worker(feeds, *, engine=None, events=None, personal=None):
    assets = _FakeAssets(feeds)
    return JobWatcher(
        assets=assets,
        postings_reader=_FakeReader(assets),
        decision_engine=engine or _engine(),
        personal=personal or _FakePersonal(["python", "django"]),
        events=events,
    )


def _ctx(config, state=None, *, version=1, inputs=None):
    return TickContext(
        worker_id="w1", mission_id=str(uuid.uuid4()), config=config,
        config_version=version, state=state or {}, inputs=inputs or [],
    )


_CFG = {
    "sources": ["feed-a"],
    "locations": ["berlin", "remote"],
    "skills": [],
    "min_salary": 0,
}


def test_full_tick_recommends_and_notifies():
    events = _FakeEvents()
    engine = _engine()
    worker = _worker({"feed-a": _POSTINGS}, engine=engine, events=events)
    result = worker.do_tick(_ctx(_CFG))
    assert engine._repo.rows
    assert any(t == "JobMatchRecommended" for t, _ in events.emitted)
    rec = next(p for t, p in events.emitted if t == "JobMatchRecommended")
    assert rec["posting"]["id"] == "j1"
    assert "Python" in result.note or "recommended" in result.note
    assert result.state["sources_fingerprint"]


def test_unchanged_feed_skips():
    worker = _worker({"feed-a": _POSTINGS})
    r1 = worker.do_tick(_ctx(_CFG))
    # Second tick with same state should skip (no new decision if fingerprint matches).
    # Need a shared engine to count decisions across ticks.
    events = _FakeEvents()
    engine = _engine()
    w = _worker({"feed-a": _POSTINGS}, engine=engine, events=events)
    r1 = w.do_tick(_ctx(_CFG))
    n1 = len(engine._repo.rows)
    r2 = w.do_tick(_ctx(_CFG, state=r1.state))
    assert len(engine._repo.rows) == n1
    assert r2.note == "" or "no change" in r2.note


def test_force_reruns():
    engine = _engine()
    w = _worker({"feed-a": _POSTINGS}, engine=engine)
    r1 = w.do_tick(_ctx(_CFG))
    w.do_tick(_ctx(_CFG, state=r1.state, inputs=[{"force": True}]))
    assert len(engine._repo.rows) == 2


def test_reboot_does_not_re_notify_same_match():
    events = _FakeEvents()
    w1 = _worker({"feed-a": _POSTINGS}, events=events)
    r1 = w1.do_tick(_ctx(_CFG))
    assert r1.state["seen_posting_ids"]
    events2 = _FakeEvents()
    w2 = _worker({"feed-a": _POSTINGS}, events=events2)
    w2.do_tick(_ctx(_CFG, state=r1.state, inputs=[{"force": True}]))
    assert [p for t, p in events2.emitted if t == "JobMatchRecommended"] == []


def test_config_version_pickup():
    w = _worker({"feed-a": _POSTINGS})
    result = w.do_tick(_ctx(_CFG, version=3))
    assert result.state["config_version"] == 3
    assert "config v3 picked up" in result.note


def test_idle_without_sources():
    events = _FakeEvents()
    engine = _engine()
    w = _worker({"feed-a": _POSTINGS}, engine=engine, events=events)
    result = w.do_tick(_ctx({"sources": []}))
    assert result.note == ""
    assert engine._repo.rows == []


def test_policy_avoid_company_holds():
    events = _FakeEvents()
    # Avoid Acme; personal skills only match Acme posting → hold, no notify.
    engine = _engine(policy=_AvoidPolicy("acme", weight=-5.0))
    w = _worker({"feed-a": _POSTINGS[:1]}, engine=engine, events=events)
    w.do_tick(_ctx(_CFG))
    assert [p for t, p in events.emitted if t == "JobMatchRecommended"] == []
    decision = engine._repo.rows[-1]
    # Either hold action_kind, or recommend with hold payload — avoid should make hold win.
    assert decision.action_kind in ("hold", "recommend")
    if decision.action_kind == "recommend":
        assert (decision.action.get("payload") or {}).get("kind") == "hold"
    else:
        assert decision.action_kind == "hold"
