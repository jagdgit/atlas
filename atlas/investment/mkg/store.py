"""IIP.5 — durable MKG store under data/investment/mkg/."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from atlas.investment.mkg.schema import VERSION, empty_graph

_log = logging.getLogger("atlas.investment.mkg.store")

STORE_REL = Path("investment") / "mkg" / "graph.json"


def store_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def load_graph(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return empty_graph()
    path = store_path(data_dir)
    if not path.is_file():
        return empty_graph()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("nodes"), dict):
            raw.setdefault("version", VERSION)
            raw.setdefault("edges", [])
            return raw
    except Exception:  # noqa: BLE001
        _log.debug("mkg load failed", exc_info=True)
    return empty_graph()


def save_graph(data_dir: str | Path | None, graph: dict[str, Any]) -> Path | None:
    if not data_dir:
        return None
    path = store_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = dict(graph)
        nodes = doc.get("nodes") or {}
        edges = doc.get("edges") or []
        doc["version"] = VERSION
        doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        doc["stats"] = {"nodes": len(nodes), "edges": len(edges)}
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        _log.debug("mkg save failed", exc_info=True)
        return None


def upsert_node(graph: dict[str, Any], node: dict[str, Any]) -> None:
    nodes = graph.setdefault("nodes", {})
    nid = node["id"]
    prev = dict(nodes.get(nid) or {})
    prev.update(node)
    nodes[nid] = prev


def upsert_edge(graph: dict[str, Any], edge: dict[str, Any]) -> None:
    edges = list(graph.get("edges") or [])
    eid = edge.get("id")
    found = False
    for i, e in enumerate(edges):
        if isinstance(e, dict) and e.get("id") == eid:
            edges[i] = {**e, **edge}
            found = True
            break
    if not found:
        edges.append(edge)
    graph["edges"] = edges
