"""Advisory-feed Reader (Phase D · PHASE_D_PLAN §D.9 / constitution P8/P11).

CVE / breaking-change / dependency feeds enter as an **Asset**, read by a stateless **Reader**
into an **Artifact**. Turns a ``.json`` list (or object with an ``advisories``/``items``/
``vulnerabilities``/``releases`` list) into normalized advisories the Tech/Security Watcher
ranks. Owns no knowledge or state (P11); cached in the Derived Artifact Store (BB11).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

ADVISORY_FEED_READER_ID = "advisory_feed"
ADVISORY_FEED_READER_VERSION = "1.0.0"

_SUPPORTED_EXTENSIONS = (".json",)
_LIST_KEYS = ("advisories", "items", "vulnerabilities", "releases", "entries", "data", "results")
_ID_KEYS = ("id", "advisory_id", "cve", "uuid", "url", "name")
_TITLE_KEYS = ("title", "summary", "name", "headline", "advisory")
_SEVERITY_KEYS = ("severity", "severity_level", "priority", "cvss_severity")
_KIND_KEYS = ("kind", "type", "category", "advisory_type")
_PACKAGE_KEYS = ("package", "component", "product", "library", "dependency")
_PACKAGES_KEYS = ("packages", "components", "affected", "products")
_URL_KEYS = ("url", "link", "href", "reference")
_CVE_KEYS = ("cve", "cve_id", "cveid")
_SUMMARY_KEYS = ("summary", "description", "body", "details")


class AdvisoryFeedReader:
    """Read an advisory feed asset → cached advisory artifact (BB11); reuse when unchanged."""

    id = ADVISORY_FEED_READER_ID
    VERSION = ADVISORY_FEED_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._logger = logger or logging.getLogger("atlas.readers.advisory_feed")

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
            return {**base, "outcome": "unsupported", "advisories": [], "count": 0,
                    "reason": f"unsupported advisory-feed format: {suffix}"}
        try:
            raw = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "advisories": [], "count": 0,
                    "reason": f"decode failed: {exc}"}
        try:
            advisories = self._parse_json(raw)
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "advisories": [], "count": 0,
                    "reason": f"parse failed: {exc}"}
        if not advisories:
            return {**base, "outcome": "empty", "advisories": [], "count": 0,
                    "reason": "no usable advisories (need id + title)"}
        return {
            **base,
            "outcome": "ok",
            "reason": None,
            "advisories": advisories,
            "count": len(advisories),
        }

    def _parse_json(self, raw: str) -> list[dict[str, Any]]:
        raw = raw.strip()
        if not raw:
            return []
        doc = json.loads(raw)
        if isinstance(doc, dict):
            rows: list[Any] = []
            for key in _LIST_KEYS:
                if isinstance(doc.get(key), list):
                    rows = doc[key]
                    break
            if not rows and ("title" in {k.lower() for k in doc} or "id" in {k.lower() for k in doc}):
                rows = [doc]
        elif isinstance(doc, list):
            rows = doc
        else:
            rows = []
        return [a for a in (self._normalize(r) for r in rows) if a is not None]

    def _normalize(self, row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        aid = self._first_str(lower, _ID_KEYS)
        title = self._first_str(lower, _TITLE_KEYS)
        if not aid or not title:
            return None
        packages = self._packages(lower)
        package = self._first_str(lower, _PACKAGE_KEYS) or (packages[0] if packages else "")
        kind = (self._first_str(lower, _KIND_KEYS) or self._infer_kind(lower)).lower()
        severity = (self._first_str(lower, _SEVERITY_KEYS) or "unknown").lower()
        return {
            "id": aid,
            "title": title,
            "severity": severity,
            "kind": kind,
            "package": package,
            "packages": packages or ([package] if package else []),
            "cve": self._first_str(lower, _CVE_KEYS),
            "url": self._first_str(lower, _URL_KEYS),
            "summary": self._first_str(lower, _SUMMARY_KEYS) or "",
        }

    def _packages(self, row: dict[str, Any]) -> list[str]:
        for key in _PACKAGES_KEYS:
            if key not in row:
                continue
            value = row[key]
            if isinstance(value, list):
                out: list[str] = []
                for item in value:
                    if isinstance(item, str) and item.strip():
                        out.append(item.strip())
                    elif isinstance(item, dict):
                        name = item.get("name") or item.get("package") or item.get("product")
                        if name:
                            out.append(str(name).strip())
                return out
            if isinstance(value, str) and value.strip():
                return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        return []

    @staticmethod
    def _infer_kind(row: dict[str, Any]) -> str:
        if any(k in row for k in _CVE_KEYS) or "cve" in str(row.get("id") or "").lower():
            return "cve"
        title = str(row.get("title") or "").lower()
        if "breaking" in title:
            return "breaking_change"
        if "depend" in title or "upgrade" in title:
            return "dependency"
        return "advisory"

    @staticmethod
    def _first_str(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return str(row[key]).strip()
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
