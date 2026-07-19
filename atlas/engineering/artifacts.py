"""Derived Artifact Store (Phase B · §B.2, BB11 / constitution P11).

Readers turn an **Asset** into a structured **Artifact** (AST / symbol table / repo map /
dependency graph) *before* knowledge extraction: **Asset → Reader → Artifact → Extraction →
Knowledge**. Those artifacts are **deterministic derived products**, not throwaway cache
entries, so they are kept in this **Derived Artifact Store**, keyed by
``{asset_id, asset_version, reader, reader_version}``. Improving the *extractor* later re-runs
extraction against the stored artifact **without re-parsing** the repo (a big CPU win on large
repos). The store is regenerable/derived — the Asset stays the source of truth — so its
physical backing (a Storage cache scope here) is an implementation detail.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from atlas.storage.service import StorageError

if TYPE_CHECKING:
    from atlas.storage.service import StorageManager

ARTIFACT_SCOPE = "derived-artifacts"


def artifact_key(asset_id: str, asset_version: int, reader: str, reader_version: str) -> str:
    """Deterministic key for a reader's artifact against one asset version (BB11)."""
    safe_reader = str(reader).replace("/", "_").replace("@", "-")
    safe_ver = str(reader_version).replace("/", "_").replace("@", "-")
    return f"{asset_id}-v{asset_version}-{safe_reader}-{safe_ver}"


class DerivedArtifactStore:
    """Store/reuse reader artifacts keyed by asset version + reader version (BB11)."""

    def __init__(
        self,
        storage: "StorageManager",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._logger = logger or logging.getLogger("atlas.engineering.artifacts")

    def get(
        self, asset_id: str, asset_version: int, reader: str, reader_version: str
    ) -> dict[str, Any] | None:
        """Return the cached artifact for this key, or ``None`` if not yet built."""
        name = artifact_key(asset_id, asset_version, reader, reader_version)
        try:
            data = self._storage.get_bytes(ARTIFACT_SCOPE, name)
        except StorageError:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._logger.warning("corrupt derived artifact %s — rebuilding", name)
            return None

    def put(
        self,
        asset_id: str,
        asset_version: int,
        reader: str,
        reader_version: str,
        artifact: dict[str, Any],
    ) -> None:
        """Persist a freshly-built artifact under its key (idempotent per key)."""
        name = artifact_key(asset_id, asset_version, reader, reader_version)
        payload = json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._storage.put_file(
            ARTIFACT_SCOPE, name, payload,
            content_type="application/json",
            metadata={
                "asset_id": asset_id, "asset_version": asset_version,
                "reader": reader, "reader_version": reader_version,
            },
        )
        self._logger.info(
            "cached derived artifact %s (%d bytes)", name, len(payload)
        )
