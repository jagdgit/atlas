"""Engineering Intelligence subsystem (Phase B).

Grows the narrow Code store into the roadmap pipeline — **Asset → Reader → Artifact →
Extraction → Knowledge** — starting with B.1: asset-backed repository acquisition with a
stable Repository UUID (BB12) and an Asset Store provenance link (P8, Assets ≠ Knowledge).

Everything here is a **stateless translator** per constitution P11 — it turns assets into
structured products, and never owns knowledge, missions, or decisions.
"""

from __future__ import annotations

from atlas.engineering.ingest import (
    AcquiredRepo,
    RepoAcquireError,
    RepoAcquirer,
    compute_tree_checksum,
)

__all__ = [
    "AcquiredRepo",
    "RepoAcquireError",
    "RepoAcquirer",
    "compute_tree_checksum",
]
