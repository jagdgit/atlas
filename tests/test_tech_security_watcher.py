"""Hermetic tests for TechSecurityWatcher (Phase D · §D.9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.watch.decision_rule import (
    MISSION_TYPE_SECURITY,
    MISSION_TYPE_TECHNOLOGY,
    AdvisoryDecisionRule,
)
from atlas.workers.base import TickContext
from atlas.workers.tech_security import TechSecurityWatcher


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
        self._ids = {n: str(uuid.uuid4()) for n in feeds}
        self._by_id = {self._ids[n]: n for n in feeds}
        self._feeds = feeds

    def get_by_name(self, kind, name):
        aid = self._ids.get(name)
        return {"id": aid, "name": name} if aid else None

    def name_for(self, asset_id):
        return self._by_id[asset_id]


class _FakeReader:
    def __init__(self, assets: _FakeAssets) -> None:
        self._assets = assets

    def read(self, asset_id, **kw):
        name = self._assets.name_for(asset_id)
        items = self._assets._feeds[name]
        return {"outcome": "ok", "advisories": items, "count": len(items)}


class _AvoidPolicy:
    def __init__(self, *terms, weight=-5.0):
        self._inf = [{"id": "pol", "terms": list(terms), "weight": weight}]

    def advice_influence(self, *, scope=None):
        return list(self._inf)


_FEED = [
    {
        "id": "CVE-9", "title": "Critical RCE in openssl", "severity": "critical",
        "kind": "cve", "package": "openssl", "packages": ["openssl"],
    },
    {
        "id": "BRK-9", "title": "Breaking change in fastapi", "severity": "high",
        "kind": "breaking_change", "package": "fastapi", "packages": ["fastapi"],
    },
]


def _engine(policy=None) -> DecisionEngine:
    reg = DecisionRuleRegistry()
    reg.register(AdvisoryDecisionRule(MISSION_TYPE_TECHNOLOGY))
    reg.register(AdvisoryDecisionRule(MISSION_TYPE_SECURITY))
    return DecisionEngine(_FakeDecisionRepo(), rules=reg, policy=policy)


def _worker(feeds, *, engine=None, events=None):
    assets = _FakeAssets(feeds)
    return TechSecurityWatcher(
        assets=assets,
        advisory_reader=_FakeReader(assets),
        decision_engine=engine or _engine(),
        events=events,
    )


def _ctx(config, state=None, *, version=1, inputs=None):
    return TickContext(
        worker_id="w1", mission_id=str(uuid.uuid4()), config=config,
        config_version=version, state=state or {}, inputs=inputs or [],
    )


def test_technology_mode_recommends_breaking():
    events = _FakeEvents()
    engine = _engine()
    # Focus only fastapi so the CVE (openssl) is filtered out; technology mode still notifies.
    w = _worker({"f1": _FEED}, engine=engine, events=events)
    result = w.do_tick(_ctx({
        "sources": ["f1"], "mode": "technology", "technologies": ["fastapi"],
        "severity_floor": "medium",
    }))
    assert any(t == "TechnologyAdvisoryRecommended" for t, _ in events.emitted)
    rec = next(p for t, p in events.emitted if t == "TechnologyAdvisoryRecommended")
    assert rec["advisory"]["id"] == "BRK-9"
    assert "fastapi" in result.note.lower() or "recommended" in result.note
    assert engine._repo.rows[-1].mission_type == "technology_watch"


def test_security_mode_recommends_cve():
    events = _FakeEvents()
    engine = _engine()
    w = _worker({"f1": _FEED}, engine=engine, events=events)
    w.do_tick(_ctx({
        "sources": ["f1"], "mode": "security", "components": ["openssl", "fastapi"],
        "severity_floor": "high",
    }))
    assert any(t == "SecurityAdvisoryRecommended" for t, _ in events.emitted)
    rec = next(p for t, p in events.emitted if t == "SecurityAdvisoryRecommended")
    assert rec["advisory"]["id"] == "CVE-9"
    assert engine._repo.rows[-1].mission_type == "security_monitoring"


def test_fingerprint_skip_and_force():
    engine = _engine()
    w = _worker({"f1": _FEED}, engine=engine)
    cfg = {"sources": ["f1"], "mode": "technology", "technologies": ["fastapi"],
           "severity_floor": "medium"}
    r1 = w.do_tick(_ctx(cfg))
    n = len(engine._repo.rows)
    r2 = w.do_tick(_ctx(cfg, state=r1.state))
    assert len(engine._repo.rows) == n
    assert r2.note == "" or "no change" in r2.note
    w.do_tick(_ctx(cfg, state=r1.state, inputs=[{"force": True}]))
    assert len(engine._repo.rows) == n + 1


def test_reboot_no_renotify():
    events = _FakeEvents()
    w1 = _worker({"f1": _FEED}, events=events)
    cfg = {"sources": ["f1"], "mode": "security", "components": ["openssl"],
           "severity_floor": "high"}
    r1 = w1.do_tick(_ctx(cfg))
    events2 = _FakeEvents()
    _worker({"f1": _FEED}, events=events2).do_tick(
        _ctx(cfg, state=r1.state, inputs=[{"force": True}])
    )
    assert [p for t, p in events2.emitted if "Recommended" in t] == []


def test_config_pickup_and_idle():
    w = _worker({"f1": _FEED})
    r = w.do_tick(_ctx({
        "sources": ["f1"], "mode": "technology", "technologies": ["fastapi"],
        "severity_floor": "medium",
    }, version=2))
    assert "config v2 picked up" in r.note
    idle = w.do_tick(_ctx({"sources": [], "mode": "technology"}))
    assert idle.note == ""


def test_policy_avoid_holds():
    events = _FakeEvents()
    engine = _engine(policy=_AvoidPolicy("openssl"))
    w = _worker({"f1": [_FEED[0]]}, engine=engine, events=events)
    w.do_tick(_ctx({
        "sources": ["f1"], "mode": "security", "components": ["openssl"],
        "severity_floor": "high",
    }))
    assert [p for t, p in events.emitted if "Recommended" in t] == []
