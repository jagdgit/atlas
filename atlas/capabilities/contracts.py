"""Capability contracts + the canonical capability catalog (S11).

Each capability has:
- a canonical **id** (a short string, e.g. ``"memory"``) — what the planner tags a
  step with and what a provider registers under;
- a ``runtime_checkable`` **Protocol** describing the methods a provider must expose,
  so the registry can *verify* a provider actually implements its contract;
- a ``CapabilitySpec`` entry in ``CAPABILITY_CATALOG`` with a human summary and what
  building it *unlocks* — the material for an honest Capability Gap Report (R2).

Protocols use ``...`` bodies; ``runtime_checkable`` only checks *method presence*,
which is exactly the "does this provider offer the capability?" question we need.
Contracts we don't yet provide (``search``, ``document``, ``code``, ``learning``)
are catalogued deliberately so gap reports can name them and say what they'd unlock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

# --- canonical capability ids (single source of truth) -------------------
CAP_LLM = "llm"
CAP_MEMORY = "memory"
CAP_KNOWLEDGE = "knowledge"
CAP_DOCUMENT = "document"
CAP_WEB = "web"
CAP_AGENT = "agent"
CAP_CONVERSATION = "conversation"
CAP_SEARCH = "search"
CAP_CODE = "code"
CAP_LEARNING = "learning"


# --- contracts (Protocols) ----------------------------------------------
@runtime_checkable
class LLMCapability(Protocol):
    """Role-resolved language-model access (D7)."""

    def for_role(self, role: str) -> Any: ...
    def embed(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class MemoryCapability(Protocol):
    """Durable working/episodic/semantic memory."""

    def remember(self, *args: Any, **kwargs: Any) -> Any: ...
    def recall(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class KnowledgeCapability(Protocol):
    """Ingest documents and answer/search over them (RAG)."""

    def ingest_text(self, *args: Any, **kwargs: Any) -> Any: ...
    def search(self, *args: Any, **kwargs: Any) -> Any: ...
    def list_documents(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ExecutionCapability(Protocol):
    """Run a named agent/strategy over a query (ReAct, RAG, …)."""

    def run(self, name: str, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ConversationCapability(Protocol):
    """Persistent multi-turn sessions + context assembly."""

    def ensure_session(self, *args: Any, **kwargs: Any) -> Any: ...
    def history(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class FetchCapability(Protocol):
    """Fetch a single URL and return readable text (the ``web`` capability)."""

    def fetch(self, url: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class FilesystemCapability(Protocol):
    """Sandboxed read/list over a configured root."""

    def list_dir(self, *args: Any, **kwargs: Any) -> Any: ...
    def read_file(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class DocumentCapability(Protocol):
    """Extract structured text from many document formats (planned, S13)."""

    def extract(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class SearchCapability(Protocol):
    """Web *search* — query → ranked results (planned, S13)."""

    def search_web(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class CodeCapability(Protocol):
    """Understand code as structure (S14, Tier B): parse, map, index, graph."""

    def parse(self, path: str, *args: Any, **kwargs: Any) -> Any: ...
    def repo_map(self, root: str, *args: Any, **kwargs: Any) -> Any: ...
    def index(self, root: str, *args: Any, **kwargs: Any) -> Any: ...
    def search_symbols(self, query: str, *args: Any, **kwargs: Any) -> Any: ...
    def graph(self, root: str, *args: Any, **kwargs: Any) -> Any: ...


# --- the catalog ---------------------------------------------------------
@dataclass(frozen=True)
class CapabilitySpec:
    """A known capability — provided or not — for honest gap reporting."""

    id: str
    contract: type
    summary: str
    unlocks: str
    since: str  # the sprint that introduces (or will introduce) it


CAPABILITY_CATALOG: dict[str, CapabilitySpec] = {
    CAP_LLM: CapabilitySpec(
        CAP_LLM,
        LLMCapability,
        "Role-resolved LLM access (chat/planner/researcher/…), single lane.",
        "Any reasoning, composition, or embedding step.",
        "S10",
    ),
    CAP_MEMORY: CapabilitySpec(
        CAP_MEMORY,
        MemoryCapability,
        "Remember and recall facts (working/episodic/semantic).",
        "Personalization, preferences, cross-turn recall.",
        "S6",
    ),
    CAP_KNOWLEDGE: CapabilitySpec(
        CAP_KNOWLEDGE,
        KnowledgeCapability,
        "Ingest documents and answer/search over them with citations.",
        "Grounded, cited answers from your documents.",
        "S3",
    ),
    CAP_AGENT: CapabilitySpec(
        CAP_AGENT,
        ExecutionCapability,
        "Run named agents/strategies (RAG, ReAct) over a query.",
        "Open-ended reasoning and tool use.",
        "S8",
    ),
    CAP_CONVERSATION: CapabilitySpec(
        CAP_CONVERSATION,
        ConversationCapability,
        "Persistent chat sessions, history, and context assembly.",
        "Multi-turn conversations that keep context.",
        "S10",
    ),
    CAP_WEB: CapabilitySpec(
        CAP_WEB,
        FetchCapability,
        "Fetch a single http(s) URL and return readable text.",
        "Reading a specific web page the user names.",
        "S7",
    ),
    CAP_DOCUMENT: CapabilitySpec(
        CAP_DOCUMENT,
        DocumentCapability,
        "Structured extraction from pdf/docx/pptx/xlsx/csv/… (planned).",
        "Reading rich document formats beyond plain text.",
        "S13",
    ),
    CAP_SEARCH: CapabilitySpec(
        CAP_SEARCH,
        SearchCapability,
        "Web *search*: a query returns ranked result links (planned).",
        "Discovering sources, not just fetching a known URL.",
        "S13",
    ),
    CAP_CODE: CapabilitySpec(
        CAP_CODE,
        CodeCapability,
        "Parse/understand code: symbols, import & call graph, patterns.",
        "Reading and reviewing code as structure, not text.",
        "S14",
    ),
    CAP_LEARNING: CapabilitySpec(
        CAP_LEARNING,
        Protocol,  # concrete LearningCapability contract lands with its impl (S18)
        "Promote completed activities into the five stores, governed (planned).",
        "Continuous learning: Atlas compounds over time (§5d).",
        "S18",
    ),
}


def describe_capabilities(registry: Any) -> list[dict[str, Any]]:
    """Merge the catalog with a live ``CapabilityRegistry`` for introspection.

    Returns one row per known-or-registered capability: whether it is currently
    ``provided``, its ``kind``, contract name, summary, and what it unlocks. This is
    the honest "here's what I can and cannot do" surface (R2), used by the API/CLI.
    """
    described = registry.describe() if hasattr(registry, "describe") else {}
    known = set(CAPABILITY_CATALOG) | set(described)
    rows: list[dict[str, Any]] = []
    for cap_id in sorted(known):
        spec = CAPABILITY_CATALOG.get(cap_id)
        meta = described.get(cap_id, {})
        provided = registry.has(cap_id) if hasattr(registry, "has") else cap_id in described
        rows.append(
            {
                "id": cap_id,
                "provided": bool(provided),
                "kind": meta.get("kind"),
                "contract": (spec.contract.__name__ if spec else None),
                "summary": (spec.summary if spec else meta.get("summary", "")),
                "unlocks": (spec.unlocks if spec else ""),
                "since": (spec.since if spec else None),
            }
        )
    return rows


def gap_report(missing: Iterable[str]) -> list[dict[str, Any]]:
    """Build a Capability Gap Report (R2) for a set of missing capability ids."""
    report: list[dict[str, Any]] = []
    for cap_id in missing:
        spec = CAPABILITY_CATALOG.get(cap_id)
        report.append(
            {
                "missing_capability": cap_id,
                "reason": (
                    f"the '{cap_id}' capability is not registered"
                    if spec is None
                    else f"'{cap_id}' ({spec.summary}) is not registered"
                ),
                "unlocks": (spec.unlocks if spec else ""),
                "since": (spec.since if spec else None),
            }
        )
    return report
