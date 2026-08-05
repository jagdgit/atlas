"""CI.1 — Career Observer, watchlist, brief, export structured parse."""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest

from atlas.career import watchlist as wl
from atlas.career.brief import build_morning_brief
from atlas.career.observe import candidates_from_bundle
from atlas.configuration.schemas import default_registry
from atlas.knowledge.domains import ALL_DOMAINS, DOMAIN_CAREER
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.templates.resources import resources_for
from atlas.personal.linkedin_export import (
    extract_linkedin_export_text,
    load_linkedin_export_bundle,
)
from atlas.workers.base import TickContext
from atlas.workers.career_observer import CareerObserverWorker


def _sample_export_zip(tmp_path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Profile.csv",
            "First Name,Last Name,Headline\nJagadeshwar,Maddikari,Engineer\n",
        )
        zf.writestr("Skills.csv", "Name\nPython\nFastAPI\n")
        zf.writestr(
            "Positions.csv",
            "Company Name,Title,Description,Location,Started On,Finished On\n"
            "Peak Energy,Senior Technical Specialist,,,Mar 2026,\n",
        )
        zf.writestr(
            "Jobs/Saved Jobs.csv",
            "Saved Date,Job Url,Job Title,Company Name\n"
            '"1/1/26",http://www.linkedin.com/jobs/view/999001,Controls Engineer,Siemens\n',
        )
        zf.writestr(
            "Jobs/Job Applications.csv",
            "Application Date,Contact Email,Contact Phone Number,Company Name,Job Title,Job Url,Resume Name,Question And Answers\n"
            '"1/2/26",a@b.c,,Bosch,System Test Engineer,http://www.linkedin.com/jobs/view/999002,r.pdf,q\n',
        )
        zf.writestr("Company Follows.csv", "Organization,Followed On\nHitachi Energy,Mon Jun 01\n")
        zf.writestr("messages.csv", "x," + ("y" * 5000) + "\n")
        zf.writestr("Ad_Targeting.csv", "noise," + ("z" * 3000) + "\n")
    zpath = tmp_path / "linkedin.zip"
    zpath.write_bytes(buf.getvalue())
    return zpath


def test_career_domain_registered():
    assert DOMAIN_CAREER in ALL_DOMAINS
    assert "career" in ALL_DOMAINS


def test_career_observer_template_and_batch():
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    assert "career_observer" in names
    prof = resources_for("career_observer")
    assert prof.service_class == "BATCH"
    cfg, ver = default_registry().validate("career_observer", {})
    assert ver == 1
    assert cfg["wire_advisor_sources"] is False


def test_export_skips_noise_and_parses_jobs(tmp_path: Path):
    zpath = _sample_export_zip(tmp_path)
    text = extract_linkedin_export_text(zpath)
    assert text["ok"] is True
    assert "Python" in text["text"]
    assert "messages.csv" not in (text.get("files") or [])
    assert "Ad_Targeting.csv" not in (text.get("files") or [])

    bundle = load_linkedin_export_bundle(zpath)
    assert bundle["ok"] is True
    assert "Python" in bundle["skills"]
    assert any(p.get("company") == "Peak Energy" for p in bundle["positions"])
    ids = {p["id"] for p in bundle["postings"]}
    assert "linkedin-999001" in ids
    assert "linkedin-999002" in ids
    applied = [p for p in bundle["postings"] if p.get("operator_status") == "applied"]
    assert applied
    assert "Hitachi Energy" in bundle["companies_followed"]


def test_candidates_from_bundle_domain_career(tmp_path: Path):
    bundle = load_linkedin_export_bundle(_sample_export_zip(tmp_path))
    payloads = candidates_from_bundle(bundle, mission_id="m1", max_candidates=20)
    assert payloads
    assert all(p["domain"] == "career" for p in payloads)
    assert any("Python" in p["statement"] for p in payloads)


def test_watchlist_upsert_and_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATLAS_CAREER_DIR", str(tmp_path / "career"))
    out = wl.upsert(label="Siemens", kind="company", operator_status="interested")
    assert out["ok"] is True
    listed = wl.list_items()
    assert listed["count"] >= 1
    assert "Siemens" in wl.companies_for_filter(statuses=["interested"])

    class _Personal:
        def best_jobs(self, **kwargs):
            return {
                "ok": True,
                "jobs": [{"title": "Controls Engineer", "company": "Siemens", "score": 0.9}],
                "can_apply": False,
            }

    brief = build_morning_brief(personal=_Personal(), include_jobs=True, job_limit=3)
    assert brief["ok"] is True
    assert brief["policy"]["can_apply"] is False
    assert brief["policy"]["observer_recommends"] is False
    assert any("interested" in h for h in brief["highlights"])


class _FakeCandidates:
    def __init__(self) -> None:
        self.emitted: list[dict[str, Any]] = []

    def emit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.emitted.append(payload)
        return {"id": str(uuid.uuid4()), **payload}

    def consume_pending(self, limit: int = 20) -> int:
        return min(limit, len(self.emitted))


class _FakeAssets:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str]] = []

    def register(self, kind, name, data, **kwargs):
        self.registered.append((kind, name))
        return {"asset": {"id": str(uuid.uuid4())}, "version": {"version": 1}}

    def get_by_name(self, kind, name):
        return None


def test_career_observer_tick_emits_no_recommend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATLAS_CAREER_DIR", str(tmp_path / "career"))
    zpath = _sample_export_zip(tmp_path)
    cands = _FakeCandidates()
    assets = _FakeAssets()
    worker = CareerObserverWorker(candidates=cands, assets=assets)
    ctx = TickContext(
        mission_id="career-obs-1",
        worker_id="w1",
        config={
            "linkedin_export_paths": [str(zpath)],
            "register_job_assets": True,
            "seed_watchlist": True,
            "wire_advisor_sources": False,
            "max_candidates_per_tick": 30,
        },
        state={},
        inputs=[],
        config_version=1,
    )
    result = worker.do_tick(ctx)
    assert "discover only" in (result.note or "")
    assert cands.emitted
    assert all(p.get("domain") == "career" for p in cands.emitted)
    assert ("linkedin_profile", "linkedin_profile_export") in assets.registered
    assert ("job_postings", "linkedin_export_jobs") in assets.registered
    # Never a decision / recommend payload
    assert not any("recommend" in str(p.get("statement") or "").lower() for p in cands.emitted)
