"""HTTP routes for the Atlas REST API.

Routes are thin: they resolve kernel services from the running Application's DI
container and translate to/from the public schemas. No SQL, no provider calls
here — the API is just another caller of the same services agents use (ADR-0006).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from atlas.api.auth import require_api_key
from atlas.api.schemas import (
    AgentsResponse,
    DetailedHealthResponse,
    ForgetResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    InvokeToolRequest,
    InvokeToolResponse,
    MemoryItemOut,
    PluginInfo,
    PluginsResponse,
    RecallRequest,
    RecallResponse,
    RecentMemoryResponse,
    RememberRequest,
    RememberResponse,
    RunAgentRequest,
    RunAgentResponse,
    SearchRequest,
    SearchResponse,
    SearchResultOut,
    ServiceHealth,
    ToolInfo,
    ToolsResponse,
)

# Public: liveness only, no auth (safe to expose to a load balancer / probe).
public_router = APIRouter(tags=["health"])

# Everything else requires a valid API key.
v1_router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


def _app(request: Request):
    return request.app.state.application


def _memory_out(item) -> MemoryItemOut:
    return MemoryItemOut(
        id=item.id,
        kind=item.kind,
        scope=item.scope,
        content=item.content,
        importance=item.importance,
        metadata=item.metadata,
        occurred_at=item.occurred_at.isoformat() if item.occurred_at else None,
        expires_at=item.expires_at.isoformat() if item.expires_at else None,
        similarity=item.similarity,
    )


@public_router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    cfg = _app(request).config
    return HealthResponse(status="ok", version=cfg.system.version)


@v1_router.get("/health", response_model=DetailedHealthResponse, tags=["health"])
def detailed_health(request: Request) -> DetailedHealthResponse:
    report = _app(request).health()
    services = {
        name: ServiceHealth(healthy=s.healthy, detail=s.detail)
        for name, s in report.items()
    }
    healthy = all(s.healthy for s in services.values())
    return DetailedHealthResponse(healthy=healthy, services=services)


@v1_router.get("/agents", response_model=AgentsResponse, tags=["agents"])
def list_agents(request: Request) -> AgentsResponse:
    agent_service = _app(request).container.resolve("agent")
    return AgentsResponse(agents=agent_service.list())


@v1_router.post(
    "/agents/{name}/run", response_model=RunAgentResponse, tags=["agents"]
)
def run_agent(name: str, body: RunAgentRequest, request: Request) -> RunAgentResponse:
    agent_service = _app(request).container.resolve("agent")
    result = agent_service.run(name, body.query, **body.options)
    return RunAgentResponse(**result.as_dict())


@v1_router.post("/knowledge/search", response_model=SearchResponse, tags=["knowledge"])
def search(body: SearchRequest, request: Request) -> SearchResponse:
    knowledge = _app(request).container.resolve("knowledge")
    results = knowledge.search(body.query, limit=body.limit)
    return SearchResponse(
        results=[
            SearchResultOut(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                ordinal=r.ordinal,
                content=r.content,
                similarity=r.similarity,
            )
            for r in results
        ]
    )


@v1_router.post("/knowledge/ingest", response_model=IngestResponse, tags=["knowledge"])
def ingest(body: IngestRequest, request: Request) -> IngestResponse:
    knowledge = _app(request).container.resolve("knowledge")
    summary = knowledge.ingest_text(
        body.source,
        body.content,
        title=body.title,
        uri=body.uri,
        content_type=body.content_type,
        embed=body.embed,
    )
    return IngestResponse(**summary)


@v1_router.post("/memory/remember", response_model=RememberResponse, tags=["memory"])
def remember(body: RememberRequest, request: Request) -> RememberResponse:
    memory = _app(request).container.resolve("memory")
    item = memory.remember(
        body.content,
        kind=body.kind,
        scope=body.scope,
        importance=body.importance,
        metadata=body.metadata,
        ttl_seconds=body.ttl_seconds,
    )
    return RememberResponse(item=_memory_out(item))


@v1_router.post("/memory/recall", response_model=RecallResponse, tags=["memory"])
def recall(body: RecallRequest, request: Request) -> RecallResponse:
    memory = _app(request).container.resolve("memory")
    results = memory.recall(body.query, limit=body.limit, kind=body.kind, scope=body.scope)
    return RecallResponse(results=[_memory_out(r) for r in results])


@v1_router.get("/memory/recent", response_model=RecentMemoryResponse, tags=["memory"])
def recent_memory(
    request: Request,
    kind: str | None = None,
    scope: str | None = None,
    limit: int = 20,
) -> RecentMemoryResponse:
    memory = _app(request).container.resolve("memory")
    items = memory.recent(kind=kind, scope=scope, limit=limit)
    return RecentMemoryResponse(items=[_memory_out(i) for i in items])


@v1_router.delete("/memory/{memory_id}", response_model=ForgetResponse, tags=["memory"])
def forget(memory_id: str, request: Request) -> ForgetResponse:
    memory = _app(request).container.resolve("memory")
    return ForgetResponse(forgotten=memory.forget(memory_id))


@v1_router.get("/plugins", response_model=PluginsResponse, tags=["plugins"])
def list_plugins(request: Request) -> PluginsResponse:
    manager = _app(request).container.resolve("plugins")
    return PluginsResponse(plugins=[PluginInfo(**p) for p in manager.describe()])


@v1_router.get("/tools", response_model=ToolsResponse, tags=["plugins"])
def list_tools(request: Request) -> ToolsResponse:
    tools = _app(request).tools
    return ToolsResponse(tools=[ToolInfo(**t) for t in tools.describe()])


@v1_router.post(
    "/tools/{name}/invoke", response_model=InvokeToolResponse, tags=["plugins"]
)
def invoke_tool(name: str, body: InvokeToolRequest, request: Request) -> InvokeToolResponse:
    result = _app(request).invoke_tool(name, **body.args)
    return InvokeToolResponse(result=result)
