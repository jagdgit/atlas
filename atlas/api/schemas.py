"""Request/response schemas for the REST API (Pydantic v2).

These are the API's public contract — deliberately separate from internal domain
models (ADR-0036). Pydantic here is the "validation at the edge" half of §18.9 F1.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str


class ServiceHealth(BaseModel):
    healthy: bool
    detail: str
    severity: str = "ok"  # ok | degraded | failed (S22)
    data: dict[str, Any] = Field(default_factory=dict)


class DetailedHealthResponse(BaseModel):
    healthy: bool
    degraded: bool = False
    services: dict[str, ServiceHealth]


class StatusResponse(BaseModel):
    version: str
    uptime_seconds: float | None = None
    healthy: bool
    degraded: bool = False
    services_total: int
    severity_counts: dict[str, int]


class AgentsResponse(BaseModel):
    agents: list[str]


class RunAgentRequest(BaseModel):
    query: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class CitationOut(BaseModel):
    index: int
    document_id: str
    chunk_id: str
    similarity: float
    snippet: str


class RunAgentResponse(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    intent: str
    citations: list[CitationOut] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    capability_gaps: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str | None = None


class SessionOut(BaseModel):
    id: str
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SessionsResponse(BaseModel):
    sessions: list[SessionOut]


class ChatMessageOut(BaseModel):
    ordinal: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessageOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)
    domains: list[str] | None = None
    tiers: list[str] | None = None
    role: str = Field(default="chat", min_length=1)
    mode: str = Field(default="hybrid", pattern="^(hybrid|dense|lexical)$")


class SearchResultOut(BaseModel):
    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    similarity: float | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    rrf_score: float | None = None
    score: float | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    role: str | None = None
    mode: str | None = None
    diagnostics_id: str | None = None
    context: str | None = None


class IngestRequest(BaseModel):
    content: str = Field(min_length=1)
    source: str = "api"
    title: str | None = None
    uri: str | None = None
    content_type: str = "text/plain"
    embed: bool = True


class IngestResponse(BaseModel):
    document_id: str
    status: str
    chunks: int
    deduped: bool


class RememberRequest(BaseModel):
    content: str = Field(min_length=1)
    kind: str = Field(default="semantic", pattern="^(working|episodic|semantic)$")
    scope: str = "global"
    importance: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = None


class MemoryItemOut(BaseModel):
    id: str
    kind: str
    scope: str
    content: str
    importance: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str | None = None
    expires_at: str | None = None
    similarity: float | None = None


class RememberResponse(BaseModel):
    item: MemoryItemOut


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)
    kind: str | None = Field(default=None, pattern="^(working|episodic|semantic)$")
    scope: str | None = None


class RecallResponse(BaseModel):
    results: list[MemoryItemOut]


class RecentMemoryResponse(BaseModel):
    items: list[MemoryItemOut]


class ForgetResponse(BaseModel):
    forgotten: bool


class ToolInfo(BaseModel):
    name: str
    description: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    plugin: str | None = None


class ToolsResponse(BaseModel):
    tools: list[ToolInfo]


class InvokeToolRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class InvokeToolResponse(BaseModel):
    result: Any


class PluginInfo(BaseModel):
    name: str
    version: str


class PluginsResponse(BaseModel):
    plugins: list[PluginInfo]


class DocumentFormatsResponse(BaseModel):
    formats: list[str]


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=25)


class WebSearchResponse(BaseModel):
    query: str
    provider: str | None = None
    outcome: str
    results: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


class CodeParseRequest(BaseModel):
    path: str = Field(min_length=1)


class CodeRepoRequest(BaseModel):
    root: str = Field(min_length=1)


class CodeSymbolsRequest(BaseModel):
    root: str = Field(min_length=1)
    query: str = ""
    kind: str | None = None
    lang: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


class CodeExplainRequest(BaseModel):
    path: str = Field(min_length=1)
    question: str | None = None


class ScholarSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=25)


class YouTubeTranscriptRequest(BaseModel):
    video: str = Field(min_length=1)  # YouTube URL or 11-char video id


class GitRequest(BaseModel):
    # Read-only local git inspection (S20a). `action` selects the operation.
    action: str = Field(default="status")  # status|log|diff|show|branches|file_history
    repo: str = Field(min_length=1)
    ref: str | None = None
    path: str | None = None  # required for file_history
    max_count: int | None = Field(default=None, ge=1, le=1000)


class SQLQueryRequest(BaseModel):
    # Read-only SQL over a local database (S20b).
    sql: str = Field(min_length=1)
    source: str | None = None  # db file under the sandbox root
    params: list | dict | None = None
    limit: int | None = Field(default=None, ge=1, le=100_000)


class OCRRequest(BaseModel):
    # Extract text from an image (S20c).
    path: str = Field(min_length=1)  # image path under the OCR sandbox root
    lang: str | None = None  # tesseract language code (default 'eng')


class MailSearchRequest(BaseModel):
    # Read-only mailbox search (S20d).
    query: str = ""  # empty => most recent messages
    folder: str | None = None  # mailbox/folder (default INBOX)
    limit: int | None = Field(default=None, ge=1, le=500)


class ResearchRequest(BaseModel):
    # Autonomous gather→verify→decide research loop (S21).
    objective: str = Field(min_length=1)
    max_iterations: int | None = Field(default=None, ge=1, le=100)


class BrowseRequest(BaseModel):
    # Render a URL in a headless browser (S20e).
    url: str = Field(min_length=1)


class ScreenshotRequest(BaseModel):
    # Screenshot a URL to a PNG under the sandbox root (S20e).
    url: str = Field(min_length=1)
    path: str = Field(min_length=1)
    full_page: bool = True


class ReportRequest(BaseModel):
    # Objective + a serialised Evidence Graph → a verified §5a.5 report (S17).
    objective: str = Field(min_length=1)
    claims: list[dict] = Field(default_factory=list)
    sources: list[dict] | None = None
    budget: dict | None = None
    notes: str | None = None


class LearningApplyRequest(BaseModel):
    # Promote a proposed learning event into its store (S18b, §5d).
    policy: str | None = None  # temporary | project | personal | verified
    level: int | None = Field(default=None, ge=1, le=5)


class ExperienceRequest(BaseModel):
    # Manually record an Experience (problem → solution → lessons).
    title: str | None = None
    problem: str = Field(min_length=1)
    diagnosis: str | None = None
    actions: list[str] | None = None
    mistakes: str | None = None
    solution: str | None = None
    lessons: str | None = None
    tags: list[str] | None = None
    policy: str | None = None


class LearnRepositoryRequest(BaseModel):
    # Learn a repository into the Code store (S19, L2).
    root: str = Field(min_length=1)
    policy: str | None = None
    apply: bool = True


class RecommendRequest(BaseModel):
    # Personal Coding Assistant recommendations (S19, L5).
    context: str = ""
    limit: int | None = Field(default=None, ge=1, le=50)


class PythonRunRequest(BaseModel):
    code: str = Field(min_length=1)
    timeout: float | None = Field(default=None, gt=0)
    files: dict[str, str] | None = None
    stdin: str | None = None


class VerifyRequest(BaseModel):
    # A serialised Evidence Graph (claims + optional sources) plus an optional
    # per-request Evidence Budget override (S15, D8/§5a).
    claims: list[dict] = Field(min_length=1)
    sources: list[dict] | None = None
    budget: dict | None = None


class VerifyResponse(BaseModel):
    claims: list[dict]
    sources: list[dict]
    budget: dict


class CreateJobRequest(BaseModel):
    objective: str = Field(min_length=1)
    session_id: str | None = None


class JobInputRequest(BaseModel):
    """Human guidance for a running or blocked job (queued into the workspace)."""

    text: str = Field(min_length=1, max_length=8000)


class JobStepOut(BaseModel):
    ordinal: int
    intent: str
    capability: str
    status: str
    description: str = ""
    depends_on: int | None = None
    blocked_reason: str | None = None
    error: str | None = None
    attempts: int = 0
    result: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None


class JobOut(BaseModel):
    id: str
    objective: str
    status: str
    # 3.2e: planning_queued | planning | ready (status stays familiar queued/running/…)
    phase: str = "ready"
    session_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class JobsResponse(BaseModel):
    jobs: list[JobOut]


class JobDetailResponse(BaseModel):
    job: JobOut
    steps: list[JobStepOut]
    progress: dict[str, int]
    blocked: list[dict[str, Any]] = Field(default_factory=list)
    # Live "watch it work" feed (RL/C0): recent human-readable progress events.
    activity: list[dict[str, Any]] = Field(default_factory=list)
    # Approximate on-disk / text size for this job (live or finalized).
    usage: dict[str, Any] | None = None


class CapabilityInfo(BaseModel):
    id: str
    provided: bool
    kind: str | None = None
    contract: str | None = None
    summary: str = ""
    unlocks: str = ""
    since: str | None = None


class CapabilitiesResponse(BaseModel):
    capabilities: list[CapabilityInfo]
