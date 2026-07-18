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
CAP_SCHOLAR = "scholar"
CAP_TRANSCRIPT = "transcript"
CAP_CODE = "code"
CAP_PYTHON = "python"
CAP_LEARNING = "learning"
CAP_INTELLIGENCE = "intelligence"
CAP_GIT = "git"
CAP_SQL = "sql"
CAP_OCR = "ocr"
CAP_MAIL = "mail"
CAP_BROWSER = "browser"
CAP_RESEARCH = "research"
# Stage 3B knowledge-OS capabilities (stubs until providers land; D3B.25).
CAP_RETRIEVAL = "retrieval"
CAP_SYNTHESIS = "synthesis"
CAP_KNOWLEDGE_LIFECYCLE = "knowledge_lifecycle"

# Cost classes reused by Resource Manager / CapabilitySpec (3.2d / A3B.20).
COST_FREE = "free"
COST_CHEAP = "cheap"
COST_MODERATE = "moderate"
COST_EXPENSIVE = "expensive"
COST_LLM = "llm"
COST_UNKNOWN = "unknown"


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
    """Ingest documents and answer/search over them (RAG + Access Layer)."""

    def ingest_text(self, *args: Any, **kwargs: Any) -> Any: ...
    def search(self, *args: Any, **kwargs: Any) -> Any: ...
    def retrieve(self, *args: Any, **kwargs: Any) -> Any: ...
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
class ScholarCapability(Protocol):
    """Academic *search* — query → graded papers (arXiv, Semantic Scholar; S18)."""

    def search_scholar(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class TranscriptCapability(Protocol):
    """Video → transcript text (YouTube; S18)."""

    def get_transcript(self, video: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class CodeCapability(Protocol):
    """Understand code as structure (S14, Tier B): parse, map, index, graph."""

    def parse(self, path: str, *args: Any, **kwargs: Any) -> Any: ...
    def repo_map(self, root: str, *args: Any, **kwargs: Any) -> Any: ...
    def index(self, root: str, *args: Any, **kwargs: Any) -> Any: ...
    def search_symbols(self, query: str, *args: Any, **kwargs: Any) -> Any: ...
    def graph(self, root: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class PythonExecutionCapability(Protocol):
    """Run Python in an isolated, resource-limited sandbox (S16, D6)."""

    def run(self, code: str, *args: Any, **kwargs: Any) -> Any: ...
    def run_file(self, path: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class LearningCapability(Protocol):
    """Promote completed activities into the five stores, governed (S18b, §5d)."""

    def observe_job(self, detail: Any, *args: Any, **kwargs: Any) -> Any: ...
    def apply(self, event_id: str, *args: Any, **kwargs: Any) -> Any: ...
    def revert(self, event_id: str, *args: Any, **kwargs: Any) -> Any: ...
    def recall(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class IntelligenceCapability(Protocol):
    """Engineering Intelligence: learn repos (L2), connect/search (L3), generalize
    patterns (L4) and recommend (L5) over the Code store (S19, §5d)."""

    def learn_repository(self, root: str, *args: Any, **kwargs: Any) -> Any: ...
    def generalize(self, *args: Any, **kwargs: Any) -> Any: ...
    def recommend(self, *args: Any, **kwargs: Any) -> Any: ...
    def search(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class GitCapability(Protocol):
    """Read-only local version-control inspection (S20a)."""

    def status(self, repo: str, *args: Any, **kwargs: Any) -> Any: ...
    def log(self, repo: str, *args: Any, **kwargs: Any) -> Any: ...
    def diff(self, repo: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class SQLCapability(Protocol):
    """Read-only SQL querying over a local database (S20b)."""

    def query(self, sql: str, *args: Any, **kwargs: Any) -> Any: ...
    def tables(self, *args: Any, **kwargs: Any) -> Any: ...
    def schema(self, table: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class OCRCapability(Protocol):
    """Extract text from an image via OCR (S20c)."""

    def image(self, path: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class MailCapability(Protocol):
    """Read-only email retrieval over IMAP (S20d)."""

    def search(self, *args: Any, **kwargs: Any) -> Any: ...
    def message(self, uid: str, *args: Any, **kwargs: Any) -> Any: ...
    def folders(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class BrowserCapability(Protocol):
    """Read-only headless browser: render a URL / screenshot it (S20e)."""

    def open(self, url: str, *args: Any, **kwargs: Any) -> Any: ...
    def screenshot(self, url: str, path: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ResearchCapability(Protocol):
    """Autonomous gather → verify → decide research loop (S21)."""

    def research(self, objective: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class RetrievalCapability(Protocol):
    """Global Knowledge Access retrieve path (Stage 3B.1): Retrieve→Re-rank→Context."""

    def retrieve(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class SynthesisCapability(Protocol):
    """Evidence → Findings synthesizer (Stage 3B.2)."""

    def synthesize(self, claims: Any, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class KnowledgeLifecycleCapability(Protocol):
    """Append-only finding revisions, freshness, supersede/archive (Stage 3B.3)."""

    def revise(self, *args: Any, **kwargs: Any) -> Any: ...
    def supersede(self, *args: Any, **kwargs: Any) -> Any: ...


# --- the catalog ---------------------------------------------------------
@dataclass(frozen=True)
class CapabilitySpec:
    """A known capability — provided or not — for honest gap reporting."""

    id: str
    contract: type
    summary: str
    unlocks: str
    since: str  # the sprint that introduces (or will introduce) it
    # Stage 3B.0 extensions (defaults keep existing catalog entries valid).
    version: str = "1"
    cost_class: str = COST_UNKNOWN
    dependencies: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    quality_notes: str = ""


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
    CAP_SCHOLAR: CapabilitySpec(
        CAP_SCHOLAR,
        ScholarCapability,
        "Academic search (arXiv, Semantic Scholar): papers graded L3/L4.",
        "Peer-reviewed evidence for the Verification Engine (§5a).",
        "S18",
    ),
    CAP_TRANSCRIPT: CapabilitySpec(
        CAP_TRANSCRIPT,
        TranscriptCapability,
        "Fetch a video transcript (YouTube) as readable text (L1 evidence).",
        "Learning from talks/lectures, not just written sources.",
        "S18",
    ),
    CAP_CODE: CapabilitySpec(
        CAP_CODE,
        CodeCapability,
        "Parse/understand code: symbols, import & call graph, patterns.",
        "Reading and reviewing code as structure, not text.",
        "S14",
    ),
    CAP_PYTHON: CapabilitySpec(
        CAP_PYTHON,
        PythonExecutionCapability,
        "Run Python in an isolated, resource-limited sandbox (no network by default).",
        "Data-driven computation; results become L5 evidence (§5a.6).",
        "S16",
    ),
    CAP_LEARNING: CapabilitySpec(
        CAP_LEARNING,
        LearningCapability,
        "Promote completed activities into the five stores, governed & reversible.",
        "Continuous learning: Atlas compounds over time (§5d); Experience store.",
        "S18",
    ),
    CAP_INTELLIGENCE: CapabilitySpec(
        CAP_INTELLIGENCE,
        IntelligenceCapability,
        "Learn repos (L2), connect (L3), generalize patterns (L4), recommend (L5).",
        "Engineering Intelligence: Atlas learns *you* — the Personal Coding Assistant.",
        "S19",
    ),
    CAP_GIT: CapabilitySpec(
        CAP_GIT,
        GitCapability,
        "Read a local repo's status, log, diff, branches and file history.",
        "Version-control awareness for the coding assistant (read-only).",
        "S20",
    ),
    CAP_SQL: CapabilitySpec(
        CAP_SQL,
        SQLCapability,
        "Run a read-only SQL query over a local database; list tables/schema.",
        "Structured-data analysis (read-only); result sets are L5 evidence.",
        "S20",
    ),
    CAP_OCR: CapabilitySpec(
        CAP_OCR,
        OCRCapability,
        "Extract text from an image file (screenshot, photo, scan).",
        "Read pixels Atlas otherwise can't — completes the Document Reader.",
        "S20",
    ),
    CAP_MAIL: CapabilitySpec(
        CAP_MAIL,
        MailCapability,
        "Read-only email: list folders, search messages, open one message (IMAP).",
        "Email becomes a first-class research/assistant source; read-only, never sends.",
        "S20",
    ),
    CAP_BROWSER: CapabilitySpec(
        CAP_BROWSER,
        BrowserCapability,
        "Render a URL in a headless browser (JS-executed) and extract text/links; screenshot.",
        "Read JS-rendered pages plain fetch can't; read-only navigation.",
        "S20",
    ),
    CAP_RESEARCH: CapabilitySpec(
        CAP_RESEARCH,
        ResearchCapability,
        "Run an autonomous gather→verify→decide research loop and emit a verified report.",
        "Turns the tools + Verification Engine into a self-directing researcher.",
        "S21",
        cost_class=COST_LLM,
        dependencies=(CAP_SCHOLAR, CAP_WEB, CAP_KNOWLEDGE),
        metrics=("benchmark_pass_rate",),
        quality_notes="First consumer of Access Layer + Findings; not a separate RAG stack.",
    ),
    CAP_RETRIEVAL: CapabilitySpec(
        CAP_RETRIEVAL,
        RetrievalCapability,
        "Global retrieve(query, domains, filters, role) with dense+lexical hybrid and diagnostics.",
        "One Access Layer for chat, research, planner, and future Engineering/Personal.",
        "3B.1",
        version="1",
        cost_class=COST_MODERATE,
        dependencies=(CAP_KNOWLEDGE, CAP_LLM),
        metrics=("precision_at_k", "recall_at_k", "citation_coverage"),
        quality_notes=(
            "Pipeline locked: Retrieve→Re-rank→Context→LLM. Persist dense/lexical/rrf scores."
        ),
    ),
    CAP_SYNTHESIS: CapabilitySpec(
        CAP_SYNTHESIS,
        SynthesisCapability,
        "Synthesize per-source claims into durable Findings (support/contradict/quality).",
        "Canonical findings with provenance; evolves group_claims into knowledge.findings.",
        "3B.2",
        version="1",
        cost_class=COST_CHEAP,
        dependencies=(CAP_RESEARCH,),
        metrics=("merge_accuracy", "false_merge_rate", "contradiction_recall"),
        quality_notes="Conservative merge; never silently average contradictions.",
    ),
    CAP_KNOWLEDGE_LIFECYCLE: CapabilitySpec(
        CAP_KNOWLEDGE_LIFECYCLE,
        KnowledgeLifecycleCapability,
        "Append-only finding revisions, freshness, supersede/archive, invalidation.",
        "Durable knowledge that never overwrites; archive excluded from retrieval by default.",
        "3B.3",
        version="1",
        cost_class=COST_CHEAP,
        dependencies=(CAP_SYNTHESIS, CAP_RETRIEVAL),
        metrics=("freshness_label_accuracy", "supersession_correctness"),
        quality_notes="IDs: UUID + F-###### + revision. supersedes/superseded_by links.",
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
                "version": (spec.version if spec else None),
                "cost_class": (spec.cost_class if spec else None),
                "dependencies": list(spec.dependencies) if spec else [],
                "metrics": list(spec.metrics) if spec else [],
                "quality_notes": (spec.quality_notes if spec else ""),
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
