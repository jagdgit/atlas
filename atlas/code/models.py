"""Data model for code understanding (S14).

Plain, frozen dataclasses — the *facts* a deterministic parse produces, kept separate
from any parser/LLM so they serialise cleanly to the API/CLI and feed the S18 Learning
Pipeline unchanged. Every model has ``as_dict`` for transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Symbol kinds.
KIND_FUNCTION = "function"
KIND_METHOD = "method"
KIND_CLASS = "class"
KIND_IMPORT = "import"

# Parse outcomes (R2 honesty): 'shallow' = parsed at symbol level only (no calls),
# 'unsupported' = no parser (plain-text fallback), 'error' = could not read/parse.
OUTCOME_OK = "ok"
OUTCOME_SHALLOW = "shallow"
OUTCOME_UNSUPPORTED = "unsupported"
OUTCOME_ERROR = "error"


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    file: str
    start_line: int
    end_line: int
    lang: str
    signature: str = ""
    docstring: str = ""
    parent: str | None = None  # qualified name of the enclosing symbol

    @property
    def qualname(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "kind": self.kind,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "lang": self.lang,
            "signature": self.signature,
            "docstring": self.docstring,
            "parent": self.parent,
        }


@dataclass(frozen=True, slots=True)
class ImportRef:
    module: str  # dotted module / import target as written
    file: str
    line: int
    names: tuple[str, ...] = ()  # imported names (from X import a, b)
    resolved_file: str | None = None  # in-repo file this resolves to, if any

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "file": self.file,
            "line": self.line,
            "names": list(self.names),
            "resolved_file": self.resolved_file,
        }


@dataclass(frozen=True, slots=True)
class CallRef:
    caller: str  # qualified name of the calling symbol ("" = module scope)
    callee: str  # dotted callee as written (e.g. "foo", "self.bar", "mod.baz")
    file: str
    line: int
    resolved: str | None = None  # "file::qualname" of the resolved definition

    def as_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "file": self.file,
            "line": self.line,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True)
class FileParse:
    path: str
    lang: str
    outcome: str = OUTCOME_OK
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)
    loc: int = 0
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lang": self.lang,
            "outcome": self.outcome,
            "loc": self.loc,
            "reason": self.reason,
            "symbols": [s.as_dict() for s in self.symbols],
            "imports": [i.as_dict() for i in self.imports],
            "calls": [c.as_dict() for c in self.calls],
        }


@dataclass(frozen=True, slots=True)
class RepoMap:
    root: str
    file_count: int
    total_loc: int
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    manifests: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)  # manager -> deps
    frameworks: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)  # {path, lang, loc, symbols}

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_loc": self.total_loc,
            "languages": self.languages,
            "manifests": self.manifests,
            "dependencies": self.dependencies,
            "frameworks": self.frameworks,
            "entry_points": self.entry_points,
            "files": self.files,
        }


@dataclass(frozen=True, slots=True)
class CodeGraph:
    import_edges: list[tuple[str, str]] = field(default_factory=list)  # (src, dst) files
    call_edges: list[tuple[str, str]] = field(default_factory=list)    # (caller, callee) qual
    unresolved_calls: int = 0
    external_imports: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "import_edges": [list(e) for e in self.import_edges],
            "call_edges": [list(e) for e in self.call_edges],
            "unresolved_calls": self.unresolved_calls,
            "external_imports": self.external_imports,
            "import_edge_count": len(self.import_edges),
            "call_edge_count": len(self.call_edges),
        }


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    description: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
        }
