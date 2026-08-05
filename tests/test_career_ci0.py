"""CI.0.1 skill hygiene + LinkedIn export unpack + job watcher max_recommendations."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.career.decision_rule import JobDecisionRule
from atlas.career.feeds import load_postings_json, sample_fixture_path
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.personal.draft import build_linkedin
from atlas.personal.linkedin_export import extract_linkedin_export_text
from atlas.personal.skill_hygiene import is_noise_skill, skill_names_from_facts
from atlas.workers.base import TickContext
from atlas.workers.job_watcher import JobWatcher


def test_noise_skill_filters_hashes():
    assert is_noise_skill("docker-fb7c6151")
    assert is_noise_skill("celery-d0be09db")
    assert is_noise_skill("skill-cc0d78847e")
    assert is_noise_skill("Original")
    assert not is_noise_skill("python")
    assert not is_noise_skill("FastAPI")
    assert not is_noise_skill("power systems")


def test_draft_linkedin_drops_hash_skills():
    profile = {
        "identity": [],
        "skills": [
            {"key": "fastapi", "state": "verified", "value": {"skill": "FastAPI"}},
            {"key": "docker-deadbeef", "state": "verified", "value": {"skill": "docker-deadbeef"}},
            {"key": "original", "state": "verified", "value": {"skill": "Original"}},
        ],
        "timeline": [],
        "professional": [],
    }
    out = build_linkedin(profile)
    assert "FastAPI" in out["markdown"]
    assert "docker-deadbeef" not in out["markdown"]
    assert "Original" not in out["markdown"]
    assert out["counts"]["skills"] == 1


def test_skill_names_from_facts_respects_inferred_flag():
    facts = [
        {"state": "verified", "value": {"skill": "Python"}},
        {"state": "inferred", "value": {"skill": "Rust"}},
        {"state": "rejected", "value": {"skill": "COBOL"}},
        {"state": "verified", "value": {"skill": "celery-aaaaaa"}},
    ]
    assert skill_names_from_facts(facts, include_inferred=False) == ["Python"]
    names = skill_names_from_facts(facts, include_inferred=True)
    assert names == ["Python", "Rust"]


def test_linkedin_export_from_zip(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Profile.csv",
            "First Name,Last Name,Headline\nJagadeshwar,Maddikari,Engineer\n",
        )
        zf.writestr("Skills.csv", "Skill\nPython\nFastAPI\n")
    zpath = tmp_path / "linkedin.zip"
    zpath.write_bytes(buf.getvalue())
    out = extract_linkedin_export_text(zpath)
    assert out["ok"] is True
    assert "Python" in out["text"]
    assert "Jagadeshwar" in out["text"]
    assert out["can_write_linkedin"] is False


def test_sample_fixture_loads():
    path = sample_fixture_path()
    assert path.is_file()
    posts = load_postings_json(path)
    assert len(posts) >= 3
    assert posts[0]["id"]


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
    def skills(self, *, include_inferred=True):
        return [
            {"key": "python", "value": {"skill": "python"}},
            {"key": "fastapi", "value": {"skill": "fastapi"}},
            {"key": "docker-deadbeef12", "value": {"skill": "docker-deadbeef12"}},
        ]


_POSTINGS = [
    {
        "id": "j1", "title": "Senior Python Engineer", "company": "Acme",
        "location": "Berlin", "skills": ["python", "django"], "salary": 120000,
        "url": "https://example.com/j1",
    },
    {
        "id": "j2", "title": "Python FastAPI Engineer", "company": "Beta",
        "location": "Remote", "skills": ["python", "fastapi"], "salary": 130000,
        "url": "https://example.com/j2",
    },
    {
        "id": "j3", "title": "Rust Systems Engineer", "company": "OtherCo",
        "location": "Remote", "skills": ["rust"], "salary": 140000,
    },
]


def test_job_watcher_max_recommendations_fanout():
    events = _FakeEvents()
    reg = DecisionRuleRegistry()
    reg.register(JobDecisionRule())
    engine = DecisionEngine(_FakeDecisionRepo(), rules=reg)
    assets = _FakeAssets({"feed-a": _POSTINGS})
    worker = JobWatcher(
        assets=assets,
        postings_reader=_FakeReader(assets),
        decision_engine=engine,
        personal=_FakePersonal(),
        events=events,
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id=str(uuid.uuid4()),
            config={
                "sources": ["feed-a"],
                "locations": [],
                "skills": [],
                "min_salary": 0,
                "max_recommendations": 2,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    recs = [p for t, p in events.emitted if t == "JobMatchRecommended"]
    assert len(recs) == 2
    assert result.state["last_recommended_count"] == 2
    # Noise skill must not appear as a personal match driver — still ranks on python/fastapi.
    ids = {r["posting"]["id"] for r in recs}
    assert "j3" not in ids
