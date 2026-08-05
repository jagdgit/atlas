"""Career job-feed import helpers (CI.0.2) — register ``job_postings`` assets + Advisor sources."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("atlas.career.feeds")

SAMPLE_FEED_NAME = "operator_sample_jobs"
FIXTURE_REL = Path("tests/fixtures/career/sample_job_postings.json")


def sample_fixture_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / FIXTURE_REL


def load_postings_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("postings", "jobs", "items", "results", "data"):
            chunk = data.get(key)
            if isinstance(chunk, list):
                return [x for x in chunk if isinstance(x, dict)]
    raise ValueError("JSON must be a list of postings or an object with postings/jobs/items")


def import_job_feed(
    *,
    assets: Any,
    path: str | Path,
    asset_name: str = SAMPLE_FEED_NAME,
    configuration: Any | None = None,
    missions: Any | None = None,
    wire_career_advisor: bool = True,
) -> dict[str, Any]:
    """Register a jobs JSON file as ``job_postings`` asset; optionally wire Career Advisor sources."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"job feed not found: {p}")
    postings = load_postings_json(p)
    if not postings:
        raise ValueError("job feed contains no postings")

    raw = p.read_bytes()
    registered = assets.register(
        "job_postings",
        asset_name,
        raw,
        source_uri=str(p.resolve()),
        content_type="application/json",
        metadata={"posting_count": len(postings), "ci": "CI.0.2"},
    )
    wired: dict[str, Any] | None = None
    if wire_career_advisor and configuration is not None and missions is not None:
        try:
            wired = wire_source_to_career_advisor(
                missions=missions,
                configuration=configuration,
                source_name=asset_name,
            )
        except Exception as exc:  # noqa: BLE001 - import should still succeed
            _LOG.warning("wire Career Advisor sources failed: %s", exc)
            wired = {"ok": False, "reason": str(exc)}

    return {
        "ok": True,
        "asset_name": asset_name,
        "asset_id": str((registered.get("asset") or {}).get("id") or ""),
        "posting_count": len(postings),
        "path": str(p.resolve()),
        "career_advisor": wired,
        "policy": "recommend_only",
        "can_apply": False,
        "note": (
            "Feed registered. Career Advisor will rank on next tick when sources include "
            f"{asset_name!r}. Atlas never applies for you."
        ),
    }


def wire_source_to_career_advisor(
    *,
    missions: Any,
    configuration: Any,
    source_name: str,
) -> dict[str, Any]:
    """Append ``source_name`` to the active Personal Career Advisor (job_hunting) config."""
    mission = _find_career_advisor_mission(missions)
    if mission is None:
        return {"ok": False, "reason": "no active Career Advisor (job_hunting) mission"}

    mid = getattr(mission, "id", None) or mission.get("id")
    active = configuration.get_active(mid)
    if active is None:
        return {"ok": False, "reason": "Career Advisor has no active config"}
    doc = dict(getattr(active, "document", None) or active.get("document") or {})
    sources = [str(s) for s in (doc.get("sources") or []) if str(s).strip()]
    if source_name not in sources:
        sources.append(source_name)
    doc["sources"] = sources
    if not doc.get("max_recommendations"):
        doc["max_recommendations"] = 5
    cfg = configuration.update_config(
        mid,
        doc,
        change_note=f"CI.0.2 wire job_postings source {source_name}",
        activate=True,
    )
    return {
        "ok": True,
        "mission_id": str(mid),
        "sources": sources,
        "config_version": getattr(cfg, "version", None),
    }


def _find_career_advisor_mission(missions: Any) -> Any | None:
    """Prefer active job_hunting / Career Advisor mission."""
    rows: list[Any] = []
    if hasattr(missions, "list_missions"):
        try:
            rows = list(missions.list_missions(status="active", limit=100) or [])
        except TypeError:
            try:
                rows = list(missions.list_missions(limit=100) or [])
            except TypeError:
                rows = list(missions.list_missions() or [])
    elif hasattr(missions, "list"):
        try:
            rows = list(missions.list(status="active") or [])
        except TypeError:
            rows = list(missions.list() or [])
    for m in rows:
        title = str(getattr(m, "title", None) or (m.get("title") if isinstance(m, dict) else "") or "")
        labels = getattr(m, "labels", None) or (m.get("labels") if isinstance(m, dict) else None) or []
        label_s = " ".join(str(x) for x in labels) if not isinstance(labels, str) else labels
        status = str(getattr(m, "status", None) or (m.get("status") if isinstance(m, dict) else "") or "")
        if status and status not in {"active", "running"}:
            # Still allow if title matches — list may already be filtered.
            if "Career Advisor" not in title and "job_hunting" not in label_s:
                continue
        if "job_hunting" in label_s or "Career Advisor" in title or "role:job_hunting" in label_s:
            return m
    for m in rows:
        title = str(getattr(m, "title", None) or (m.get("title") if isinstance(m, dict) else "") or "")
        if "Career Advisor" in title:
            return m
    return None
