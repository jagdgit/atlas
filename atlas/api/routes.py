"""HTTP routes for the Atlas REST API.

Routes are thin: they resolve kernel services from the running Application's DI
container and translate to/from the public schemas. No SQL, no provider calls
here — the API is just another caller of the same services agents use (ADR-0006).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from atlas.telemetry import get_metrics, render_prometheus

from atlas.api.auth import require_api_key
from atlas.api.schemas import (
    AgentsResponse,
    CapabilitiesResponse,
    CapabilityInfo,
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    CreateJobRequest,
    DetailedHealthResponse,
    DocumentFormatsResponse,
    ForgetResponse,
    HealthResponse,
    HistoryResponse,
    IngestRequest,
    IngestResponse,
    InvokeToolRequest,
    InvokeToolResponse,
    JobDetailResponse,
    JobOut,
    JobsResponse,
    JobStepOut,
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
    SessionOut,
    SessionsResponse,
    CodeExplainRequest,
    CodeParseRequest,
    CodeRepoRequest,
    CodeSymbolsRequest,
    ExperienceRequest,
    GitRequest,
    LearningApplyRequest,
    LearnRepositoryRequest,
    RecommendRequest,
    PythonRunRequest,
    ReportRequest,
    ScholarSearchRequest,
    SQLQueryRequest,
    ToolInfo,
    ToolsResponse,
    VerifyRequest,
    VerifyResponse,
    WebSearchRequest,
    WebSearchResponse,
    YouTubeTranscriptRequest,
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


@public_router.get("/metrics", response_class=PlainTextResponse, tags=["monitoring"])
def metrics(request: Request) -> PlainTextResponse:
    """Prometheus text exposition of in-process metrics (ADR-0054).

    Public (unauthenticated) so a local Prometheus can scrape it, matching the
    convention for /health; disable via api.metrics_enabled.
    """
    if not _app(request).config.api.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return PlainTextResponse(render_prometheus(get_metrics().snapshot()))


@v1_router.get("/metrics", tags=["monitoring"])
def metrics_json(request: Request) -> dict:
    """Detailed metrics snapshot as JSON (authenticated)."""
    if not _app(request).config.api.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return get_metrics().snapshot()


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


@v1_router.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(body: ChatRequest, request: Request) -> ChatResponse:
    assistant = _app(request).container.resolve("chat")
    turn = assistant.chat(body.message, session_id=body.session_id)
    return ChatResponse(**turn.as_dict())


@v1_router.get("/chat/sessions", response_model=SessionsResponse, tags=["chat"])
def list_sessions(request: Request, limit: int = 50) -> SessionsResponse:
    conversation = _app(request).container.resolve("conversation")
    sessions = conversation.list_sessions(limit=limit)
    return SessionsResponse(
        sessions=[
            SessionOut(
                id=s.id,
                title=s.title,
                created_at=s.created_at.isoformat() if s.created_at else None,
                updated_at=s.updated_at.isoformat() if s.updated_at else None,
            )
            for s in sessions
        ]
    )


@v1_router.get(
    "/chat/sessions/{session_id}", response_model=HistoryResponse, tags=["chat"]
)
def session_history(session_id: str, request: Request) -> HistoryResponse:
    conversation = _app(request).container.resolve("conversation")
    if conversation.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = conversation.history(session_id)
    return HistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessageOut(
                ordinal=m.ordinal,
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in messages
        ],
    )


def _job_out(job) -> JobOut:
    return JobOut(
        id=job.id,
        objective=job.objective,
        status=job.status,
        session_id=job.session_id,
        result=job.result,
        error=job.error,
        created_at=job.created_at.isoformat() if job.created_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _step_out(step) -> JobStepOut:
    return JobStepOut(
        ordinal=step.ordinal,
        intent=step.intent,
        capability=step.capability,
        status=step.status,
        description=step.description,
        depends_on=step.depends_on,
        blocked_reason=step.blocked_reason,
        error=step.error,
        attempts=step.attempts,
    )


def _job_detail(detail) -> JobDetailResponse:
    return JobDetailResponse(
        job=_job_out(detail["job"]),
        steps=[_step_out(s) for s in detail["steps"]],
        progress=detail["progress"],
        blocked=detail["blocked"],
    )


@v1_router.get("/documents/formats", response_model=DocumentFormatsResponse, tags=["documents"])
def document_formats(request: Request) -> DocumentFormatsResponse:
    documents = _app(request).container.resolve("documents")
    return DocumentFormatsResponse(formats=documents.supported())


@v1_router.post("/search", response_model=WebSearchResponse, tags=["web"])
def web_search(body: WebSearchRequest, request: Request) -> WebSearchResponse:
    result = _app(request).invoke_tool(
        "web.search", query=body.query, max_results=body.max_results
    )
    return WebSearchResponse(
        query=result.get("query", body.query),
        provider=result.get("provider"),
        outcome=result.get("outcome", "error"),
        results=result.get("results", []),
        reason=result.get("reason"),
    )


@v1_router.post("/scholar", tags=["research"])
def scholar_search(body: ScholarSearchRequest, request: Request) -> dict:
    return _app(request).invoke_tool(
        "scholar.search", query=body.query, max_results=body.max_results
    )


@v1_router.post("/youtube/transcript", tags=["research"])
def youtube_transcript(body: YouTubeTranscriptRequest, request: Request) -> dict:
    return _app(request).invoke_tool("youtube.transcript", video=body.video)


# --- git (S20a): read-only local version-control inspection ---------------
@v1_router.post("/git", tags=["git"])
def git(body: GitRequest, request: Request) -> dict:
    app = _app(request)
    action = body.action
    if action == "log":
        return app.invoke_tool("git.log", repo=body.repo, max_count=body.max_count)
    if action == "diff":
        return app.invoke_tool("git.diff", repo=body.repo, ref=body.ref)
    if action == "show":
        return app.invoke_tool("git.show", repo=body.repo, ref=body.ref or "HEAD")
    if action == "branches":
        return app.invoke_tool("git.branches", repo=body.repo)
    if action == "file_history":
        return app.invoke_tool(
            "git.file_history", repo=body.repo, path=body.path or "",
            max_count=body.max_count,
        )
    return app.invoke_tool("git.status", repo=body.repo)


# --- sql (S20b): read-only local database querying ------------------------
@v1_router.post("/db/query", tags=["sql"])
def db_query(body: SQLQueryRequest, request: Request) -> dict:
    return _app(request).invoke_tool(
        "sql.query", sql=body.sql, source=body.source, params=body.params,
        limit=body.limit,
    )


@v1_router.get("/db/tables", tags=["sql"])
def db_tables(request: Request, source: str | None = None) -> dict:
    return _app(request).invoke_tool("sql.tables", source=source)


@v1_router.get("/db/schema", tags=["sql"])
def db_schema(request: Request, table: str, source: str | None = None) -> dict:
    return _app(request).invoke_tool("sql.schema", table=table, source=source)


# --- code understanding (S14) --------------------------------------------
def _code(request: Request):
    return _app(request).container.resolve("code")


@v1_router.post("/code/parse", tags=["code"])
def code_parse(body: CodeParseRequest, request: Request) -> dict:
    return _code(request).parse(body.path)


@v1_router.post("/code/repo-map", tags=["code"])
def code_repo_map(body: CodeRepoRequest, request: Request) -> dict:
    return _code(request).repo_map(body.root)


@v1_router.post("/code/graph", tags=["code"])
def code_graph(body: CodeRepoRequest, request: Request) -> dict:
    return _code(request).graph(body.root)


@v1_router.post("/code/patterns", tags=["code"])
def code_patterns(body: CodeRepoRequest, request: Request) -> dict:
    return {"patterns": _code(request).patterns(body.root)}


@v1_router.post("/code/symbols", tags=["code"])
def code_symbols(body: CodeSymbolsRequest, request: Request) -> dict:
    symbols = _code(request).search_symbols(
        body.query, root=body.root, kind=body.kind, lang=body.lang, limit=body.limit
    )
    return {"symbols": symbols}


@v1_router.post("/code/explain", tags=["code"])
def code_explain(body: CodeExplainRequest, request: Request) -> dict:
    return _code(request).explain(body.path, body.question)


@v1_router.post("/python/run", tags=["python"])
def python_run(body: PythonRunRequest, request: Request) -> dict:
    sandbox = _app(request).container.resolve("python")
    return sandbox.run(
        body.code, timeout=body.timeout, files=body.files, stdin=body.stdin
    )


@v1_router.post("/report", tags=["reports"])
def report(body: ReportRequest, request: Request) -> dict:
    reports = _app(request).container.resolve("reports")
    return reports.report(
        body.objective,
        {"claims": body.claims, "sources": body.sources or []},
        budget=body.budget,
        notes=body.notes or "",
    )


@v1_router.get("/learning/events", tags=["learning"])
def learning_events(
    request: Request, status: str | None = None, store: str | None = None, limit: int = 50
) -> dict:
    learning = _app(request).container.resolve("learning")
    return {"events": learning.list_events(status=status, store=store, limit=limit)}


@v1_router.get("/learning/events/{event_id}", tags=["learning"])
def learning_event(event_id: str, request: Request) -> dict:
    learning = _app(request).container.resolve("learning")
    try:
        return learning.explain(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="learning event not found")


@v1_router.post("/learning/events/{event_id}/apply", tags=["learning"])
def learning_apply(event_id: str, body: LearningApplyRequest, request: Request) -> dict:
    learning = _app(request).container.resolve("learning")
    try:
        return learning.apply(event_id, policy=body.policy, level=body.level)
    except KeyError:
        raise HTTPException(status_code=404, detail="learning event not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@v1_router.post("/learning/events/{event_id}/revert", tags=["learning"])
def learning_revert(event_id: str, request: Request) -> dict:
    learning = _app(request).container.resolve("learning")
    try:
        return learning.revert(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="learning event not found")


@v1_router.get("/learning/experiences", tags=["learning"])
def learning_experiences(request: Request, q: str | None = None, limit: int = 50) -> dict:
    learning = _app(request).container.resolve("learning")
    if q:
        return {"experiences": learning.recall(q, limit=limit)}
    return {"experiences": learning.list_experiences(limit=limit)}


@v1_router.post("/learning/experiences", tags=["learning"])
def learning_remember(body: ExperienceRequest, request: Request) -> dict:
    learning = _app(request).container.resolve("learning")
    return learning.remember_experience(**body.model_dump(exclude_none=True))


@v1_router.post("/intelligence/repositories", tags=["intelligence"])
def intel_learn(body: LearnRepositoryRequest, request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.learn_repository(body.root, policy=body.policy, apply=body.apply)


@v1_router.get("/intelligence/repositories", tags=["intelligence"])
def intel_repositories(request: Request, limit: int = 100) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return {"repositories": intel.list_repositories(limit=limit)}


@v1_router.get("/intelligence/repositories/{repo_id}", tags=["intelligence"])
def intel_repository(repo_id: str, request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    rec = intel.get_repository(repo_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return rec


@v1_router.get("/intelligence/search", tags=["intelligence"])
def intel_search(request: Request, q: str = "", limit: int = 20) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.search(q, limit=limit)


@v1_router.get("/intelligence/connections", tags=["intelligence"])
def intel_connections(request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.connections()


@v1_router.post("/intelligence/generalize", tags=["intelligence"])
def intel_generalize(request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.generalize()


@v1_router.get("/intelligence/patterns", tags=["intelligence"])
def intel_patterns(request: Request, limit: int = 100) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return {"patterns": intel.patterns(limit=limit)}


@v1_router.post("/intelligence/recommend", tags=["intelligence"])
def intel_recommend(body: RecommendRequest, request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.recommend(body.context, limit=body.limit)


@v1_router.get("/intelligence/profile", tags=["intelligence"])
def intel_profile(request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return intel.profile()


@v1_router.post("/verify", response_model=VerifyResponse, tags=["verification"])
def verify(body: VerifyRequest, request: Request) -> VerifyResponse:
    verification = _app(request).container.resolve("verification")
    result = verification.verify(
        {"claims": body.claims, "sources": body.sources or []}, budget=body.budget
    )
    return VerifyResponse(**result)


@v1_router.post("/jobs", response_model=JobDetailResponse, tags=["jobs"])
def create_job(body: CreateJobRequest, request: Request) -> JobDetailResponse:
    jobs = _app(request).container.resolve("jobs")
    detail = jobs.create_job(body.objective, session_id=body.session_id)
    return _job_detail(detail)


@v1_router.get("/jobs", response_model=JobsResponse, tags=["jobs"])
def list_jobs(request: Request, status: str | None = None, limit: int = 50) -> JobsResponse:
    jobs = _app(request).container.resolve("jobs")
    return JobsResponse(jobs=[_job_out(j) for j in jobs.list_jobs(status=status, limit=limit)])


@v1_router.get("/jobs/blocked", tags=["jobs"])
def list_blocked_jobs(request: Request, limit: int = 50) -> dict:
    jobs = _app(request).container.resolve("jobs")
    return {"blocked": jobs.list_blocked(limit=limit)}


@v1_router.get("/jobs/{job_id}", response_model=JobDetailResponse, tags=["jobs"])
def get_job(job_id: str, request: Request) -> JobDetailResponse:
    jobs = _app(request).container.resolve("jobs")
    try:
        return _job_detail(jobs.job_detail(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")


@v1_router.post("/jobs/{job_id}/resume", response_model=JobDetailResponse, tags=["jobs"])
def resume_job(job_id: str, request: Request) -> JobDetailResponse:
    jobs = _app(request).container.resolve("jobs")
    try:
        return _job_detail(jobs.resume_job(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")


@v1_router.post("/jobs/{job_id}/cancel", response_model=JobDetailResponse, tags=["jobs"])
def cancel_job(job_id: str, request: Request) -> JobDetailResponse:
    jobs = _app(request).container.resolve("jobs")
    try:
        return _job_detail(jobs.cancel_job(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")


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


@v1_router.get("/capabilities", response_model=CapabilitiesResponse, tags=["plugins"])
def list_capabilities(request: Request) -> CapabilitiesResponse:
    """Honest inventory of what Atlas can and cannot do (R2).

    Merges the capability catalog with what's actually registered, so a caller can
    see which capabilities are ``provided`` and what building the missing ones
    unlocks.
    """
    from atlas.capabilities import describe_capabilities

    registry = _app(request).capabilities
    rows = describe_capabilities(registry)
    return CapabilitiesResponse(capabilities=[CapabilityInfo(**r) for r in rows])


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
