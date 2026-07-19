"""CodeService — the `code` capability (S14, Tier B).

One service over the code toolchain: parse a file, map a repo, build the symbol
index + import/call graph, mine patterns, search symbols, and (optionally) push
code-aware chunks into the knowledge base for semantic code search. The ``code``-role
LLM (D7) explains/reviews **grounded on the parsed structure** (curbs hallucination).

Repo scans are parsed once and cached per root; `index(refresh=True)` re-scans.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.code.graph import build_graph
from atlas.code.languages import language_for, supported_languages
from atlas.code.models import KIND_CLASS, FileParse
from atlas.code.parser import CodeParser
from atlas.code.patterns import mine_patterns
from atlas.code.repomap import (
    DEFAULT_IGNORES,
    build_repo_map,
    iter_source_files,
    read_manifests,
)
from atlas.llm.provider import ChatMessage
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.engineering.readers import ReaderRegistry
    from atlas.knowledge.service import KnowledgeService
    from atlas.llm.service import LLMService

_EXPLAIN_SYSTEM = (
    "You are Atlas's code expert. Explain or review the code strictly from the "
    "parsed structure and source provided. Be concrete about functions, classes, "
    "imports, and relationships. Do not invent APIs or behaviour that isn't shown."
)


class CodeService:
    name = "code"

    # Reader/artifact version (P2/BB8): bump on a material change to what the code reader
    # extracts (symbols/imports/graph). Stamped onto engineering findings + derived artifacts
    # so knowledge stays comparable across time and a reader upgrade is a visible version delta.
    VERSION = "1.0.0"

    def __init__(
        self,
        parser: CodeParser | None = None,
        *,
        knowledge: "KnowledgeService | None" = None,
        llm: "LLMService | None" = None,
        readers: "ReaderRegistry | None" = None,
        max_file_bytes: int = 1_048_576,
        max_files: int = 5000,
        ignores: frozenset[str] = DEFAULT_IGNORES,
        logger: logging.Logger | None = None,
    ) -> None:
        self._parser = parser or CodeParser(max_file_bytes=max_file_bytes)
        self._knowledge = knowledge
        self._llm = llm
        self._readers = readers
        self._max_files = max_files
        self._ignores = ignores
        self._logger = logger or logging.getLogger("atlas.code")
        self._cache: dict[str, tuple[list[FileParse], dict[str, str]]] = {}

    # --- capability API -------------------------------------------------
    def supported(self) -> list[str]:
        return supported_languages()

    def parse(self, path: str) -> dict[str, Any]:
        """Parse a single file → structural facts (symbols/imports/calls)."""
        return self._parser.parse_file(path).as_dict()

    def repo_map(self, root: str) -> dict[str, Any]:
        parses, manifests = self._scan(root)
        return build_repo_map(Path(root).resolve(), parses, manifests).as_dict()

    def graph(self, root: str) -> dict[str, Any]:
        parses, _ = self._scan(root)
        return build_graph(parses).as_dict()

    def patterns(self, root: str) -> list[dict[str, Any]]:
        parses, manifests = self._scan(root)
        repo_map = build_repo_map(Path(root).resolve(), parses, manifests)
        return [p.as_dict() for p in mine_patterns(repo_map, parses)]

    def search_symbols(
        self,
        query: str,
        *,
        root: str,
        kind: str | None = None,
        lang: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        parses, _ = self._scan(root)
        q = (query or "").lower()
        hits = []
        for fp in parses:
            if lang and fp.lang != lang:
                continue
            for sym in fp.symbols:
                if kind and sym.kind != kind:
                    continue
                if q and q not in sym.name.lower() and q not in sym.qualname.lower():
                    continue
                hits.append(sym.as_dict())
                if len(hits) >= limit:
                    return hits
        return hits

    def index(
        self,
        root: str,
        *,
        ingest: bool = False,
        refresh: bool = False,
        embed_cap: int | None = None,
    ) -> dict[str, Any]:
        """Parse the whole repo, build the graph, and optionally ingest code chunks.

        ``embed_cap`` bounds how many code chunks are embedded (Q-B4); chunks are ingested
        in **priority order** (public API → frequently-imported → symbol-rich → rest) so a
        capped run keeps the most useful code searchable.
        """
        if refresh:
            self._cache.pop(str(Path(root).resolve()), None)
        parses, manifests = self._scan(root)
        repo_map = build_repo_map(Path(root).resolve(), parses, manifests)
        graph = build_graph(parses)
        symbol_count = sum(len(fp.symbols) for fp in parses)
        ingested = 0
        if ingest and self._knowledge is not None:
            ingested = self._ingest_code(
                Path(root).resolve(), parses, graph=graph, embed_cap=embed_cap
            )
        return {
            "root": repo_map.root,
            "files": repo_map.file_count,
            "symbols": symbol_count,
            "languages": repo_map.languages,
            "frameworks": repo_map.frameworks,
            "graph": graph.as_dict(),
            "ingested_chunks": ingested,
        }

    def artifact(
        self, root: str, *, symbol_limit: int = 200, refresh: bool = False
    ) -> dict[str, Any]:
        """Reader → **Artifact** (BB11): parse the repo once into a cacheable derived product.

        Returns the structured facts the extractor consumes (repo map, import/call graph,
        mined patterns, a bounded symbol list) plus the reader identity. Caching this against
        the asset version lets extraction improve later **without re-parsing** (P11).

        ``refresh`` drops the in-memory parse cache first, so a re-ingest of the *same local
        path* whose files changed on disk is re-parsed rather than served stale (the Derived
        Artifact Store is the authoritative cross-run cache, keyed by asset version).
        """
        if refresh:
            self._cache.pop(str(Path(root).resolve()), None)
        parses, manifests = self._scan(root)
        resolved = Path(root).resolve()
        repo_map = build_repo_map(resolved, parses, manifests)
        graph = build_graph(parses)
        symbols: list[dict[str, Any]] = []
        for fp in parses:
            for sym in fp.symbols:
                symbols.append(
                    {"qualname": sym.qualname, "kind": sym.kind, "file": fp.path, "lang": fp.lang}
                )
                if len(symbols) >= symbol_limit:
                    break
            if len(symbols) >= symbol_limit:
                break
        languages = sorted({fp.lang for fp in parses})
        return {
            "root": repo_map.root,
            "reader": "code",
            "reader_version": self.VERSION,
            "repo_map": repo_map.as_dict(),
            "graph": graph.as_dict(),
            "patterns": [p.as_dict() for p in mine_patterns(repo_map, parses)],
            "symbols": symbols,
            "symbol_count": sum(len(fp.symbols) for fp in parses),
            # Honest per-language reader attribution + coverage (BB10): which reader handled
            # each language and what it can/can't extract (e.g. no JS/TS call graph — declared,
            # not silently empty).
            "readers": self._reader_attribution(languages),
        }

    def _reader_attribution(self, languages: list[str]) -> list[dict[str, Any]]:
        """Per-language reader id/version + coverage from the Reader Registry (BB10)."""
        if self._readers is None:
            return []
        out: list[dict[str, Any]] = []
        for lang in languages:
            reader = self._readers.reader_for_language(lang)
            if reader is None:
                out.append({"language": lang, "reader": None, "reason": "no reader"})
                continue
            out.append({
                "language": lang,
                "reader": reader.id,
                "reader_version": reader.version,
                "coverage": {c: reader.supports(c) for c in reader.coverage},
                "call_graph": reader.supports("call_graph"),
            })
        return out

    def explain(self, path: str, question: str | None = None) -> dict[str, Any]:
        """LLM explanation of a file, grounded on its parsed structure."""
        fp = self._parser.parse_file(path)
        outline = self._outline(fp)
        if self._llm is None:
            return {"path": path, "outcome": fp.outcome, "outline": outline,
                    "explanation": "", "grounded": True}
        try:
            source = Path(path).read_text(encoding="utf-8", errors="replace")[:6000]
        except OSError:
            source = ""
        ask = question or "Explain what this file does and how it is structured."
        user = f"{ask}\n\nParsed structure:\n{outline}\n\nSource (truncated):\n{source}"
        try:
            text = self._llm.for_role("code").chat(
                [ChatMessage("system", _EXPLAIN_SYSTEM), ChatMessage("user", user)]
            ).text.strip()
        except Exception:  # noqa: BLE001 - never let explanation crash the call
            self._logger.exception("code explanation failed")
            text = ""
        return {"path": path, "outcome": fp.outcome, "outline": outline,
                "explanation": text, "grounded": True}

    # --- internals ------------------------------------------------------
    def _scan(self, root: str) -> tuple[list[FileParse], dict[str, str]]:
        resolved = Path(root).resolve()
        key = str(resolved)
        if key in self._cache:
            return self._cache[key]
        if not resolved.is_dir():
            raise NotADirectoryError(f"not a directory: {root}")
        parses: list[FileParse] = []
        for abs_path in iter_source_files(
            resolved, ignores=self._ignores, max_files=self._max_files
        ):
            rel = abs_path.relative_to(resolved).as_posix()
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self._logger.debug("skip unreadable %s: %s", rel, exc)
                continue
            parses.append(self._parser.parse_text(text, rel, language_for(rel)))
        manifests = read_manifests(resolved)
        self._cache[key] = (parses, manifests)
        return parses, manifests

    def _ingest_code(
        self,
        root: Path,
        parses: list[FileParse],
        *,
        graph: Any | None = None,
        embed_cap: int | None = None,
    ) -> int:
        """Code-aware chunking → knowledge: one chunk per symbol (§5b.1 layer 3).

        Files are embedded in **priority order** (Q-B4) and stop at ``embed_cap`` chunks.
        """
        ingested = 0
        for fp in self._embed_priority(parses, graph):
            if embed_cap is not None and ingested >= embed_cap:
                break
            if not fp.symbols:
                continue
            try:
                lines = (root / fp.path).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for sym in fp.symbols:
                if embed_cap is not None and ingested >= embed_cap:
                    return ingested
                if sym.kind == KIND_CLASS:
                    continue  # methods are chunked individually
                body = "\n".join(lines[sym.start_line - 1 : sym.end_line])
                if not body.strip():
                    continue
                self._knowledge.ingest_text(
                    f"{fp.path}::{sym.qualname}",
                    body,
                    title=sym.qualname,
                    content_type=f"text/x-{fp.lang}",
                    metadata={
                        "code": True, "lang": fp.lang, "file": fp.path,
                        "symbol": sym.qualname, "kind": sym.kind,
                        "start_line": sym.start_line, "end_line": sym.end_line,
                    },
                )
                ingested += 1
        return ingested

    @staticmethod
    def _embed_priority(parses: list[FileParse], graph: Any | None) -> list[FileParse]:
        """Order files for embedding (Q-B4): public API → frequently-imported → symbol-rich."""
        indegree: dict[str, int] = {}
        edges = getattr(graph, "import_edges", None) or []
        for edge in edges:
            try:
                _src, target = edge
            except (TypeError, ValueError):
                continue
            indegree[target] = indegree.get(target, 0) + 1

        def score(fp: FileParse) -> tuple[Any, ...]:
            name = fp.path.replace("\\", "/").rsplit("/", 1)[-1]
            is_public = name == "__init__.py"
            return (0 if is_public else 1, -indegree.get(fp.path, 0), -len(fp.symbols), fp.path)

        return sorted(parses, key=score)

    @staticmethod
    def _outline(fp: FileParse) -> str:
        lines = [f"file: {fp.path} ({fp.lang}, {fp.loc} loc, outcome={fp.outcome})"]
        if fp.imports:
            lines.append("imports: " + ", ".join(i.module for i in fp.imports[:20]))
        for sym in fp.symbols[:60]:
            indent = "  " if sym.parent else ""
            lines.append(f"{indent}{sym.kind} {sym.signature or sym.name} "
                         f"(L{sym.start_line}-{sym.end_line})")
        return "\n".join(lines)

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(
            f"code understanding ready ({len(supported_languages())} languages)",
            languages=len(supported_languages()),
        )
