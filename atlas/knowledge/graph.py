"""Knowledge Graph — derived Claim↔Concept↔Entity↔SPO view (KG.1 / V6).

Built on read from Knowledge findings — not a second claim store or graph DB
(philosophy: no parallel consolidator). Edges come from typed ``value`` links and
relationship SPO triples already produced by KE.2.x.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.knowledge.lifecycle import normalize_statement


def _node_id(kind: str, label: str) -> str:
    return f"{kind}:{normalize_statement(label)}"


def build_knowledge_graph(
    findings: list[dict[str, Any]] | None,
    *,
    q: str | None = None,
    limit_nodes: int = 80,
    limit_edges: int = 120,
) -> dict[str, Any]:
    """Construct a graph snapshot from finding rows."""
    needle = (q or "").strip().lower()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_keys: set[str] = set()

    def upsert_node(
        kind: str,
        label: str,
        *,
        finding_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str | None:
        label = (label or "").strip()
        if not label:
            return None
        nid = _node_id(kind, label)
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "kind": kind,
                "label": label,
                "finding_ids": [],
            }
        if finding_id:
            ids = nodes[nid]["finding_ids"]
            if finding_id not in ids:
                ids.append(finding_id)
        if extra:
            nodes[nid].update({k: v for k, v in extra.items() if v is not None})
        return nid

    def add_edge(
        source: str,
        target: str,
        rel: str,
        *,
        finding_id: str | None = None,
        predicate: str | None = None,
    ) -> None:
        if not source or not target or source == target:
            return
        key = f"{source}|{rel}|{target}|{predicate or ''}"
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "rel": rel,
                "predicate": predicate,
                "finding_id": finding_id,
            }
        )

    for f in findings or []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "")
        ct = str(f.get("claim_type") or "").strip().lower()
        statement = str(f.get("statement") or "").strip()
        value = f.get("value") if isinstance(f.get("value"), dict) else {}
        domain = f.get("domain")

        if needle:
            hay = " ".join(
                [
                    statement,
                    ct,
                    str(value.get("name") or ""),
                    str(value.get("subject") or ""),
                    str(value.get("predicate") or ""),
                    str(value.get("object") or ""),
                    " ".join(str(x) for x in (value.get("related_concepts") or [])),
                    " ".join(str(x) for x in (value.get("related_entities") or [])),
                ]
            ).lower()
            if needle not in hay and not any(
                tok in hay for tok in needle.split() if len(tok) > 2
            ):
                continue

        if ct in {"concept", "entity"}:
            name = str(value.get("name") or statement).strip()
            upsert_node(
                ct,
                name,
                finding_id=fid or None,
                extra={"entity_type": value.get("entity_type"), "domain": domain},
            )
            continue

        if ct in {"relationship", "fact"}:
            subj = str(value.get("subject") or "").strip()
            pred = str(value.get("predicate") or ct).strip()
            obj = str(value.get("object") or "").strip()
            sid = upsert_node("entity", subj, finding_id=fid or None) if subj else None
            # Prefer entity for object; concepts may appear as objects too
            oid = upsert_node("entity", obj, finding_id=fid or None) if obj else None
            if sid and oid:
                add_edge(sid, oid, "spo", finding_id=fid or None, predicate=pred)
            # Also a relationship node for the triple itself
            if statement or (subj and obj):
                rid = upsert_node(
                    "relationship",
                    statement or f"{subj} {pred} {obj}",
                    finding_id=fid or None,
                    extra={"subject": subj, "predicate": pred, "object": obj, "domain": domain},
                )
                if rid and sid:
                    add_edge(rid, sid, "has_subject", finding_id=fid or None)
                if rid and oid:
                    add_edge(rid, oid, "has_object", finding_id=fid or None)
            continue

        if ct == "claim":
            cid = upsert_node(
                "claim",
                statement[:160] or f"claim:{fid}",
                finding_id=fid or None,
                extra={"domain": domain},
            )
            for name in value.get("related_concepts") or []:
                nid = upsert_node("concept", str(name), finding_id=fid or None)
                if cid and nid:
                    add_edge(cid, nid, "mentions", finding_id=fid or None)
            for name in value.get("related_entities") or []:
                nid = upsert_node("entity", str(name), finding_id=fid or None)
                if cid and nid:
                    add_edge(cid, nid, "mentions", finding_id=fid or None)
            for link in value.get("links") or []:
                if not isinstance(link, dict):
                    continue
                target = str(link.get("target") or "").strip()
                ttype = str(link.get("target_type") or "concept").strip() or "concept"
                rel = str(link.get("rel") or "mentions").strip() or "mentions"
                nid = upsert_node(ttype, target, finding_id=fid or None)
                if cid and nid:
                    add_edge(cid, nid, rel, finding_id=fid or None)

    node_list = list(nodes.values())[:limit_nodes]
    keep = {n["id"] for n in node_list}
    edge_list = [e for e in edges if e["source"] in keep and e["target"] in keep][
        :limit_edges
    ]
    kinds: dict[str, int] = {}
    for n in node_list:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    return {
        "nodes": node_list,
        "edges": edge_list,
        "stats": {
            "nodes": len(node_list),
            "edges": len(edge_list),
            "kinds": kinds,
            "findings_scanned": len(findings or []),
        },
        "q": q or "",
        "version": "kg.1",
    }


class KnowledgeGraphService:
    """Read-derived Knowledge Graph over findings (KG.1)."""

    name = "knowledge_graph"
    VERSION = "kg.1"

    def __init__(
        self,
        knowledge: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._logger = logger or logging.getLogger("atlas.knowledge.graph")

    def snapshot(
        self,
        *,
        q: str | None = None,
        domain: str | None = None,
        limit_findings: int = 200,
        limit_nodes: int = 80,
        limit_edges: int = 120,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        try:
            findings = self._knowledge.list_findings(
                domain=domain, limit=limit_findings
            ) or []
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("list_findings for graph failed: %s", exc)
        graph = build_knowledge_graph(
            findings,
            q=q,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
        graph["domain"] = domain
        return graph

    def context_nodes(
        self, topic: str, *, limit: int = 6
    ) -> list[dict[str, Any]]:
        """Compact nodes for Mission Context."""
        snap = self.snapshot(q=topic, limit_findings=100, limit_nodes=limit, limit_edges=20)
        out: list[dict[str, Any]] = []
        for n in snap.get("nodes") or []:
            out.append(
                {
                    "item_kind": "graph_node",
                    "id": n.get("id"),
                    "kind": n.get("kind"),
                    "label": n.get("label"),
                }
            )
            if len(out) >= limit:
                break
        return out
