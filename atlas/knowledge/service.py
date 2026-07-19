"""Knowledge service — ingestion, embedding, and Knowledge Access Layer.

Ties together the knowledge repositories, the chunker, and the LLM service:

    ingest_text -> document (dedup) -> chunks -> embeddings -> status 'embedded'
    retrieve(query, role=…) -> dense + lexical → RRF → re-rank → context

``search`` remains dense-only for back-compat; chat/research/API use ``retrieve``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from uuid import UUID

from atlas.exceptions import EmbeddingMismatchError
from atlas.knowledge.access import (
    RankedContext,
    RankedHit,
    TIER_EXPERIENCE,
    TIER_KNOWLEDGE,
    archive_requested,
    build_context,
    domains_for_role,
    fuse_dense_lexical,
    heuristic_rerank,
    normalize_tiers,
    partition_tiers,
)
from atlas.knowledge.chunking import chunk_text
from atlas.telemetry import timed, timer

if TYPE_CHECKING:
    from atlas.llm.service import LLMService
    from atlas.models import Document
    from atlas.repositories.chunk_repo import ChunkRepository
    from atlas.repositories.document_repo import DocumentRepository
    from atlas.repositories.embedding_repo import EmbeddingRepository
    from atlas.repositories.retrieval_diagnostics_repo import (
        RetrievalDiagnosticsRepository,
    )


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    distance: float
    similarity: float  # 1 - cosine distance
    dense_score: float | None = None
    lexical_score: float | None = None
    rrf_score: float | None = None


class KnowledgeService:
    name = "knowledge"

    def __init__(
        self,
        documents: "DocumentRepository",
        chunks: "ChunkRepository",
        embeddings: "EmbeddingRepository",
        llm: "LLMService",
        *,
        embedding_model: str,
        chunk_max_words: int = 200,
        chunk_overlap: int = 40,
        embed_batch: int = 32,
        rrf_k: int = 60,
        candidate_multiplier: int = 2,
        max_context_chars: int = 6000,
        retrieval_mode: str = "hybrid",
        persist_diagnostics: bool = True,
        diagnostics: "RetrievalDiagnosticsRepository | None" = None,
        learning: Any = None,
        policy: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._embeddings = embeddings
        self._llm = llm
        self._model = embedding_model
        self._chunk_max_words = chunk_max_words
        self._chunk_overlap = chunk_overlap
        self._embed_batch = embed_batch
        self._rrf_k = rrf_k
        self._candidate_multiplier = max(1, candidate_multiplier)
        self._max_context_chars = max_context_chars
        self._retrieval_mode = retrieval_mode
        self._persist_diagnostics = persist_diagnostics
        self._diagnostics = diagnostics
        # Optional LearningService: soft-bias terms after apply+enable (D3B.12).
        self._learning = learning
        # Optional PolicyService: signed operator-policy influence on ranking (C.5/CC8).
        self._policy = policy
        self._logger = logger or logging.getLogger("atlas.knowledge")

    # --- ingestion ------------------------------------------------------
    def ingest_text(
        self,
        source: str,
        content: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        content_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
        domain: str = "external",
        embed: bool = True,
        asset_id: str | None = None,
        asset_version: int | None = None,
    ) -> dict[str, Any]:
        """Ingest raw text: dedup, chunk, and (optionally) embed inline.

        ``domain`` (Stage 3 / D3.13) tags the knowledge universe so retrieval can
        stay scoped — Researcher defaults to external/research/experience.
        ``asset_id``/``asset_version`` (Phase C / §C.2) record the source Asset the text
        was read from, so retrieval results are traceable back to raw bytes (P9).
        """
        document = self._documents.create(
            source,
            content,
            uri=uri,
            title=title,
            content_type=content_type,
            metadata=metadata,
            domain=domain,
            asset_id=asset_id,
            asset_version=asset_version,
        )
        doc_id = document.id

        # Dedup hit that is already embedded: nothing to do.
        if document.status == "embedded":
            return self._summary(doc_id, deduped=True)

        pieces = chunk_text(
            content,
            max_words=self._chunk_max_words,
            overlap=self._chunk_overlap,
        )
        self._chunks.add_many(
            doc_id,
            [
                {
                    "ordinal": p.ordinal,
                    "content": p.content,
                    "token_count": p.token_count,
                }
                for p in pieces
            ],
        )
        self._documents.set_status(doc_id, "chunked")

        if embed:
            self.embed_document(doc_id)

        return self._summary(doc_id, deduped=False)

    @timed("knowledge.embed_document")
    def embed_document(self, document_id: UUID | str) -> dict[str, Any]:
        """Embed all chunks of a document and mark it 'embedded'.

        Idempotent: embeddings are upserted per (chunk, model), so re-running
        after an interruption simply overwrites.
        """
        chunks = self._chunks.list_for_document(document_id)
        if not chunks:
            self._documents.set_status(document_id, "failed")
            self._logger.warning("no chunks for document %s", document_id)
            return self._summary(document_id, deduped=False)

        embedded = 0
        for start in range(0, len(chunks), self._embed_batch):
            batch = chunks[start : start + self._embed_batch]
            vectors = self._llm.embed(
                [c["content"] for c in batch], model=self._model
            ).vectors
            if len(vectors) != len(batch):
                self._documents.set_status(document_id, "failed")
                raise EmbeddingMismatchError(
                    f"embedding count mismatch: got {len(vectors)} for {len(batch)} chunks",
                    document_id=str(document_id),
                    expected=len(batch),
                    got=len(vectors),
                )
            for chunk, vector in zip(batch, vectors):
                self._embeddings.upsert(chunk["id"], self._model, vector)
                embedded += 1

        self._documents.set_status(document_id, "embedded")
        self._logger.info("embedded %d chunk(s) for document %s", embedded, document_id)
        return self._summary(document_id, deduped=False)

    # --- catalog --------------------------------------------------------
    def list_documents(self, *, limit: int = 50) -> list["Document"]:
        """List documents in the knowledge base (newest first)."""
        return self._documents.recent(limit=limit)

    def document_count(self) -> int:
        return self._documents.count()

    def list_findings(
        self,
        *,
        domain: str | None = None,
        limit: int = 50,
        include_archive: bool = False,
    ) -> list[dict[str, Any]]:
        """Active head revisions only unless ``include_archive`` (D3B.21)."""
        repo = getattr(self, "_findings", None)
        if repo is None or not hasattr(repo, "list_active"):
            return []
        return repo.list_active(
            domain=domain, limit=limit, include_archive=include_archive
        )

    # --- retrieval ------------------------------------------------------
    def search(
        self, query: str, *, limit: int = 5, domains: list[str] | None = None
    ) -> list[SearchResult]:
        """Dense-only semantic search (legacy). Prefer ``retrieve`` for Access Layer."""
        with timer("knowledge.search"):
            rows = self._dense_rows(query, limit=limit, domains=domains)
        return [
            SearchResult(
                chunk_id=str(r["chunk_id"]),
                document_id=str(r["document_id"]),
                ordinal=r["ordinal"],
                content=r["content"],
                distance=float(r["distance"]),
                similarity=1.0 - float(r["distance"]),
                dense_score=1.0 - float(r["distance"]),
            )
            for r in rows
        ]

    def retrieve(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        tiers: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        as_of: str | None = None,
        role: str = "research",
        k: int | None = None,
        mode: str | None = None,
        soft_bias_terms: list[str] | None = None,
    ) -> RankedContext:
        """Global Access Layer entrypoint (D3B.6 / A3B.24).

        Pipeline: Retrieve → Re-rank → Context Build. Callers (chat, research, …)
        pass ``role``; do not invent per-surface retrieve APIs.

        ``soft_bias_terms`` is optional and should only come from experiences that
        were applied *and* explicitly bias-enabled (D3B.12 / A3B.18). When omitted,
        terms are loaded from the wired LearningService (if any).
        """
        del filters, as_of  # reserved for 3B.3 temporal/lifecycle filters
        limit = int(k if k is not None else 5)
        resolved_mode = (mode or self._retrieval_mode or "hybrid").lower()
        resolved_domains = domains_for_role(role, domains)
        requested_tiers = normalize_tiers(tiers)
        live_tiers, deferred_tiers = partition_tiers(requested_tiers)
        resolved_tiers = live_tiers or [TIER_KNOWLEDGE]
        # Experience domain is included when the experience tier is requested.
        search_domains = list(resolved_domains) if resolved_domains is not None else None
        if TIER_EXPERIENCE in requested_tiers and search_domains is not None:
            if "experience" not in search_domains:
                search_domains = [*search_domains, "experience"]

        bias_terms = soft_bias_terms
        if bias_terms is None:
            bias_terms = self._soft_bias_terms()
        policy_rules = self._policy_rules(role)

        with timer("knowledge.retrieve"):
            candidate_n = max(limit * self._candidate_multiplier, limit)
            dense_rows: list[dict[str, Any]] = []
            lexical_rows: list[dict[str, Any]] = []

            if resolved_mode in {"hybrid", "dense"} and TIER_KNOWLEDGE in resolved_tiers:
                dense_rows = self._dense_rows(
                    query, limit=candidate_n, domains=search_domains
                )
            if resolved_mode in {"hybrid", "lexical"} and TIER_KNOWLEDGE in resolved_tiers:
                lexical_rows = self._lexical_rows(
                    query, limit=candidate_n, domains=search_domains
                )

            if resolved_mode == "dense":
                hits = [
                    RankedHit(
                        chunk_id=str(r["chunk_id"]),
                        document_id=str(r["document_id"]),
                        ordinal=int(r["ordinal"]),
                        content=str(r["content"]),
                        dense_score=1.0 - float(r["distance"]),
                        lexical_score=None,
                        rrf_score=1.0 - float(r["distance"]),
                        score=1.0 - float(r["distance"]),
                        distance=float(r["distance"]),
                        similarity=1.0 - float(r["distance"]),
                        tier=TIER_KNOWLEDGE,
                    )
                    for r in dense_rows
                ]
            elif resolved_mode == "lexical":
                hits = [
                    RankedHit(
                        chunk_id=str(r["chunk_id"]),
                        document_id=str(r["document_id"]),
                        ordinal=int(r["ordinal"]),
                        content=str(r["content"]),
                        dense_score=None,
                        lexical_score=float(r.get("rank", 0.0)),
                        rrf_score=float(r.get("rank", 0.0)),
                        score=float(r.get("rank", 0.0)),
                        distance=None,
                        similarity=None,
                        tier=TIER_KNOWLEDGE,
                    )
                    for r in lexical_rows
                ]
            else:
                hits = fuse_dense_lexical(
                    dense_rows, lexical_rows, rrf_k=self._rrf_k
                )

            # Archive excluded unless explicitly requested (D3B.21).
            if not archive_requested(requested_tiers):
                hits = [h for h in hits if h.tier != "archive"]

            ranked = heuristic_rerank(
                hits, query, soft_bias_terms=bias_terms, policy_rules=policy_rules
            )[:limit]
            context, citations = build_context(
                ranked, max_chars=self._max_context_chars
            )

            diagnostics_id = self._maybe_persist_diagnostics(
                query,
                ranked,
                role=role,
                mode=resolved_mode,
                domains=search_domains,
                tiers=requested_tiers,
            )

        return RankedContext(
            query=query,
            hits=tuple(ranked),
            context=context,
            citations=tuple(citations),
            role=role,
            domains=tuple(search_domains or ()),
            tiers=tuple(requested_tiers),
            mode=resolved_mode,
            diagnostics_id=diagnostics_id,
            meta={
                "dense_candidates": len(dense_rows),
                "lexical_candidates": len(lexical_rows),
                "archive_excluded": not archive_requested(requested_tiers),
                "findings_heads_only": not archive_requested(requested_tiers),
                "live_tiers": list(resolved_tiers),
                "deferred_tiers": list(deferred_tiers),
                "soft_bias_term_count": len(bias_terms or []),
                "policy_rules_considered": len(policy_rules),
                "policy_rules_applied": sorted(
                    {pid for h in ranked for pid in h.policy_ids}
                ),
            },
        )

    def _soft_bias_terms(self) -> list[str]:
        learning = getattr(self, "_learning", None)
        if learning is None or not hasattr(learning, "soft_bias_terms"):
            return []
        try:
            return list(learning.soft_bias_terms() or [])
        except Exception:  # noqa: BLE001 — bias must never break retrieve
            self._logger.debug("soft_bias_terms failed", exc_info=True)
            return []

    def _policy_rules(self, role: str) -> list[dict[str, Any]]:
        policy = getattr(self, "_policy", None)
        if policy is None or not hasattr(policy, "retrieval_influence"):
            return []
        try:
            return list(policy.retrieval_influence() or [])
        except Exception:  # noqa: BLE001 — policy must never break retrieve
            self._logger.debug("policy influence failed", exc_info=True)
            return []

    # --- scheduler integration -----------------------------------------
    def embed_document_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scheduler handler for task_type 'embed_document'."""
        return self.embed_document(payload["document_id"])

    # --- internals ------------------------------------------------------
    def _dense_rows(
        self, query: str, *, limit: int, domains: list[str] | None
    ) -> list[dict[str, Any]]:
        if not (query or "").strip() or limit <= 0:
            return []
        vector = self._llm.embed([query], model=self._model).vectors[0]
        return self._embeddings.search(
            vector, self._model, limit=limit, domains=domains
        )

    def _lexical_rows(
        self, query: str, *, limit: int, domains: list[str] | None
    ) -> list[dict[str, Any]]:
        if not hasattr(self._chunks, "search_lexical"):
            return []
        try:
            return self._chunks.search_lexical(query, limit=limit, domains=domains)
        except Exception as exc:  # noqa: BLE001 — lexical is best-effort in hybrid
            self._logger.warning("lexical search failed: %s", exc)
            return []

    def _maybe_persist_diagnostics(
        self,
        query: str,
        hits: list[RankedHit],
        *,
        role: str,
        mode: str,
        domains: list[str] | None,
        tiers: list[str],
    ) -> str | None:
        if not self._persist_diagnostics or self._diagnostics is None:
            return None
        try:
            payload = [
                {
                    "chunk_id": h.chunk_id,
                    "document_id": h.document_id,
                    "dense_score": h.dense_score,
                    "lexical_score": h.lexical_score,
                    "rrf_score": h.rrf_score,
                    "score": h.score,
                }
                for h in hits
            ]
            row = self._diagnostics.record(
                query,
                payload,
                role=role,
                mode=mode,
                domains=domains,
                tiers=tiers,
            )
            return str(row["id"]) if row else None
        except Exception as exc:  # noqa: BLE001 — never fail retrieve on diagnostics
            self._logger.warning("retrieval diagnostics persist failed: %s", exc)
            return None

    def _summary(self, document_id: UUID | str, *, deduped: bool) -> dict[str, Any]:
        doc = self._documents.get(document_id)
        return {
            "document_id": str(document_id),
            "status": doc.status if doc else "unknown",
            "chunks": self._chunks.count_for_document(document_id),
            "deduped": deduped,
        }
