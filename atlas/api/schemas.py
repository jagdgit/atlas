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
