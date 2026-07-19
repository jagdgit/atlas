"""Architecture graph as a versioned asset (Phase B · §B.3, BB3).

The import/call/module graph a reader produces is a **deterministic derived product**, so it is
persisted as its own versioned ``architecture_graph`` **asset** (JSON) keyed by ``repo_uid`` and
linked back to the ``git_repo`` asset it was distilled from. Content-addressed versioning means an
unchanged graph **reuses** its version; a real structural change cuts a new version whose **diff**
(added/removed modules, edges, entry points) explains what changed. Per constitution P11 this is a
stateless translator over the artifact — it owns no state and makes no decisions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

ASSET_KIND_GRAPH = "architecture_graph"


def build_architecture_graph(artifact: dict[str, Any], *, repo_uid: str) -> dict[str, Any]:
    """Normalize a reader artifact into a compact, diffable architecture graph doc (BB3)."""
    repo_map = artifact.get("repo_map", {}) or {}
    graph = artifact.get("graph", {}) or {}
    modules = sorted(
        {str(f.get("path", "")) for f in repo_map.get("files", []) if f.get("path")}
    )
    import_edges = sorted(list(e) for e in graph.get("import_edges", []))
    call_edges = sorted(list(e) for e in graph.get("call_edges", []))
    entry_points = sorted(str(e) for e in repo_map.get("entry_points", []))
    return {
        "repo_uid": repo_uid,
        "modules": modules,
        "import_edges": import_edges,
        "call_edges": call_edges,
        "entry_points": entry_points,
        "languages": repo_map.get("languages", {}),
        "frameworks": list(repo_map.get("frameworks", [])),
        "counts": {
            "modules": len(modules),
            "import_edges": len(import_edges),
            "call_edges": len(call_edges),
            "entry_points": len(entry_points),
        },
    }


def graph_checksum(graph_doc: dict[str, Any]) -> str:
    """Content hash over the *structural* parts — change ⇒ a new graph version (BB3)."""
    structural = {
        "modules": graph_doc.get("modules", []),
        "import_edges": graph_doc.get("import_edges", []),
        "call_edges": graph_doc.get("call_edges", []),
        "entry_points": graph_doc.get("entry_points", []),
    }
    blob = json.dumps(structural, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _as_edge_set(edges: list[Any]) -> set[tuple[str, ...]]:
    return {tuple(str(x) for x in e) for e in edges or []}


def diff_graphs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Structural delta between two graph versions (added/removed modules/edges/entry points)."""
    mo, mn = set(old.get("modules", [])), set(new.get("modules", []))
    ieo, ien = _as_edge_set(old.get("import_edges", [])), _as_edge_set(new.get("import_edges", []))
    ceo, cen = _as_edge_set(old.get("call_edges", [])), _as_edge_set(new.get("call_edges", []))
    epo, epn = set(old.get("entry_points", [])), set(new.get("entry_points", []))

    added_modules = sorted(mn - mo)
    removed_modules = sorted(mo - mn)
    added_import_edges = sorted(list(e) for e in ien - ieo)
    removed_import_edges = sorted(list(e) for e in ieo - ien)
    added_call_edges = sorted(list(e) for e in cen - ceo)
    removed_call_edges = sorted(list(e) for e in ceo - cen)
    added_entry_points = sorted(epn - epo)
    removed_entry_points = sorted(epo - epn)

    changed = any((
        added_modules, removed_modules, added_import_edges, removed_import_edges,
        added_call_edges, removed_call_edges, added_entry_points, removed_entry_points,
    ))
    return {
        "changed": changed,
        "added_modules": added_modules,
        "removed_modules": removed_modules,
        "added_import_edges": added_import_edges,
        "removed_import_edges": removed_import_edges,
        "added_call_edges": added_call_edges,
        "removed_call_edges": removed_call_edges,
        "added_entry_points": added_entry_points,
        "removed_entry_points": removed_entry_points,
    }


class ArchitectureGraphStore:
    """Persist/retrieve/diff the architecture graph as a versioned asset (BB3)."""

    def __init__(
        self,
        asset_store: "AssetStore",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = asset_store
        self._logger = logger or logging.getLogger("atlas.engineering.architecture")

    def persist(
        self,
        repo_uid: str,
        graph_doc: dict[str, Any],
        *,
        repo_asset_id: str | None = None,
        repo_asset_version: int | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a new graph version (reusing the current one if unchanged).

        Returns ``{asset_id, version, reused, diff}`` — ``diff`` is the structural delta
        against the immediately-previous version (``None`` on reuse or first version).
        """
        checksum = graph_checksum(graph_doc)
        existing = self._assets.get_by_name(ASSET_KIND_GRAPH, repo_uid)
        previous_doc: dict[str, Any] | None = None
        if existing is not None:
            versions = self._assets.versions(str(existing["id"]))
            if versions:
                current = versions[0]
                if (current.get("metadata") or {}).get("graph_checksum") == checksum:
                    self._logger.info(
                        "architecture graph for %s unchanged — reusing v%s",
                        repo_uid, current["version"],
                    )
                    return {
                        "asset_id": str(existing["id"]),
                        "version": int(current["version"]),
                        "reused": True,
                        "diff": None,
                    }
                try:
                    previous_doc = self.get(repo_uid)
                except Exception:  # noqa: BLE001 - a diff is best-effort, never fatal
                    self._logger.debug("previous graph load failed", exc_info=True)

        metadata: dict[str, Any] = {
            "graph_checksum": checksum,
            "repo_uid": repo_uid,
            "counts": graph_doc.get("counts", {}),
        }
        if repo_asset_id:
            metadata["repo_asset_id"] = repo_asset_id
        if repo_asset_version is not None:
            metadata["repo_asset_version"] = repo_asset_version
        if mission_id:
            metadata["mission_id"] = mission_id

        payload = json.dumps(graph_doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
        result = self._assets.register(
            ASSET_KIND_GRAPH, repo_uid, payload,
            content_type="application/json",
            metadata=metadata,
        )
        asset_id = str(result["asset"]["id"])
        version = int(result["version"]["version"])
        diff = diff_graphs(previous_doc, graph_doc) if previous_doc is not None else None
        self._logger.info("persisted architecture graph %s v%s", repo_uid, version)
        return {"asset_id": asset_id, "version": version, "reused": False, "diff": diff}

    def get(self, repo_uid: str, version: int | None = None) -> dict[str, Any] | None:
        """Return the graph doc for a repo (latest unless a version is given)."""
        existing = self._assets.get_by_name(ASSET_KIND_GRAPH, repo_uid)
        if existing is None:
            return None
        data = self._assets.get_bytes(str(existing["id"]), version)
        return json.loads(data.decode("utf-8"))

    def versions(self, repo_uid: str) -> list[dict[str, Any]]:
        """Version rows (newest first) for a repo's architecture graph."""
        existing = self._assets.get_by_name(ASSET_KIND_GRAPH, repo_uid)
        if existing is None:
            return []
        return self._assets.versions(str(existing["id"]))

    def diff(self, repo_uid: str, from_version: int, to_version: int) -> dict[str, Any] | None:
        """Structural diff between two persisted graph versions of the same repo."""
        old = self.get(repo_uid, from_version)
        new = self.get(repo_uid, to_version)
        if old is None or new is None:
            return None
        return diff_graphs(old, new)
