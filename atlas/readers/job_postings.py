"""Job-postings Reader (Phase D · PHASE_D_PLAN §D.8 / constitution P8/P11).

Job postings enter Atlas as an **Asset**, read by a stateless **Reader** into an **Artifact**
(``Asset → Reader → Artifact``, P8/P11). This reader turns a fixture/export of job postings
(``.json`` list or object with a ``postings``/``jobs``/``listings`` list) into a normalized
postings artifact the Job Watcher matches. It owns no knowledge or state (P11): it reads bytes
and returns an artifact, cached in the Derived Artifact Store keyed by
``{asset_id, asset_version, reader, reader_version}`` (BB11).

Accepted shapes (tolerant):
  * ``.json`` — a list of posting objects, or an object with a ``postings``/``jobs``/``listings``/
    ``results``/``data`` list.
Each posting needs at least an ``id`` (or ``url``) and a ``title``; rows missing either are skipped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

JOB_POSTINGS_READER_ID = "job_postings"
JOB_POSTINGS_READER_VERSION = "1.0.0"

_SUPPORTED_EXTENSIONS = (".json",)
_LIST_KEYS = ("postings", "jobs", "listings", "results", "data", "items")
_ID_KEYS = ("id", "job_id", "posting_id", "uuid", "url")
_TITLE_KEYS = ("title", "role", "position", "job_title", "name")
_COMPANY_KEYS = ("company", "employer", "organization", "org")
_LOCATION_KEYS = ("location", "city", "place", "remote_location")
_SALARY_KEYS = ("salary", "salary_max", "max_salary", "compensation", "pay")
_SKILL_KEYS = ("skills", "requirements", "tags", "keywords", "technologies")
_URL_KEYS = ("url", "link", "apply_url", "href")


class JobPostingsReader:
    """Read a job-postings feed asset → cached postings artifact (BB11); reuse when unchanged."""

    id = JOB_POSTINGS_READER_ID
    VERSION = JOB_POSTINGS_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._logger = logger or logging.getLogger("atlas.readers.job_postings")

    def supported_extensions(self) -> list[str]:
        return list(_SUPPORTED_EXTENSIONS)

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        version = self._resolve_version(asset_id, asset_version)
        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                return cached
        filename = filename or self._filename_from_metadata(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if filename else ""
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "content_type": "application/json",
            "extension": suffix,
        }
        if suffix and suffix not in _SUPPORTED_EXTENSIONS:
            return {**base, "outcome": "unsupported", "postings": [], "count": 0,
                    "reason": f"unsupported job-postings format: {suffix}"}
        try:
            raw = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "postings": [], "count": 0,
                    "reason": f"decode failed: {exc}"}
        try:
            postings = self._parse_json(raw)
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "postings": [], "count": 0,
                    "reason": f"parse failed: {exc}"}
        if not postings:
            return {**base, "outcome": "empty", "postings": [], "count": 0,
                    "reason": "no usable postings (need id + title)"}
        return {
            **base,
            "outcome": "ok",
            "reason": None,
            "postings": postings,
            "count": len(postings),
        }

    def _parse_json(self, raw: str) -> list[dict[str, Any]]:
        raw = raw.strip()
        if not raw:
            return []
        doc = json.loads(raw)
        rows: list[Any]
        if isinstance(doc, dict):
            rows = []
            for key in _LIST_KEYS:
                if isinstance(doc.get(key), list):
                    rows = doc[key]
                    break
        elif isinstance(doc, list):
            rows = doc
        else:
            rows = []
        return [p for p in (self._normalize(r) for r in rows) if p is not None]

    def _normalize(self, row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        pid = self._first_str(lower, _ID_KEYS)
        title = self._first_str(lower, _TITLE_KEYS)
        if not pid or not title:
            return None
        skills = self._skills(lower)
        salary = self._first_float(lower, _SALARY_KEYS)
        return {
            "id": pid,
            "title": title,
            "company": self._first_str(lower, _COMPANY_KEYS) or "",
            "location": self._first_str(lower, _LOCATION_KEYS) or "",
            "salary": salary,
            "skills": skills,
            "url": self._first_str(lower, _URL_KEYS),
            "description": self._first_str(lower, ("description", "summary", "body")) or "",
        }

    @staticmethod
    def _skills(row: dict[str, Any]) -> list[str]:
        for key in _SKILL_KEYS:
            if key not in row:
                continue
            value = row[key]
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str) and value.strip():
                return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        return []

    @staticmethod
    def _first_str(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return str(row[key]).strip()
        return None

    @staticmethod
    def _first_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    continue
        return None

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise ValueError(f"asset has no versions: {asset_id}")
        return int(versions[0]["version"])

    def _filename_from_metadata(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                name = meta.get("filename")
                return str(name) if name else None
        return None
