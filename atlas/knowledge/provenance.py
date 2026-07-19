"""Provenance helpers for Findings / answers (Stage 3B close-out / A3B.12).

Provenance = embedded fields **and** parent edges. Minimum fields:

    entity_id, transform, component_id, component_version, ts, parent_ids
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from atlas.evidence.models import Claim, EvidenceItem


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _locator_parent_ids(locator: str) -> list[str]:
    """Parse structured locator tokens (``chunk:…``, ``document:…``, ``reader:…``)."""
    out: list[str] = []
    text = (locator or "").strip()
    if not text:
        return out
    for token in text.replace(",", " ").split():
        token = token.strip()
        if ":" not in token:
            continue
        kind, _, rest = token.partition(":")
        kind = kind.lower()
        if kind in {"chunk", "document", "reader", "source", "claim", "finding"} and rest:
            out.append(f"{kind}:{rest}")
    return out


def parent_ids_from_evidence(
    evidence: Sequence[EvidenceItem],
    *,
    documents: dict[str, Any] | None = None,
) -> list[str]:
    """Build parent id list from evidence items (+ optional Document map)."""
    parents: list[str] = []
    seen: set[str] = set()

    def add(pid: str) -> None:
        if pid and pid not in seen:
            seen.add(pid)
            parents.append(pid)

    docs = documents or {}
    for item in evidence:
        if item.source_id:
            add(f"source:{item.source_id}")
        for loc_id in _locator_parent_ids(item.locator):
            add(loc_id)
        doc = docs.get(item.source_id)
        if doc is None:
            continue
        if isinstance(doc, dict):
            did = doc.get("document_id") or doc.get("id")
            rid = doc.get("reader_id")
            cid = doc.get("chunk_id")
        else:
            did = getattr(doc, "document_id", None) or getattr(doc, "id", None)
            rid = getattr(doc, "reader_id", None)
            cid = getattr(doc, "chunk_id", None)
        if did:
            add(f"document:{did}")
        if cid:
            add(f"chunk:{cid}")
        if rid and str(rid) not in {"", "none"}:
            # A3B.17-style reader key with version suffix for provenance fixtures.
            name = "ocr" if str(rid) in {"pdf_ocr", "ocr"} else str(rid)
            add(f"reader:{name}@1")
    return parents


def provenance_edges(
    *,
    finding_id: str | None,
    claim_id: str | None,
    parent_ids: Sequence[str],
) -> list[dict[str, str]]:
    """Typed parent edges: Finding → Claim → sources/chunks/docs/readers."""
    edges: list[dict[str, str]] = []
    if finding_id and claim_id:
        edges.append(
            {
                "from": f"finding:{finding_id}",
                "to": f"claim:{claim_id}",
                "rel": "derived_from",
            }
        )
    origin = f"claim:{claim_id}" if claim_id else (f"finding:{finding_id}" if finding_id else "")
    if not origin:
        return edges
    for pid in parent_ids:
        if pid.startswith("claim:"):
            continue
        rel = "extracted_by" if pid.startswith("reader:") else "supported_by"
        edges.append({"from": origin, "to": pid, "rel": rel})
    return edges


def build_finding_provenance(
    claim: Claim,
    *,
    finding_id: str,
    job_id: str | None = None,
    objective: str = "",
    component: str = "synthesizer:v1",
    component_version: str = "1",
    documents: dict[str, Any] | None = None,
    transform: str = "claim_to_finding",
    versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full embedded provenance profile for a synthesized Finding.

    ``versions`` (P2 · ATLAS_OS_ROADMAP §2.6) records the real component/model builds
    (llm/embedding/reader/extractor/verifier/synthesizer + knowledge schema) that
    produced this finding, so a later model swap is a scoped re-derivation, not a
    rebuild. Omitted from the provenance when not supplied (back-compatible).
    """
    parent_ids: list[str] = []
    if claim.id:
        parent_ids.append(f"claim:{claim.id}")
    parent_ids.extend(
        parent_ids_from_evidence(claim.evidence, documents=documents)
    )
    # De-dupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in parent_ids:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    prov: dict[str, Any] = {
        "entity_id": f"finding:{finding_id}",
        "transform": transform,
        "component": component,
        "component_id": component,
        "component_version": component_version,
        "ts": _utcnow_iso(),
        "job_id": job_id,
        "objective": (objective or "")[:200],
        "claim_ids": [claim.id] if claim.id else [],
        "source_ids": [e.source_id for e in claim.evidence if e.source_id],
        "parent_ids": unique,
        "edges": provenance_edges(
            finding_id=finding_id, claim_id=claim.id or None, parent_ids=unique
        ),
    }
    if versions:
        prov["versions"] = dict(versions)
    return prov


def provenance_completeness_ids(prov: dict[str, Any]) -> list[str]:
    """Flatten provenance into the id set used by eval completeness."""
    ids: list[str] = []
    entity = prov.get("entity_id")
    if entity:
        ids.append(str(entity))
    for key in ("parent_ids", "claim_ids", "source_ids"):
        for item in prov.get(key) or []:
            text = str(item)
            if key == "claim_ids" and not text.startswith("claim:"):
                text = f"claim:{text}"
            elif key == "source_ids" and not text.startswith("source:"):
                text = f"source:{text}"
            ids.append(text)
    for edge in prov.get("edges") or []:
        if isinstance(edge, dict):
            for k in ("from", "to"):
                if edge.get(k):
                    ids.append(str(edge[k]))
    # unique
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def required_provenance_fields_present(prov: dict[str, Any]) -> list[str]:
    """Return which A3B.12 min fields are present on a provenance dict."""
    required = (
        "entity_id",
        "transform",
        "component_id",
        "component_version",
        "ts",
        "parent_ids",
    )
    present: list[str] = []
    for field in required:
        val = prov.get(field)
        if field == "component_id" and not val:
            val = prov.get("component")
        if val not in (None, "", [], {}):
            present.append(field)
    return present
