"""Career Observer helpers (CI.1.2) — normalize → knowledge candidates (no recommend)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def candidates_from_bundle(
    bundle: dict[str, Any],
    *,
    mission_id: str | None = None,
    max_candidates: int = 40,
) -> list[dict[str, Any]]:
    """Build ``domain=career`` candidate payloads from a LinkedIn export bundle."""
    payloads: list[dict[str, Any]] = []
    path = str(bundle.get("path") or "")
    evidence_base = {
        "source": "linkedin_export",
        "path": path,
        "mission_id": mission_id,
        "policy": "discover_only",
    }

    for skill in bundle.get("skills") or []:
        name = str(skill).strip()
        if not name:
            continue
        payloads.append(
            _candidate(
                statement=f"Owner LinkedIn skill: {name}",
                claim_type="fact",
                value={"skill": name, "source": "linkedin_export"},
                evidence_ref={**evidence_base, "member": "Skills.csv"},
                reader="career_observer",
                mission_id=mission_id,
            )
        )

    for pos in bundle.get("positions") or []:
        if not isinstance(pos, dict):
            continue
        company = str(pos.get("company") or "").strip()
        title = str(pos.get("title") or "").strip()
        if not (company or title):
            continue
        payloads.append(
            _candidate(
                statement=f"Owner role: {title} at {company}".strip(" at"),
                claim_type="fact",
                value={
                    "title": title,
                    "company": company,
                    "started_on": pos.get("started_on"),
                    "finished_on": pos.get("finished_on"),
                    "source": "linkedin_export",
                },
                evidence_ref={**evidence_base, "member": "Positions.csv"},
                reader="career_observer",
                mission_id=mission_id,
            )
        )

    for posting in bundle.get("postings") or []:
        if not isinstance(posting, dict):
            continue
        payloads.append(posting_candidate(posting, mission_id=mission_id, path=path))

    for company in bundle.get("companies_followed") or []:
        name = str(company).strip()
        if not name:
            continue
        payloads.append(
            _candidate(
                statement=f"Owner follows company: {name}",
                claim_type="entity",
                value={"company": name, "source": "linkedin_export_follow"},
                evidence_ref={**evidence_base, "member": "Company Follows.csv"},
                reader="career_observer",
                mission_id=mission_id,
            )
        )

    return payloads[: max(0, max_candidates)]


def posting_candidate(
    posting: dict[str, Any],
    *,
    mission_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    title = str(posting.get("title") or "").strip()
    company = str(posting.get("company") or "").strip()
    pid = str(posting.get("id") or "")
    source = str(posting.get("source") or "job_feed")
    statement = f"Job posting observed: {title} at {company}".strip(" at")
    if not statement.strip(" :"):
        statement = f"Job posting observed: {pid or 'unknown'}"
    return _candidate(
        statement=statement,
        claim_type="fact",
        value={
            "posting_id": pid,
            "title": title,
            "company": company,
            "url": posting.get("url"),
            "source": source,
            "operator_status": posting.get("operator_status"),
        },
        evidence_ref={
            "source": source,
            "path": path,
            "posting_id": pid,
            "mission_id": mission_id,
            "policy": "discover_only",
        },
        reader="career_observer",
        mission_id=mission_id,
    )


def candidates_from_postings(
    postings: list[dict[str, Any]],
    *,
    mission_id: str | None = None,
    max_candidates: int = 40,
) -> list[dict[str, Any]]:
    out = [
        posting_candidate(p, mission_id=mission_id)
        for p in postings
        if isinstance(p, dict)
    ]
    return out[: max(0, max_candidates)]


def profile_snapshot_bytes(bundle: dict[str, Any]) -> bytes:
    """Serialize a compact profile snapshot for Asset Store (CI.1.1)."""
    payload = {
        "ok": bool(bundle.get("ok")),
        "path": bundle.get("path"),
        "files": bundle.get("files") or [],
        "skills": bundle.get("skills") or [],
        "positions": bundle.get("positions") or [],
        "posting_count": len(bundle.get("postings") or []),
        "companies_followed": (bundle.get("companies_followed") or [])[:50],
        "chars": bundle.get("chars"),
        "policy": "suggestions_only",
        "can_write_linkedin": False,
        "text_preview": (bundle.get("text") or "")[:4000],
    }
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def postings_asset_bytes(postings: list[dict[str, Any]]) -> bytes:
    return json.dumps(postings, indent=2, default=str).encode("utf-8")


def fingerprint(parts: list[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _candidate(
    *,
    statement: str,
    claim_type: str,
    value: dict[str, Any],
    evidence_ref: dict[str, Any],
    reader: str,
    mission_id: str | None,
) -> dict[str, Any]:
    return {
        "statement": statement,
        "claim_type": claim_type,
        "domain": "career",
        "value": value,
        "evidence_ref": evidence_ref,
        "provenance": {"pipeline": "career_observer", "ci": "CI.1.2"},
        "reader": reader,
        "reader_version": 1,
        "mission_id": mission_id,
    }
