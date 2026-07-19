"""Reader Registry (Phase B · §B.4, BB10 / constitution P11).

A **Reader** turns an Asset into a structured Artifact for one family of languages. The
**ReaderRegistry** is Atlas's honest answer to *"who can read `.mat`?"* and *"can you produce a JS
call graph?"*: it maps **extensions → reader** and records each reader's `version`, a **coverage
matrix** of what it can/can't extract, a `priority`, and enabled/health. Because capabilities are
**declared**, Atlas fails *honestly* — reporting "the JS/TS reader doesn't produce a call graph"
from the coverage matrix instead of silently returning an empty graph. New readers register here
later (MATLAB, CAD, …) with no changes elsewhere. Per P11 readers own no knowledge/state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.services.base import HealthStatus

# Coverage-matrix capability keys (what a reader can extract from its languages).
CAP_SYMBOLS = "symbols"
CAP_IMPORTS = "imports"
CAP_EXPORTS = "exports"
CAP_CALL_GRAPH = "call_graph"
CAP_DECORATORS = "decorators"
CAP_TYPING = "typing"
CAP_MODULES = "modules"

ALL_CAPABILITIES = (
    CAP_SYMBOLS, CAP_IMPORTS, CAP_EXPORTS, CAP_CALL_GRAPH,
    CAP_DECORATORS, CAP_TYPING, CAP_MODULES,
)


@dataclass(frozen=True, slots=True)
class Reader:
    """A language-family reader with a declared coverage matrix + version (BB10/BB8)."""

    id: str
    name: str
    version: str
    extensions: tuple[str, ...]
    languages: tuple[str, ...]
    coverage: dict[str, bool] = field(default_factory=dict)
    priority: int = 50
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return bool(self.coverage.get(capability, False))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "extensions": list(self.extensions),
            "languages": list(self.languages),
            "coverage": {c: bool(self.coverage.get(c, False)) for c in ALL_CAPABILITIES},
            "priority": self.priority,
            "enabled": self.enabled,
        }


def default_readers() -> list[Reader]:
    """The built-in v1 readers (Python native + JS/TS + a tree-sitter breadth reader)."""
    return [
        Reader(
            id="python", name="Python Reader", version="1.0.0",
            extensions=(".py", ".pyi"), languages=("python",),
            coverage={
                CAP_SYMBOLS: True, CAP_IMPORTS: True, CAP_CALL_GRAPH: True,
                CAP_DECORATORS: True, CAP_TYPING: True, CAP_MODULES: True,
                CAP_EXPORTS: False,
            },
            priority=100,
        ),
        Reader(
            id="jsts", name="JavaScript/TypeScript Reader", version="1.0.0",
            extensions=(".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"),
            languages=("javascript", "typescript", "tsx"),
            coverage={
                CAP_SYMBOLS: True, CAP_IMPORTS: True, CAP_EXPORTS: True,
                CAP_MODULES: True, CAP_TYPING: True,
                CAP_CALL_GRAPH: False,  # honestly unsupported (breadth path, no call resolution)
                CAP_DECORATORS: False,
            },
            priority=90,
        ),
        Reader(
            id="treesitter", name="Tree-sitter Breadth Reader", version="1.0.0",
            extensions=(
                ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp",
                ".rs", ".go", ".java", ".sql", ".sh", ".bash",
            ),
            languages=("c", "cpp", "rust", "go", "java", "sql", "bash"),
            coverage={
                CAP_SYMBOLS: True, CAP_IMPORTS: True, CAP_MODULES: True,
                CAP_CALL_GRAPH: False, CAP_EXPORTS: False,
                CAP_DECORATORS: False, CAP_TYPING: False,
            },
            priority=50,
        ),
    ]


class ReaderRegistry:
    """Maps extensions/languages → reader and answers coverage questions honestly (BB10)."""

    name = "readers"
    VERSION = "1.0.0"

    def __init__(
        self,
        readers: list[Reader] | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._by_id: dict[str, Reader] = {}
        self._logger = logger or logging.getLogger("atlas.engineering.readers")
        for reader in readers if readers is not None else default_readers():
            self.register(reader)

    def register(self, reader: Reader) -> None:
        """Add/replace a reader (last registration for an id wins)."""
        self._by_id[reader.id] = reader

    def readers(self, *, enabled_only: bool = False) -> list[Reader]:
        """All readers, highest-priority first."""
        out = [r for r in self._by_id.values() if r.enabled or not enabled_only]
        return sorted(out, key=lambda r: (-r.priority, r.id))

    def get(self, reader_id: str) -> Reader | None:
        return self._by_id.get(reader_id)

    def reader_for_extension(self, extension: str) -> Reader | None:
        """Highest-priority enabled reader that handles ``extension`` (``.ts``)."""
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        for reader in self.readers(enabled_only=True):
            if ext in reader.extensions:
                return reader
        return None

    def reader_for_path(self, path: str) -> Reader | None:
        return self.reader_for_extension(Path(path).suffix)

    def reader_for_language(self, language: str) -> Reader | None:
        """Highest-priority enabled reader that handles ``language``."""
        for reader in self.readers(enabled_only=True):
            if language in reader.languages:
                return reader
        return None

    def supports(
        self,
        capability: str,
        *,
        language: str | None = None,
        extension: str | None = None,
    ) -> bool:
        """Whether the reader for a language/extension declares ``capability``."""
        reader = (
            self.reader_for_language(language) if language
            else self.reader_for_extension(extension) if extension
            else None
        )
        return bool(reader and reader.supports(capability))

    def can_produce(
        self, capability: str, *, language: str
    ) -> dict[str, Any]:
        """Honest answer to *"can you produce <capability> for <language>?"* (BB10).

        Returns ``{supported, reader, reason}`` — never silently empty; if no reader can,
        the ``reason`` says why so callers/UX can report it truthfully.
        """
        reader = self.reader_for_language(language)
        if reader is None:
            return {
                "supported": False, "reader": None,
                "reason": f"no reader handles language '{language}'",
            }
        if reader.supports(capability):
            return {"supported": True, "reader": reader.id, "reason": ""}
        return {
            "supported": False, "reader": reader.id,
            "reason": f"the {reader.name} does not support {capability}",
        }

    def extension_map(self) -> dict[str, str]:
        """``extension -> reader id`` (highest priority wins) for introspection."""
        out: dict[str, str] = {}
        for reader in reversed(self.readers(enabled_only=True)):  # low→high, high overwrites
            for ext in reader.extensions:
                out[ext] = reader.id
        return dict(sorted(out.items()))

    def coverage_matrix(self) -> dict[str, dict[str, bool]]:
        return {r.id: {c: r.supports(c) for c in ALL_CAPABILITIES} for r in self.readers()}

    def describe(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.readers()]

    def metrics(self) -> dict[str, Any]:
        """Self-inspection snapshot for the Capability Registry (§5.10)."""
        readers = self.readers()
        return {
            "readers": len(readers),
            "enabled": sum(1 for r in readers if r.enabled),
            "extensions": len(self.extension_map()),
            "languages": sorted({l for r in readers for l in r.languages}),
            "coverage": self.coverage_matrix(),
        }

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        readers = self.readers()
        enabled = sum(1 for r in readers if r.enabled)
        return HealthStatus.ok(
            f"{enabled}/{len(readers)} reader(s) enabled "
            f"({len(self.extension_map())} extensions)",
            readers=len(readers),
        )
