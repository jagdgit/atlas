"""IIP.5 — MKG queries: neighborhood, why-own, who-benefits."""

from __future__ import annotations

from typing import Any

from atlas.investment.mkg.schema import node_id, parse_node_id


def _nodes_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(graph.get("nodes") or {})


def _edges_list(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in (graph.get("edges") or []) if isinstance(e, dict)]


def neighborhood(
    graph: dict[str, Any],
    *,
    symbol: str | None = None,
    node: str | None = None,
    depth: int = 1,
    limit: int = 80,
) -> dict[str, Any]:
    """1-hop (or depth) neighborhood around a company or node id."""
    nodes = _nodes_map(graph)
    edges = _edges_list(graph)
    if symbol:
        root = node_id("company", symbol)
    elif node:
        root = node
    else:
        return {
            "nodes": [],
            "edges": [],
            "root": None,
            "status": "missing_query",
            "capability_gap": "Provide symbol= or node=",
        }
    if root not in nodes:
        return {
            "nodes": [],
            "edges": [],
            "root": root,
            "status": "unknown_relation",
            "capability_gap": f"No MKG node for {root} — seed or attach evidence first.",
        }

    depth = max(1, min(int(depth or 1), 3))
    frontier = {root}
    seen_nodes = {root}
    seen_edges: list[dict[str, Any]] = []
    for _ in range(depth):
        nxt: set[str] = set()
        for e in edges:
            s, t = e.get("source"), e.get("target")
            if s in frontier or t in frontier:
                if e not in seen_edges:
                    seen_edges.append(e)
                if s:
                    seen_nodes.add(str(s))
                    nxt.add(str(s))
                if t:
                    seen_nodes.add(str(t))
                    nxt.add(str(t))
            if len(seen_edges) >= limit:
                break
        frontier = nxt - {root} if depth > 1 else nxt
        if len(seen_edges) >= limit:
            break

    out_nodes = [nodes[n] for n in seen_nodes if n in nodes][:limit]
    return {
        "root": root,
        "nodes": out_nodes,
        "edges": seen_edges[:limit],
        "stats": {"nodes": len(out_nodes), "edges": min(len(seen_edges), limit)},
        "status": "ok",
    }


def who_benefits(
    graph: dict[str, Any],
    *,
    theme_id: str,
    limit: int = 40,
) -> dict[str, Any]:
    tid = (theme_id or "").strip()
    theme_nid = node_id("theme", tid) if not tid.startswith("theme:") else tid
    nodes = _nodes_map(graph)
    if theme_nid not in nodes:
        return {
            "theme_id": tid,
            "companies": [],
            "status": "unknown_relation",
            "capability_gap": f"Unknown theme {tid}",
        }
    companies: list[dict[str, Any]] = []
    for e in _edges_list(graph):
        if e.get("rel") != "benefits_from":
            continue
        if e.get("target") != theme_nid:
            continue
        kind, key = parse_node_id(str(e.get("source") or ""))
        if kind != "company":
            continue
        n = nodes.get(str(e.get("source"))) or {}
        companies.append(
            {
                "symbol": key,
                "label": n.get("label") or key,
                "role": e.get("role") or "",
                "source_label": e.get("source_label"),
                "edge_id": e.get("id"),
            }
        )
        if len(companies) >= limit:
            break
    # group by role
    by_role: dict[str, list[dict[str, Any]]] = {}
    for c in companies:
        by_role.setdefault(str(c.get("role") or "unspecified"), []).append(c)
    return {
        "theme_id": parse_node_id(theme_nid)[1],
        "theme": nodes.get(theme_nid),
        "companies": companies,
        "by_role": by_role,
        "count": len(companies),
        "status": "ok" if companies else "empty",
        "note": "Hermetic theme membership — not a live industry census.",
    }


def why_own(
    graph: dict[str, Any],
    symbol: str,
    *,
    financial_cites: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Templated ‘Why own/watch X?’ from theme/policy edges + optional financials."""
    sym_nid = node_id("company", symbol)
    nodes = _nodes_map(graph)
    kind, sym = parse_node_id(sym_nid)
    if sym_nid not in nodes:
        return {
            "symbol": sym,
            "status": "unknown_relation",
            "edges": [],
            "themes": [],
            "policies": [],
            "financial_cites": list(financial_cites or []),
            "unknown": ["No MKG company node — relation unknown (not invented)."],
            "capability_gap": f"No seeded MKG edges for {sym}",
            "summary": f"Atlas has no Market Knowledge Graph edges for {sym} yet.",
        }

    themes: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    for e in _edges_list(graph):
        if e.get("source") != sym_nid:
            continue
        if e.get("rel") not in {"benefits_from", "depends_on", "affected_by"}:
            continue
        tgt = str(e.get("target") or "")
        tk, tkey = parse_node_id(tgt)
        n = nodes.get(tgt) or {}
        row = {
            "rel": e.get("rel"),
            "target": tgt,
            "target_kind": tk,
            "target_key": tkey,
            "label": n.get("label") or tkey,
            "role": e.get("role"),
            "source_label": e.get("source_label"),
            "note": e.get("note"),
        }
        edge_rows.append(row)
        if tk == "theme":
            themes.append(row)
        elif tk == "policy":
            policies.append(row)

    fin = list(financial_cites or [])
    unknown: list[str] = []
    if not themes and not policies:
        unknown.append("No theme/policy edges — unknown relation (CapabilityGap).")
    if not fin:
        unknown.append("No imported fundamentals attached for this answer.")

    parts: list[str] = []
    if themes:
        labels = ", ".join(f"{t['label']}" + (f" ({t['role']})" if t.get("role") else "") for t in themes[:4])
        parts.append(f"Theme links: {labels}")
    if policies:
        labels = ", ".join(p["label"][:60] for p in policies[:3])
        parts.append(f"Policy links: {labels}")
    if fin:
        bits = []
        for f in fin[:4]:
            if f.get("field") and f.get("value") is not None:
                bits.append(f"{f['field']}={f['value']}")
        if bits:
            parts.append("Financial cites: " + ", ".join(bits))
    if not parts:
        summary = f"No MKG thesis for {sym} yet — do not invent supply-chain links."
    else:
        summary = f"Why watch/own {sym}: " + " · ".join(parts) + "."

    status = "ok" if (themes or policies) else "unknown_relation"
    return {
        "symbol": sym,
        "status": status,
        "edges": edge_rows,
        "themes": themes,
        "policies": policies,
        "financial_cites": fin,
        "unknown": unknown,
        "capability_gap": None if status == "ok" else f"Incomplete MKG for {sym}",
        "summary": summary,
        "note": "Answers cite labeled hermetic/catalog edges only — never invented.",
    }


def graph_view(graph: dict[str, Any], *, limit_nodes: int = 40, limit_edges: int = 60) -> dict[str, Any]:
    nodes = list((_nodes_map(graph)).values())[: max(1, int(limit_nodes))]
    edges = _edges_list(graph)[: max(1, int(limit_edges))]
    return {
        "version": graph.get("version"),
        "stats": graph.get("stats") or {"nodes": len(graph.get("nodes") or {}), "edges": len(graph.get("edges") or [])},
        "nodes": nodes,
        "edges": edges,
        "note": graph.get("note"),
        "seeded_at": graph.get("seeded_at"),
        "updated_at": graph.get("updated_at"),
    }
