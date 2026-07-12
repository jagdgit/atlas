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


class DetailedHealthResponse(BaseModel):
    healthy: bool
    services: dict[str, ServiceHealth]


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


class SearchResultOut(BaseModel):
    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    similarity: float


class SearchResponse(BaseModel):
    results: list[SearchResultOut]


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


class JobOut(BaseModel):
    id: str
    objective: str
    status: str
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
