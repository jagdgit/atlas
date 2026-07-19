"""Embedding nearest-neighbour identity for prose findings (Phase C · §C.3, CC4).

The Consolidator uses a deterministic ``identity_key`` for structured/engineering findings. For prose,
two statements can mean the same thing with different words. This resolver embeds a statement and finds
the nearest **active** finding above a similarity threshold — the "same logical finding" — so the
Consolidator merges evidence instead of storing a duplicate. Every decision is explainable
("merged with F-1928 @ 0.94").

Both the embedder (``.embed([text]) -> EmbeddingResponse``) and the repo (``.search`` / ``.upsert``)
are duck-typed, so this stays testable without a live model or DB.
"""

from __future__ import annotations

import logging
from typing import Any

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_THRESHOLD = 0.88  # cosine similarity; configurable + explainable


class EmbeddingIdentityResolver:
    def __init__(
        self,
        embedder: Any,
        repo: Any,
        *,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        logger: logging.Logger | None = None,
    ) -> None:
        self._embedder = embedder
        self._repo = repo
        self._model = model
        self._threshold = threshold
        self._logger = logger or logging.getLogger("atlas.knowledge.nn_identity")

    def _embed(self, text: str) -> list[float] | None:
        resp = self._embedder.embed([text])
        vectors = getattr(resp, "vectors", None)
        if not vectors:
            vectors = resp if isinstance(resp, (list, tuple)) else None
        if not vectors:
            return None
        return list(vectors[0])

    def resolve(
        self, statement: str, *, domain: str | None = None, exclude_id: str | None = None
    ) -> dict[str, Any] | None:
        """Return ``{finding_id, canonical_id, similarity}`` for the nearest match ≥ threshold."""
        statement = (statement or "").strip()
        if not statement:
            return None
        try:
            vec = self._embed(statement)
            if vec is None:
                return None
            hits = self._repo.search(
                vec, self._model, domains=[domain] if domain else None, limit=3
            )
        except Exception as exc:  # noqa: BLE001 - NN is best-effort; fall back to deterministic path
            self._logger.warning("nn resolve failed: %s", exc)
            return None
        for hit in hits:
            if exclude_id and str(hit.get("finding_id")) == str(exclude_id):
                continue
            similarity = 1.0 - float(hit.get("distance", 1.0))
            if similarity >= self._threshold:
                return {
                    "finding_id": str(hit["finding_id"]),
                    "canonical_id": hit.get("canonical_id"),
                    "similarity": round(similarity, 4),
                }
        return None

    def index(self, finding_id: str, statement: str) -> None:
        """Store the finding's statement embedding for future NN lookups (best-effort)."""
        statement = (statement or "").strip()
        if not statement:
            return
        try:
            vec = self._embed(statement)
            if vec is None:
                return
            self._repo.upsert(finding_id, self._model, vec)
        except Exception as exc:  # noqa: BLE001 - never block a write on indexing
            self._logger.warning("nn index failed for %s: %s", finding_id, exc)
