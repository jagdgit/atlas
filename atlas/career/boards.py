"""Job board adapters (CI.3) — sensors only; never decide / apply."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from atlas.decision.rules import CapabilityGap

_LOG = logging.getLogger("atlas.career.boards")


@dataclass
class CareerQuery:
    roles: list[str] = field(default_factory=list)
    sector: str = ""
    salary_min: float = 0.0
    skills: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    limit: int = 25

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CareerQuery":
        d = data or {}
        return cls(
            roles=[str(x) for x in (d.get("roles") or []) if str(x).strip()],
            sector=str(d.get("sector") or "").strip(),
            salary_min=float(d.get("salary_min") or 0),
            skills=[str(x) for x in (d.get("skills") or []) if str(x).strip()],
            locations=[str(x) for x in (d.get("locations") or []) if str(x).strip()],
            sources=[str(x) for x in (d.get("sources") or []) if str(x).strip()],
            limit=max(1, int(d.get("limit") or 25)),
        )


@runtime_checkable
class JobBoardAdapter(Protocol):
    id: str

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        """Return RawPosting dicts — never Decisions."""
        ...


class FixtureBoardAdapter:
    """Hermetic JSON fixture adapter (default CI.3 path)."""

    id = "fixture"

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        path = self._path
        if path is None:
            path = Path(__file__).resolve().parents[2] / "tests/fixtures/career/sample_job_postings.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("postings") or data.get("jobs") or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            p = dict(row)
            p.setdefault("source", self.id)
            if _matches(p, query):
                out.append(p)
            if len(out) >= query.limit:
                break
        return out


class GreenhouseAdapter:
    """Greenhouse public board sensor — live fetch gated; hermetic seed supported."""

    id = "greenhouse"

    def __init__(self, *, board_token: str = "", seed_postings: list[dict[str, Any]] | None = None) -> None:
        self.board_token = board_token
        self._seed = list(seed_postings or [])

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        if self._seed:
            return [dict(p, source=self.id) for p in self._seed if _matches(p, query)][: query.limit]
        if not self.board_token:
            raise CapabilityGap(
                "greenhouse_board",
                detail="Set board_token or seed_postings for Greenhouse discover (no silent scrape)",
            )
        raise CapabilityGap(
            "greenhouse_live_fetch",
            detail="Live Greenhouse HTTP fetch not enabled in this build — use seed or fixture",
        )


class LeverAdapter:
    id = "lever"

    def __init__(self, *, site: str = "", seed_postings: list[dict[str, Any]] | None = None) -> None:
        self.site = site
        self._seed = list(seed_postings or [])

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        if self._seed:
            return [dict(p, source=self.id) for p in self._seed if _matches(p, query)][: query.limit]
        raise CapabilityGap(
            "lever_live_fetch",
            detail="Live Lever fetch not enabled — provide seed_postings (CI.3 hermetic)",
        )


class LinkedInExportAdapter:
    """LinkedIn is export/assist only — never live Easy Apply scrape."""

    id = "linkedin_export"

    def __init__(self, postings: list[dict[str, Any]] | None = None) -> None:
        self._postings = list(postings or [])

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        return [dict(p, source=self.id) for p in self._postings if _matches(p, query)][: query.limit]


class BlockedBoardAdapter:
    """Honest ToS/robots block (Indeed/Naukri-style until approved)."""

    def __init__(self, board_id: str, reason: str) -> None:
        self.id = board_id
        self._reason = reason

    def discover(self, query: CareerQuery) -> list[dict[str, Any]]:
        raise CapabilityGap(f"{self.id}_tos", detail=self._reason)


def default_registry(
    *,
    fixture_path: str | Path | None = None,
    greenhouse_seed: list[dict[str, Any]] | None = None,
    lever_seed: list[dict[str, Any]] | None = None,
) -> dict[str, JobBoardAdapter]:
    return {
        "fixture": FixtureBoardAdapter(fixture_path),
        "greenhouse": GreenhouseAdapter(seed_postings=greenhouse_seed),
        "lever": LeverAdapter(seed_postings=lever_seed),
        "linkedin_export": LinkedInExportAdapter(),
        "indeed": BlockedBoardAdapter(
            "indeed", "Indeed scraping blocked pending ToS-compliant adapter (CapabilityGap)"
        ),
        "naukri": BlockedBoardAdapter(
            "naukri", "Naukri scraping blocked pending ToS-compliant adapter (CapabilityGap)"
        ),
        "wellfound": BlockedBoardAdapter(
            "wellfound", "Wellfound adapter not enabled — CapabilityGap until approved path"
        ),
    }


def discover_all(
    query: CareerQuery | dict[str, Any],
    *,
    adapters: dict[str, JobBoardAdapter] | None = None,
) -> dict[str, Any]:
    """Run selected adapters; collect postings + gaps (sensor layer only)."""
    q = query if isinstance(query, CareerQuery) else CareerQuery.from_dict(query)
    reg = adapters or default_registry()
    wanted = [s.lower() for s in (q.sources or list(reg.keys()))]
    postings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    used: list[str] = []
    for name, adapter in reg.items():
        if wanted and name.lower() not in wanted and adapter.id.lower() not in wanted:
            continue
        try:
            rows = adapter.discover(q)
            postings.extend(rows)
            used.append(adapter.id)
        except CapabilityGap as gap:
            gaps.append({"adapter": adapter.id, "capability": gap.capability, "detail": str(gap)})
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("adapter %s failed: %s", adapter.id, exc)
            gaps.append({"adapter": adapter.id, "error": str(exc)[:200]})
    return {
        "ok": True,
        "query": {
            "roles": q.roles,
            "skills": q.skills,
            "locations": q.locations,
            "sources": wanted,
            "limit": q.limit,
        },
        "postings": postings[: q.limit * 2],
        "adapters_used": used,
        "gaps": gaps,
        "policy": "sensor_only",
        "can_apply": False,
    }


def _matches(posting: dict[str, Any], query: CareerQuery) -> bool:
    title = str(posting.get("title") or "").lower()
    company = str(posting.get("company") or "").lower()
    blob = f"{title} {company} {posting.get('description') or ''}".lower()
    if query.roles and not any(r.lower() in blob for r in query.roles):
        return False
    if query.skills and not any(s.lower() in blob for s in query.skills):
        # soft: allow if posting has no description richness
        skills = posting.get("skills") or []
        if skills and not any(str(s).lower() in {x.lower() for x in skills} for s in query.skills):
            return False
    if query.locations:
        loc = str(posting.get("location") or "").lower()
        if loc and not any(x.lower() in loc or x.lower() == "remote" for x in query.locations):
            if "remote" not in loc:
                return False
    salary = posting.get("salary") or posting.get("salary_max") or 0
    try:
        if query.salary_min and float(salary or 0) and float(salary) < query.salary_min:
            return False
    except (TypeError, ValueError):
        pass
    return True
