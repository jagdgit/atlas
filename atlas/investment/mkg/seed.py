"""IIP.5 — hermetic MKG seed from themes + gov policy + Waaree-style stubs."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from atlas.investment.mkg.schema import (
    SOURCE_CATALOG,
    SOURCE_HERMETIC,
    SOURCE_THEME,
    empty_graph,
    make_edge,
    make_node,
    node_id,
)
from atlas.investment.mkg.store import save_graph, upsert_edge, upsert_node

# Theme policy_hints → government_policy catalog ids
HINT_TO_POLICY: dict[str, str] = {
    "digital_india": "digital_india_fintech",
    "power_capex": "budget_infra_capex",
    "energy_transition": "renewable_energy_push",
    "pli": "pli_electronics_auto",
    "defence": "defence_indigenisation",
    "ev": "pli_electronics_auto",
    "pharma": "pharma_api_incentives",
    "rail": "budget_infra_capex",
    "infra": "budget_infra_capex",
    "housing": "housing_urban",
}

# Explicit Done-when demo edges (not inventing full supply chains)
_EXTRA_COMPANY_EDGES: tuple[dict[str, Any], ...] = (
    {
        "symbol": "WAAREE.NS",
        "label": "Waaree Energies",
        "theme_id": "green_energy",
        "role": "epc_equipment",
        "policy_id": "renewable_energy_push",
        "note": "Hermetic demo: solar manufacturer benefits from green energy theme + renewable policy",
    },
    {
        "symbol": "TATAPOWER.NS",
        "label": "Tata Power",
        "theme_id": "green_energy",
        "role": "utilities",
        "policy_id": "renewable_energy_push",
        "note": "Utility with renewable exposure (hermetic)",
    },
)


def build_seed_graph() -> dict[str, Any]:
    """Build in-memory graph from themes + policy catalog + extra stubs."""
    from atlas.investment.government_policy import DEFAULT_POLICY_CATALOG
    from atlas.investment.themes import list_themes

    graph = empty_graph()
    as_of = time.strftime("%Y-%m-%d", time.gmtime())

    # Policy nodes
    for pol in DEFAULT_POLICY_CATALOG:
        upsert_node(
            graph,
            make_node(
                "policy",
                str(pol["id"]),
                label=str(pol.get("title") or pol["id"]),
                meta={
                    "kind": pol.get("kind"),
                    "sectors": list(pol.get("sectors") or []),
                    "summary": pol.get("summary"),
                    "source": pol.get("source") or SOURCE_CATALOG,
                },
            ),
        )

    # Theme nodes + company edges + theme→policy
    for theme in list_themes():
        tid = str(theme["theme_id"])
        upsert_node(
            graph,
            make_node(
                "theme",
                tid,
                label=str(theme.get("label") or tid),
                meta={
                    "hypothesis": theme.get("hypothesis"),
                    "horizon_default": theme.get("horizon_default"),
                    "status": theme.get("status"),
                },
            ),
        )
        theme_nid = node_id("theme", tid)
        symbols = theme.get("symbols_by_role") or {}
        if isinstance(symbols, dict):
            for role, syms in symbols.items():
                for sym in syms or []:
                    upsert_node(
                        graph,
                        make_node("company", str(sym), label=str(sym)),
                    )
                    upsert_edge(
                        graph,
                        make_edge(
                            node_id("company", str(sym)),
                            theme_nid,
                            "benefits_from",
                            source_label=SOURCE_THEME,
                            as_of=as_of,
                            role=str(role),
                            note=f"Theme seed role={role}",
                        ),
                    )
        elif isinstance(theme.get("symbols"), list):
            for sym in theme["symbols"]:
                upsert_node(
                    graph,
                    make_node("company", str(sym), label=str(sym)),
                )
                upsert_edge(
                    graph,
                    make_edge(
                        node_id("company", str(sym)),
                        theme_nid,
                        "benefits_from",
                        source_label=SOURCE_THEME,
                        as_of=as_of,
                        note="Theme seed membership",
                    ),
                )
        for hint in theme.get("policy_hints") or []:
            pid = HINT_TO_POLICY.get(str(hint).strip().lower())
            if not pid:
                continue
            upsert_edge(
                graph,
                make_edge(
                    theme_nid,
                    node_id("policy", pid),
                    "benefits_from",
                    source_label=SOURCE_THEME,
                    as_of=as_of,
                    note=f"Theme policy_hint={hint}",
                ),
            )
            # Sparse regulates: policy → theme
            upsert_edge(
                graph,
                make_edge(
                    node_id("policy", pid),
                    theme_nid,
                    "regulates",
                    source_label=SOURCE_CATALOG,
                    as_of=as_of,
                    note=f"Catalog policy linked via hint={hint}",
                ),
            )

    # Extra hermetic stubs (Waaree-style)
    for row in _EXTRA_COMPANY_EDGES:
        sym = str(row["symbol"])
        upsert_node(
            graph,
            make_node("company", sym, label=str(row.get("label") or sym)),
        )
        upsert_edge(
            graph,
            make_edge(
                node_id("company", sym),
                node_id("theme", str(row["theme_id"])),
                "benefits_from",
                source_label=SOURCE_HERMETIC,
                as_of=as_of,
                role=str(row.get("role") or ""),
                note=str(row.get("note") or ""),
            ),
        )
        upsert_edge(
            graph,
            make_edge(
                node_id("company", sym),
                node_id("policy", str(row["policy_id"])),
                "benefits_from",
                source_label=SOURCE_HERMETIC,
                as_of=as_of,
                note=str(row.get("note") or ""),
            ),
        )
        upsert_edge(
            graph,
            make_edge(
                node_id("company", sym),
                node_id("policy", str(row["policy_id"])),
                "affected_by",
                source_label=SOURCE_HERMETIC,
                as_of=as_of,
                confidence="low",
            ),
        )

    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []
    graph["stats"] = {"nodes": len(nodes), "edges": len(edges)}
    graph["seeded_at"] = as_of
    return graph


def ensure_seeded(data_dir: str | Path | None, *, force: bool = False) -> dict[str, Any]:
    """Load graph or build+save seed when missing / force."""
    from atlas.investment.mkg.store import load_graph, store_path

    if data_dir and not force:
        path = store_path(data_dir)
        if path.is_file():
            g = load_graph(data_dir)
            if (g.get("stats") or {}).get("edges", 0) > 0:
                return g
    graph = build_seed_graph()
    if data_dir:
        save_graph(data_dir, graph)
    return graph
