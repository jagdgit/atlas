"""RAG agent — retrieval-augmented question answering over the knowledge base.

Flow (ADR-0031):

    query
      -> knowledge.search(query, k)        [step: retrieve]
      -> keep chunks above similarity_floor
      -> assemble numbered context
      -> llm.chat([system, user])          [step: generate]
      -> answer with inline [n] citations + a trailing Sources list

The agent depends only on kernel services (KnowledgeService, LLMService) and the
AgentRunRepository — never on SQL or the Ollama client directly (ADR-0006/0030).
Every run and its steps are persisted for observability and recovery (ADR-0032).

Grounding is configurable (ADR-0035): "strict" answers only from retrieved context
(and says so when nothing relevant is found); "blended" also allows the model's own
knowledge, labelled as not sourced from the knowledge base.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from atlas.agents.base import AgentResult, Citation
from atlas.llm.provider import ChatMessage
from atlas.telemetry import get_metrics, start_span, timer

if TYPE_CHECKING:
    from atlas.knowledge.service import KnowledgeService, SearchResult
    from atlas.llm.service import LLMService
    from atlas.repositories.agent_run_repo import AgentRunRepository

_NO_CONTEXT_ANSWER = (
    "I don't have information about that in my knowledge base."
)


class RagAgent:
    name = "rag"
    kind = "rag"
    description = "Answers questions from the Atlas knowledge base (RAG)."

    def __init__(
        self,
        knowledge: "KnowledgeService",
        llm: "LLMService",
        run_repo: "AgentRunRepository | None" = None,
        *,
        retrieval_k: int = 5,
        similarity_floor: float = 0.35,
        max_context_chars: int = 6000,
        grounding: str = "strict",
        system_preamble: str = "You are Atlas, answering from the provided context.",
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._llm = llm
        self._run_repo = run_repo
        self._k = retrieval_k
        self._floor = similarity_floor
        self._max_context_chars = max_context_chars
        self._grounding = grounding
        self._preamble = system_preamble
        self._logger = logger or logging.getLogger("atlas.agent.rag")

    def config_snapshot(self) -> dict[str, Any]:
        return {
            "retrieval_k": self._k,
            "similarity_floor": self._floor,
            "max_context_chars": self._max_context_chars,
            "grounding": self._grounding,
        }

    # --- capability API -------------------------------------------------
    def run(self, query: str, **options: Any) -> AgentResult:
        k = int(options.get("k", self._k))
        floor = float(options.get("similarity_floor", self._floor))
        grounding = str(options.get("grounding", self._grounding))

        run_id = self._open_run(query, {"k": k, "floor": floor, "grounding": grounding})
        get_metrics().incr("agent.run", agent=self.name)
        with start_span("agent.rag.run", agent=self.name, grounding=grounding):
            try:
                with timer("agent.rag.retrieve"):
                    results = self._knowledge.search(query, limit=k)
                kept = [r for r in results if r.similarity >= floor]
                self._record_step(
                    run_id,
                    0,
                    "retrieve",
                    {
                        "query": query,
                        "k": k,
                        "floor": floor,
                        "hits": [
                            {"chunk_id": r.chunk_id, "similarity": round(r.similarity, 4)}
                            for r in results
                        ],
                        "kept": len(kept),
                    },
                )

                # Strict grounding with nothing relevant: short-circuit, no generation.
                if not kept and grounding == "strict":
                    result = AgentResult(
                        answer=_NO_CONTEXT_ANSWER,
                        citations=[],
                        usage={"retrieved": len(results), "used": 0},
                        run_id=run_id,
                    )
                    self._finish_run(run_id, result)
                    return result

                context, citations = self._assemble_context(kept)
                messages = self._build_messages(query, context, grounding)
                prompt_chars = sum(len(m.content) for m in messages)

                with timer("agent.rag.generate"):
                    response = self._llm.chat(messages)
                self._record_step(
                    run_id,
                    1,
                    "generate",
                    {
                        "model": response.model,
                        "prompt_chars": prompt_chars,
                        "usage": response.usage,
                    },
                )

                answer = self._with_sources(response.text.strip(), citations)
                result = AgentResult(
                    answer=answer,
                    citations=citations,
                    usage={
                        "model": response.model,
                        "retrieved": len(results),
                        "used": len(kept),
                        "prompt_chars": prompt_chars,
                        **response.usage,
                    },
                    run_id=run_id,
                )
                self._finish_run(run_id, result)
                return result
            except Exception as exc:  # noqa: BLE001 - record failure, then propagate
                error = f"{type(exc).__name__}: {exc}"
                get_metrics().incr("agent.run.failed", agent=self.name)
                if self._run_repo is not None and run_id is not None:
                    self._run_repo.fail_run(run_id, error)
                self._logger.exception("rag run failed for query: %s", query)
                raise

    # --- internals ------------------------------------------------------
    def _assemble_context(
        self, kept: "list[SearchResult]"
    ) -> tuple[str, list[Citation]]:
        blocks: list[str] = []
        citations: list[Citation] = []
        used_chars = 0
        for i, r in enumerate(kept, start=1):
            block = f"[{i}] {r.content}"
            # Always include the first source; otherwise respect the char cap.
            if i > 1 and used_chars + len(block) > self._max_context_chars:
                break
            blocks.append(block)
            used_chars += len(block)
            citations.append(
                Citation(
                    index=i,
                    document_id=r.document_id,
                    chunk_id=r.chunk_id,
                    similarity=r.similarity,
                    snippet=_snippet(r.content),
                )
            )
        return "\n\n".join(blocks), citations

    def _build_messages(
        self, query: str, context: str, grounding: str
    ) -> list[ChatMessage]:
        if grounding == "blended":
            rule = (
                "Prefer the numbered context and cite it inline as [n]. You may also "
                "use your own knowledge to fill gaps, but clearly mark any statement "
                "not supported by the context with '(not from knowledge base)'."
            )
        else:  # strict (default)
            rule = (
                "Answer using ONLY the numbered context below. Cite each source you "
                "use inline as [n], matching the context numbers. If the context does "
                "not contain the answer, say you don't have that information. Do not "
                "use outside knowledge."
            )
        system = f"{self._preamble} {rule}"
        user = (
            f"Context:\n{context or '(no context found)'}\n\n"
            f"Question: {query}"
        )
        return [ChatMessage("system", system), ChatMessage("user", user)]

    @staticmethod
    def _with_sources(answer: str, citations: list[Citation]) -> str:
        if not citations:
            return answer
        lines = [f"[{c.index}] {c.snippet}" for c in citations]
        return answer + "\n\nSources:\n" + "\n".join(lines)

    def _open_run(self, query: str, opts: dict[str, Any]) -> str | None:
        if self._run_repo is None:
            return None
        agent = self._run_repo.get_agent_by_name(self.name)
        row = self._run_repo.open_run(
            self.name,
            {"query": query, "options": opts},
            agent_id=agent["id"] if agent else None,
        )
        return str(row["id"])

    def _record_step(
        self, run_id: str | None, ordinal: int, kind: str, detail: dict[str, Any]
    ) -> None:
        if self._run_repo is None or run_id is None:
            return
        self._run_repo.add_step(run_id, ordinal, kind, detail)

    def _finish_run(self, run_id: str | None, result: AgentResult) -> None:
        if self._run_repo is None or run_id is None:
            return
        self._run_repo.finish_run(
            run_id,
            {
                "answer": result.answer,
                "citations": [c.as_dict() for c in result.citations],
                "usage": result.usage,
            },
        )


def _snippet(content: str, limit: int = 140) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
