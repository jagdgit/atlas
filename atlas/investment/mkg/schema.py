"""IIP.5 — Market Knowledge Graph schema (v1 subset).

Domain content for Market Program — not a second graph OS.
Missing relations → unknown / CapabilityGap; never invent supply chains.
"""

from __future__ import annotations

from typing import Any

VERSION = "iip.5.mkg"

NODE_KINDS = frozenset({"company", "theme", "policy", "industry"})
EDGE_RELS = frozenset(
    {
        "benefits_from",
        "depends_on",
        "affected_by",
        "regulates",
    }
)

SOURCE_HERMETIC = "hermetic_seed"
SOURCE_THEME = "hermetic_theme_seed"
SOURCE_CATALOG = "catalog"
SOURCE_FUNDAMENTALS = "fundamentals_join"
SOURCE_DOCS = "company_document"
SOURCE_POLICY = "government_policy"


def node_id(kind: str, key: str) -> str:
    k = (kind or "").strip().lower()
    key_n = (key or "").strip()
    if k == "company":
        s = key_n.upper()
        if s and not s.endswith(".NS") and "." not in s:
            s = f"{s}.NS"
        return f"company:{s}"
    return f"{k}:{key_n}"


def parse_node_id(nid: str) -> tuple[str, str]:
    if ":" not in (nid or ""):
        return "", nid or ""
    kind, key = nid.split(":", 1)
    return kind, key


def make_node(
    kind: str,
    key: str,
    *,
    label: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind_n = (kind or "").strip().lower()
    if kind_n not in NODE_KINDS:
        raise ValueError(f"unknown node kind: {kind}")
    nid = node_id(kind_n, key)
    _, key_n = parse_node_id(nid)
    out: dict[str, Any] = {
        "id": nid,
        "kind": kind_n,
        "key": key_n,
        "label": label or key_n,
    }
    if meta:
        out["meta"] = meta
    return out


def make_edge(
    source: str,
    target: str,
    rel: str,
    *,
    source_label: str = SOURCE_HERMETIC,
    as_of: str = "",
    confidence: str = "low",
    role: str = "",
    note: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rel_n = (rel or "").strip().lower()
    if rel_n not in EDGE_RELS:
        raise ValueError(f"unknown edge rel: {rel}")
    edge: dict[str, Any] = {
        "id": f"{source}|{rel_n}|{target}",
        "source": source,
        "target": target,
        "rel": rel_n,
        "source_label": source_label,
        "as_of": as_of,
        "confidence": confidence,
    }
    if role:
        edge["role"] = role
    if note:
        edge["note"] = note
    if meta:
        edge["meta"] = meta
    return edge


def empty_graph() -> dict[str, Any]:
    return {
        "version": VERSION,
        "nodes": {},
        "edges": [],
        "stats": {"nodes": 0, "edges": 0},
        "note": (
            "Market Knowledge Graph v1 — hermetic theme/policy/company edges. "
            "Missing relations are unknown, never invented."
        ),
    }
