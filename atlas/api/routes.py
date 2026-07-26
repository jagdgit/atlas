"""HTTP routes for the Atlas REST API.

Routes are thin: they resolve kernel services from the running Application's DI
container and translate to/from the public schemas. No SQL, no provider calls
here — the API is just another caller of the same services agents use (ADR-0006).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from atlas.notify.broker import sse_stream

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
    BridgeIngestRequest,
    BridgeIngestResponse,
    InvokeToolRequest,
    InvokeToolResponse,
    InstantiateMissionRequest,
    PlanProgramRequest,
    ProgramChatRequest,
    ProgramShareRequest,
    CreateVirtualPortfolioRequest,
    WithdrawPortfolioRequest,
    ScreenerSnapshotRequest,
    ScreenerComputeRequest,
    FilingsSnapshotRequest,
    CreateGoalRequest,
    UpdateGoalRequest,
    StartProgramRequest,
    ApprovalActionRequest,
    CreateMissionRequest,
    MissionActionRequest,
    PersonalLearnCvRequest,
    LinkedInCoachRequest,
    BestJobsRequest,
    RegisterAssetRequest,
    UpdateMissionConfigRequest,
    WorkerActionRequest,
    WorkerInputRequest,
    JobDetailResponse,
    JobInputRequest,
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
    StatusResponse,
    CodeExplainRequest,
    CodeParseRequest,
    CodeRepoRequest,
    CodeSymbolsRequest,
    EngineeringIngestRequest,
    ExperienceRequest,
    GitRequest,
    LearningApplyRequest,
    LearnRepositoryRequest,
    PersonalCorrectRequest,
    PersonalFactRequest,
    KnowledgeResolveRequest,
    PolicyRuleRequest,
    RecommendRequest,
    PythonRunRequest,
    ReportRequest,
    BrowseRequest,
    MailSearchRequest,
    OCRRequest,
    ResearchRequest,
    ScholarSearchRequest,
    ScreenshotRequest,
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
        name: ServiceHealth(
            healthy=s.healthy, detail=s.detail, severity=s.level, data=s.data
        )
        for name, s in report.items()
    }
    healthy = all(s.healthy for s in report.values())
    degraded = any(s.degraded for s in report.values())
    return DetailedHealthResponse(healthy=healthy, degraded=degraded, services=services)


@v1_router.get("/status", response_model=StatusResponse, tags=["health"])
def status(request: Request) -> StatusResponse:
    """Operability summary (S22): version, uptime, and a severity roll-up."""
    return StatusResponse(**_app(request).status())


def _event_row(row: dict) -> dict:
    """JSON-safe projection of an ``audit.events`` row."""
    return {
        "id": str(row.get("id")),
        "type": row.get("event_type"),
        "source": row.get("source"),
        "payload": row.get("payload") or {},
        "status": row.get("status"),
        "created_at": (
            row["created_at"].isoformat() if row.get("created_at") else None
        ),
    }


@v1_router.get("/events", tags=["events"])
def recent_events(
    request: Request, limit: int = 100, event_type: str | None = None
) -> dict:
    """Recent events from the durable log (``audit.events``) — newest first (§2.5)."""
    repo = _app(request).container.resolve("event_repo")
    rows = repo.recent(limit=limit, event_type=event_type)
    return {"events": [_event_row(r) for r in rows]}


@v1_router.get("/ops", tags=["ops"])
def ops_dashboard(request: Request) -> dict:
    """Operations Dashboard snapshot (§5.11): the single-screen operator view."""
    return _app(request).container.resolve("ops_dashboard").snapshot()


@v1_router.get("/events/stream", tags=["events"])
def events_stream(request: Request) -> StreamingResponse:
    """Live event stream over Server-Sent Events (§2.5): the web console's push feed."""
    notifier = _app(request).container.resolve("notifier")
    q = notifier.subscribe()
    return StreamingResponse(
        sse_stream(q, broker=notifier.broker),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


def _job_out(job, *, phase: str | None = None) -> JobOut:
    meta = job.metadata if isinstance(getattr(job, "metadata", None), dict) else {}
    resolved = phase or meta.get("phase") or "ready"
    return JobOut(
        id=job.id,
        objective=job.objective,
        status=job.status,
        phase=str(resolved),
        session_id=job.session_id,
        mission_id=getattr(job, "mission_id", None),
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
        result=step.result or {},
        started_at=step.started_at.isoformat() if step.started_at else None,
        completed_at=step.completed_at.isoformat() if step.completed_at else None,
    )


def _job_detail(detail) -> JobDetailResponse:
    return JobDetailResponse(
        job=_job_out(detail["job"], phase=detail.get("phase")),
        steps=[_step_out(s) for s in detail["steps"]],
        progress=detail["progress"],
        blocked=detail["blocked"],
        activity=detail.get("activity", []),
        usage=detail.get("usage"),
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


# --- ocr (S20c): image → text --------------------------------------------
@v1_router.post("/ocr", tags=["ocr"])
def ocr(body: OCRRequest, request: Request) -> dict:
    return _app(request).invoke_tool("ocr.image", path=body.path, lang=body.lang)


# --- mail (S20d): read-only email ----------------------------------------
@v1_router.post("/mail/search", tags=["mail"])
def mail_search(body: MailSearchRequest, request: Request) -> dict:
    return _app(request).invoke_tool(
        "mail.search", query=body.query, folder=body.folder, limit=body.limit
    )


@v1_router.get("/mail/folders", tags=["mail"])
def mail_folders(request: Request) -> dict:
    return _app(request).invoke_tool("mail.folders")


@v1_router.get("/mail/message", tags=["mail"])
def mail_message(request: Request, uid: str, folder: str | None = None) -> dict:
    return _app(request).invoke_tool("mail.message", uid=uid, folder=folder)


# --- browser (S20e): headless render (read-only) -------------------------
@v1_router.post("/browser/open", tags=["browser"])
def browser_open(body: BrowseRequest, request: Request) -> dict:
    return _app(request).invoke_tool("browser.open", url=body.url)


@v1_router.post("/browser/screenshot", tags=["browser"])
def browser_screenshot(body: ScreenshotRequest, request: Request) -> dict:
    return _app(request).invoke_tool(
        "browser.screenshot", url=body.url, path=body.path, full_page=body.full_page
    )


# --- research (S21): autonomous gather→verify→decide loop -----------------
@v1_router.post("/research", tags=["research"])
def research(body: ResearchRequest, request: Request) -> dict:
    return _app(request).invoke_tool(
        "research.run", objective=body.objective, max_iterations=body.max_iterations
    )


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


@v1_router.get("/learning/advice", tags=["learning"])
def learning_advice(request: Request, q: str = "", limit: int = 5) -> dict:
    """Non-mutating experience advice for planning/research (3B.5)."""
    learning = _app(request).container.resolve("learning")
    return learning.advice_for(q, limit=limit)


@v1_router.get("/experience/shape", tags=["experience"])
def experience_shape(request: Request) -> dict:
    """Experience OS journal shape — Observation→…→Lesson (EX.1 / OI-MP1)."""
    try:
        eos = _app(request).container.resolve("experience_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"experience_os unavailable: {exc}") from exc
    return eos.shape()


@v1_router.post("/experience/journal", tags=["experience"])
def experience_journal(request: Request, body: dict | None = None) -> dict:
    """Write a structured Experience Journal entry (EX.1)."""
    try:
        eos = _app(request).container.resolve("experience_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"experience_os unavailable: {exc}") from exc
    payload = body or {}
    required = ("observation", "decision", "outcome", "reflection", "lesson")
    missing = [k for k in required if not str(payload.get(k) or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing journal fields: {missing}")
    title = str(payload.get("title") or payload.get("lesson") or "Experience")[:200]
    return eos.journal(
        title=title,
        observation=str(payload.get("observation") or ""),
        reasoning=str(payload.get("reasoning") or ""),
        decision=str(payload.get("decision") or ""),
        outcome=str(payload.get("outcome") or ""),
        reflection=str(payload.get("reflection") or ""),
        lesson=str(payload.get("lesson") or ""),
        domain=str(payload.get("domain") or "general"),
        tags=list(payload.get("tags") or []),
        recommendations=list(payload.get("recommendations") or []),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        strict=bool(payload.get("strict", True)),
    )


@v1_router.get("/experience/recall", tags=["experience"])
def experience_recall(request: Request, q: str = "", limit: int = 20) -> dict:
    """Recall Experiences as structured journals (EX.1)."""
    try:
        eos = _app(request).container.resolve("experience_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"experience_os unavailable: {exc}") from exc
    if q.strip():
        return {"journals": eos.recall(q, limit=limit), "query": q}
    return {"journals": eos.list_journals(limit=limit)}


@v1_router.get("/experience/advice", tags=["experience"])
def experience_advice(request: Request, q: str = "", limit: int = 5) -> dict:
    """Advice from Experience OS (structured journals + legacy advice_for)."""
    try:
        eos = _app(request).container.resolve("experience_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"experience_os unavailable: {exc}") from exc
    return eos.advice_for(q, limit=limit)


@v1_router.get("/learning/sources", tags=["learning"])
def learning_sources(request: Request, limit: int = 20) -> dict:
    """Operational source-reliability advice (prefer/deprioritize) — advice-only (§3B)."""
    learning = _app(request).container.resolve("learning")
    return learning.source_advice(limit=limit)


@v1_router.post("/learning/experiences/{experience_id}/bias", tags=["learning"])
def learning_enable_bias(
    experience_id: str, request: Request, enabled: bool = True
) -> dict:
    """Explicit soft-bias gate after apply (D3B.12). Default remains off."""
    learning = _app(request).container.resolve("learning")
    try:
        return learning.enable_bias(experience_id, enabled=enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="experience not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@v1_router.get("/learning/components", tags=["learning"])
def learning_components(
    request: Request, component_key: str | None = None, limit: int = 50
) -> dict:
    learning = _app(request).container.resolve("learning")
    return {
        "observations": learning.list_component_observations(
            component_key=component_key, limit=limit
        )
    }


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


@v1_router.post(
    "/intelligence/repositories/{repo_uid}/design-review", tags=["intelligence"]
)
def intel_design_review(repo_uid: str, request: Request) -> dict:
    """On-demand advice-only design review for a learned repo (B.5, structural-change-gated
    during ingest; always available on demand here)."""
    intel = _app(request).container.resolve("intelligence")
    return intel.review_design(repo_uid)


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


# --- Engineering Intelligence (Phase B · §B.7) ---------------------------
def _repo_uid_for(intel, repo_id: str) -> tuple[dict, str]:
    """Resolve a learned-repository id → (record, repo_uid); 404 if unknown."""
    rec = intel.get_repository(repo_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="repository not found")
    repo_uid = rec.get("repo_uid")
    if not repo_uid:
        raise HTTPException(status_code=409, detail="repository has no stable repo_uid")
    return rec, repo_uid


@v1_router.get("/engineering/repositories", tags=["engineering"])
def eng_repositories(request: Request, limit: int = 100) -> dict:
    intel = _app(request).container.resolve("intelligence")
    return {"repositories": intel.list_repositories(limit=limit)}


@v1_router.get("/engineering/repositories/{repo_id}", tags=["engineering"])
def eng_repository(repo_id: str, request: Request) -> dict:
    intel = _app(request).container.resolve("intelligence")
    rec, repo_uid = _repo_uid_for(intel, repo_id)
    return {"repository": rec, "graph_versions": intel.architecture_graph_versions(repo_uid)}


@v1_router.get("/engineering/repositories/{repo_id}/graph", tags=["engineering"])
def eng_repository_graph(repo_id: str, request: Request, version: int | None = None) -> dict:
    intel = _app(request).container.resolve("intelligence")
    _, repo_uid = _repo_uid_for(intel, repo_id)
    graph = intel.architecture_graph(repo_uid, version=version)
    if graph is None:
        raise HTTPException(status_code=404, detail="no architecture graph for this repository")
    return graph


@v1_router.get("/engineering/repositories/{repo_id}/graph/diff", tags=["engineering"])
def eng_repository_graph_diff(
    repo_id: str, request: Request, from_version: int, to_version: int
) -> dict:
    intel = _app(request).container.resolve("intelligence")
    _, repo_uid = _repo_uid_for(intel, repo_id)
    diff = intel.architecture_graph_diff(repo_uid, from_version, to_version)
    if diff is None:
        raise HTTPException(status_code=404, detail="graph version(s) not found")
    return diff


@v1_router.get("/engineering/findings", tags=["engineering"])
def eng_findings(
    request: Request,
    repo_id: str | None = None,
    claim_type: str | None = None,
    mission_id: str | None = None,
    job_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Engineering findings, optionally scoped by repo, claim type, or **who discovered them**
    (``mission_id``/``job_id`` — P12 provenance, a read-only lens, never ownership)."""
    intel = _app(request).container.resolve("intelligence")
    repo_uid = None
    if repo_id:
        _, repo_uid = _repo_uid_for(intel, repo_id)
    return {
        "findings": intel.list_findings(
            repo_uid=repo_uid, claim_type=claim_type,
            mission_id=mission_id, job_id=job_id, limit=limit,
        )
    }


@v1_router.get("/knowledge/coverage", tags=["knowledge"])
def knowledge_coverage(request: Request) -> dict:
    """Knowledge coverage map (Phase C · §C.4): per-domain **coverage %** (how much was read) and
    **understanding %** (how well it is understood, from finding maturity/confidence), plus an overall
    rollup. Coverage ≠ comprehension — both are surfaced side by side."""
    return _app(request).container.resolve("coverage").summary()


@v1_router.get("/knowledge/graph", tags=["knowledge"])
def knowledge_graph(
    request: Request,
    q: str = "",
    domain: str | None = None,
    limit_findings: int = 200,
    limit_nodes: int = 80,
    limit_edges: int = 120,
) -> dict:
    """Derived Knowledge Graph over findings (KG.1) — Claim↔Concept↔Entity↔SPO."""
    try:
        graph = _app(request).container.resolve("knowledge_graph")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"knowledge_graph unavailable: {exc}"
        ) from exc
    return graph.snapshot(
        q=q or None,
        domain=domain,
        limit_findings=limit_findings,
        limit_nodes=limit_nodes,
        limit_edges=limit_edges,
    )


@v1_router.get("/knowledge/contested", tags=["knowledge"])
def knowledge_contested(
    request: Request,
    domain: str | None = None,
    limit: int = 50,
) -> dict:
    """Contested knowledge heads for the Conflict Resolver (OI-B3)."""
    lifecycle = _knowledge_lifecycle(request)
    rows = lifecycle.list_contested(domain=domain, limit=max(1, min(limit, 200)))
    return {"findings": rows, "count": len(rows)}


@v1_router.post("/knowledge/findings/{finding_id}/resolve", tags=["knowledge"])
def knowledge_resolve(
    finding_id: str, body: KnowledgeResolveRequest, request: Request
) -> dict:
    """Apply an operator conflict resolution (hold / supersede / reactivate)."""
    lifecycle = _knowledge_lifecycle(request)
    try:
        return lifecycle.resolve_conflict(
            finding_id,
            action=body.action,
            note=body.note or "",
            clear_contradicting=bool(body.clear_contradicting),
            actor=body.actor or "operator",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="finding not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@v1_router.post("/knowledge/conflicts/decide", tags=["knowledge"])
def knowledge_conflict_decide(request: Request, finding_id: str = "") -> dict:
    """Ask the Decision Engine for a conflict-resolution recommendation (OI-B3)."""
    finding_id = (finding_id or "").strip()
    if not finding_id:
        raise HTTPException(status_code=422, detail="finding_id required")
    lifecycle = _knowledge_lifecycle(request)
    store = getattr(lifecycle, "_store", None)
    row = store.get(finding_id) if store is not None else None
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    from atlas.decision.contracts import DecisionRequest
    from atlas.knowledge.conflict import MISSION_TYPE_KNOWLEDGE_CONFLICT

    engine = _app(request).container.resolve("decision")
    decision = engine.decide(
        DecisionRequest(
            mission_id=None,
            mission_type=MISSION_TYPE_KNOWLEDGE_CONFLICT,
            context={"finding_id": finding_id, "finding": dict(row)},
        )
    )
    if hasattr(decision, "to_dict"):
        return decision.to_dict()
    if hasattr(decision, "as_dict"):
        return decision.as_dict()
    return dict(decision) if isinstance(decision, dict) else {"decision": str(decision)}


def _knowledge_lifecycle(request: Request):
    container = _app(request).container
    try:
        return container.resolve("knowledge_lifecycle")
    except Exception:
        knowledge = container.resolve("knowledge")
        lifecycle = getattr(knowledge, "_lifecycle", None)
        if lifecycle is None:
            raise HTTPException(status_code=503, detail="knowledge lifecycle unavailable")
        return lifecycle


@v1_router.get("/policy/rules", tags=["policy"])
def policy_rules(
    request: Request,
    scope: str | None = None,
    rule: str | None = None,
    enabled: bool | None = None,
    limit: int = 200,
) -> dict:
    """List operator policy rules (Phase C · §C.5). Influence, not arbitration (CC8)."""
    policy = _app(request).container.resolve("policy")
    return {"rules": policy.list_rules(scope=scope, rule=rule, enabled=enabled, limit=limit)}


@v1_router.post("/policy/evaluate", tags=["policy"])
def policy_evaluate(request: Request, body: dict | None = None) -> dict:
    """Policy Engine — hard/soft evaluation for an intended action (PA.2 / OI-PA-POLICY)."""
    try:
        engine = _app(request).container.resolve("policy_engine")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"policy_engine unavailable: {exc}") from exc
    payload = body or {}
    return engine.evaluate(
        action=payload.get("action") if isinstance(payload.get("action"), dict) else payload,
        context=payload.get("context") if isinstance(payload.get("context"), dict) else {},
        scope=payload.get("scope"),
        scopes=payload.get("scopes") if isinstance(payload.get("scopes"), list) else None,
    )


@v1_router.post("/policy/rules", tags=["policy"])
def policy_create_rule(body: PolicyRuleRequest, request: Request) -> dict:
    """Create (or upsert) a policy rule. Journaled + reversible."""
    policy = _app(request).container.resolve("policy")
    return policy.create_rule(**body.model_dump(exclude_none=True))


@v1_router.get("/policy/rules/{rule_id}", tags=["policy"])
def policy_rule(rule_id: str, request: Request) -> dict:
    policy = _app(request).container.resolve("policy")
    rule = policy.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="policy rule not found")
    return rule


@v1_router.post("/policy/rules/{rule_id}/enable", tags=["policy"])
def policy_enable_rule(rule_id: str, request: Request, enabled: bool = True) -> dict:
    """Enable or (with ?enabled=false) disable a rule."""
    policy = _app(request).container.resolve("policy")
    try:
        return policy.set_enabled(rule_id, enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="policy rule not found")


@v1_router.delete("/policy/rules/{rule_id}", tags=["policy"])
def policy_delete_rule(
    rule_id: str, request: Request, actor: str | None = None
) -> dict:
    """Hard-delete a policy rule (OI-C9). Prefer disable+revert for reversible edits."""
    policy = _app(request).container.resolve("policy")
    try:
        return {"deleted": policy.delete_rule(rule_id, actor=actor)}
    except KeyError:
        raise HTTPException(status_code=404, detail="policy rule not found")


@v1_router.get("/policy/events", tags=["policy"])
def policy_events(request: Request, rule_id: str | None = None, limit: int = 100) -> dict:
    policy = _app(request).container.resolve("policy")
    return {"events": policy.list_events(rule_id=rule_id, limit=limit)}


@v1_router.post("/policy/events/{event_id}/revert", tags=["policy"])
def policy_revert(event_id: str, request: Request) -> dict:
    """Undo a policy change, restoring the prior state (governed + reversible)."""
    policy = _app(request).container.resolve("policy")
    try:
        return {"reverted": policy.revert(event_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="policy event not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- Decision Engine (Phase D · §D.5) — the P9 "explain this" surface -------

@v1_router.get("/decision/decisions", tags=["decision"])
def decision_list(
    request: Request,
    mission_id: str | None = None,
    mission_type: str | None = None,
    action_kind: str | None = None,
    limit: int = 100,
) -> dict:
    """List journaled decisions (recommend-only; P14). Filter by mission/type/action_kind."""
    decision = _app(request).container.resolve("decision")
    return {
        "decisions": decision.list_decisions(
            mission_id=mission_id, mission_type=mission_type,
            action_kind=action_kind, limit=limit,
        )
    }


@v1_router.get("/decision/gaps", tags=["decision"])
def decision_gaps(request: Request, limit: int = 100) -> dict:
    """The capability-gap backlog (P15): what Atlas honestly reported it could not do."""
    decision = _app(request).container.resolve("decision")
    return {"gaps": decision.list_gaps(limit=limit)}


@v1_router.get("/decision/decisions/{decision_id}", tags=["decision"])
def decision_explain(decision_id: str, request: Request) -> dict:
    """The full P9 record for one decision — action, why, refs, versions, alternatives rejected."""
    decision = _app(request).container.resolve("decision")
    row = decision.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return row


# --- Human-approval gate (Phase D · §D.5, P14) -----------------------------

@v1_router.get("/decision/approvals", tags=["decision"])
def approvals_list(
    request: Request,
    status: str | None = None,
    mission_id: str | None = None,
    limit: int = 100,
) -> dict:
    """List approvals (default: all). Use ?status=proposed for the operator's pending queue."""
    approvals = _app(request).container.resolve("approvals")
    return {"approvals": approvals.list(status=status, mission_id=mission_id, limit=limit)}


@v1_router.get("/decision/approvals/{approval_id}", tags=["decision"])
def approval_get(approval_id: str, request: Request) -> dict:
    approvals = _app(request).container.resolve("approvals")
    row = approvals.get(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return row


def _approval_action(request: Request, approval_id: str, action: str, body: ApprovalActionRequest) -> dict:
    from atlas.decision import ApprovalError

    approvals = _app(request).container.resolve("approvals")
    fn = getattr(approvals, action)
    try:
        if action == "reject":
            return fn(approval_id, actor=body.actor, note=body.note)
        return fn(approval_id, actor=body.actor)
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@v1_router.post("/decision/approvals/{approval_id}/approve", tags=["decision"])
def approval_approve(approval_id: str, body: ApprovalActionRequest, request: Request) -> dict:
    """Approve a proposed side-effecting decision (does not apply it yet)."""
    return _approval_action(request, approval_id, "approve", body)


@v1_router.post("/decision/approvals/{approval_id}/reject", tags=["decision"])
def approval_reject(approval_id: str, body: ApprovalActionRequest, request: Request) -> dict:
    return _approval_action(request, approval_id, "reject", body)


@v1_router.post("/decision/approvals/{approval_id}/apply", tags=["decision"])
def approval_apply(approval_id: str, body: ApprovalActionRequest, request: Request) -> dict:
    """Execute an approved action via its registered applier, capturing before/after for revert."""
    return _approval_action(request, approval_id, "apply", body)


@v1_router.post("/decision/approvals/{approval_id}/revert", tags=["decision"])
def approval_revert(approval_id: str, body: ApprovalActionRequest, request: Request) -> dict:
    """Undo an applied action from its recorded snapshot (reversible, P14)."""
    return _approval_action(request, approval_id, "revert", body)


@v1_router.get("/personal/profile", tags=["personal"])
def personal_profile(request: Request, include_inferred: bool = True) -> dict:
    """The assembled owner profile — identity/skills/timeline/professional (Phase C · §C.7)."""
    return _app(request).container.resolve("personal").profile(include_inferred=include_inferred)


@v1_router.get("/personal/facts", tags=["personal"])
def personal_facts(
    request: Request,
    category: str | None = None,
    state: str | None = None,
    limit: int = 500,
) -> dict:
    personal = _app(request).container.resolve("personal")
    return {"facts": personal.list_facts(category=category, state=state, limit=limit)}


@v1_router.post("/personal/facts", tags=["personal"])
def personal_add_fact(body: PersonalFactRequest, request: Request) -> dict:
    """Operator adds an authoritative fact directly (starts life verified)."""
    personal = _app(request).container.resolve("personal")
    return personal.add_fact(**body.model_dump(exclude_none=True))


@v1_router.post("/personal/infer", tags=["personal"])
def personal_infer(request: Request) -> dict:
    """Refresh inferred facts from Experience + Engineering knowledge (CC7; no silent scraping)."""
    return _app(request).container.resolve("personal").infer()


@v1_router.post("/personal/facts/{fact_id}/confirm", tags=["personal"])
def personal_confirm(fact_id: str, request: Request) -> dict:
    """Operator confirms an inferred fact → verified (CC7/A9)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.confirm(fact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="personal fact not found")


@v1_router.post("/personal/facts/{fact_id}/correct", tags=["personal"])
def personal_correct(fact_id: str, body: PersonalCorrectRequest, request: Request) -> dict:
    """Operator edits a fact (and thereby verifies it)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.correct(fact_id, **body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="personal fact not found")


@v1_router.post("/personal/facts/{fact_id}/reject", tags=["personal"])
def personal_reject(fact_id: str, request: Request) -> dict:
    """Operator rejects a fact → rejected (Atlas will not re-infer over it)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.reject(fact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="personal fact not found")


@v1_router.get("/personal/dashboard", tags=["personal"])
def personal_dashboard(request: Request, include_inferred: bool = True) -> dict:
    """The Personal/Owner console view (Phase C · §C.8): per-domain coverage + skills/timeline.

    Combines the knowledge coverage map (C.4 — coverage% and understanding% per domain) with the
    assembled owner profile (C.7). Live updates ride the shared SSE feed at /v1/events/stream.
    """
    container = _app(request).container
    personal = container.resolve("personal")
    profile = personal.profile(include_inferred=include_inferred)
    try:
        coverage = container.resolve("coverage").summary()
    except Exception:  # noqa: BLE001 - dashboard degrades gracefully without coverage
        coverage = {}
    career: dict = {}
    try:
        career["linkedin"] = personal.linkedin_suggestions(include_inferred=include_inferred)
    except Exception as exc:  # noqa: BLE001
        career["linkedin"] = {"error": str(exc), "can_write_linkedin": False}
    try:
        assets = None
        reader = None
        engine = None
        try:
            assets = container.resolve("assets")
        except Exception:  # noqa: BLE001
            pass
        try:
            reader = container.resolve("job_postings_reader")
        except Exception:  # noqa: BLE001
            try:
                reader = container.resolve("readers")
            except Exception:  # noqa: BLE001
                reader = None
        try:
            engine = container.resolve("decision")
        except Exception:  # noqa: BLE001
            pass
        career["jobs"] = personal.best_jobs(
            assets=assets,
            postings_reader=reader if hasattr(reader, "read") else None,
            decision_engine=engine,
            limit=8,
            include_inferred_skills=include_inferred,
        )
    except Exception as exc:  # noqa: BLE001
        career["jobs"] = {"jobs": [], "error": str(exc), "can_apply": False}
    return {
        "coverage": coverage,
        "identity": profile.get("identity", []),
        "skills": profile.get("skills", []),
        "timeline": profile.get("timeline", []),
        "professional": profile.get("professional", []),
        "career": career,
        "counts": {
            "skills": len(profile.get("skills", [])),
            "timeline": len(profile.get("timeline", [])),
            "professional": len(profile.get("professional", [])),
        },
    }


@v1_router.post("/personal/learn-cv", tags=["personal"])
def personal_learn_cv(body: PersonalLearnCvRequest, request: Request) -> dict:
    """Parse a CV on the Atlas host into inferred Personal facts (Confirm/Reject next)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.learn_from_cv_path(body.path, actor=body.actor or "operator")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@v1_router.post("/personal/linkedin/suggestions", tags=["personal"])
def personal_linkedin_suggestions(body: LinkedInCoachRequest, request: Request) -> dict:
    """LinkedIn profile improvement suggestions — Atlas never writes to LinkedIn (P10)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.linkedin_suggestions(
            linkedin_text=body.linkedin_text,
            linkedin_path=body.linkedin_path,
            linkedin_url=body.linkedin_url,
            include_inferred=body.include_inferred,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@v1_router.get("/personal/jobs", tags=["personal"])
@v1_router.post("/personal/jobs", tags=["personal"])
def personal_best_jobs(
    request: Request,
    body: BestJobsRequest | None = None,
    limit: int = 10,
    include_inferred_skills: bool = True,
    feed_path: str | None = None,
) -> dict:
    """Best open jobs for the Personal profile (recommend-only; never apply)."""
    container = _app(request).container
    personal = container.resolve("personal")
    payload = body or BestJobsRequest(
        limit=limit,
        include_inferred_skills=include_inferred_skills,
        feed_path=feed_path,
    )
    assets = None
    reader = None
    engine = None
    try:
        assets = container.resolve("assets")
    except Exception:  # noqa: BLE001
        pass
    try:
        reader = container.resolve("job_postings_reader")
    except Exception:  # noqa: BLE001
        pass
    try:
        engine = container.resolve("decision")
    except Exception:  # noqa: BLE001
        pass
    return personal.best_jobs(
        assets=assets,
        postings_reader=reader,
        decision_engine=engine,
        feed_path=payload.feed_path,
        limit=payload.limit,
        include_inferred_skills=payload.include_inferred_skills,
    )


@v1_router.get("/personal/draft", tags=["personal"])
def personal_draft(request: Request, kind: str = "resume", include_inferred: bool = False) -> dict:
    """Draft a resume/LinkedIn summary purely from the profile (retrieval, not action; P10)."""
    personal = _app(request).container.resolve("personal")
    try:
        return personal.draft(kind, include_inferred=include_inferred)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@v1_router.get("/personal/events", tags=["personal"])
def personal_events(request: Request, fact_id: str | None = None, limit: int = 100) -> dict:
    personal = _app(request).container.resolve("personal")
    return {"events": personal.list_events(fact_id=fact_id, limit=limit)}


@v1_router.post("/personal/events/{event_id}/revert", tags=["personal"])
def personal_revert(event_id: str, request: Request) -> dict:
    """Undo a personal-fact change, restoring the prior state (governed + reversible)."""
    personal = _app(request).container.resolve("personal")
    try:
        return {"reverted": personal.revert(event_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="personal event not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@v1_router.post("/engineering/ingest", tags=["engineering"])
def eng_ingest(body: EngineeringIngestRequest, request: Request) -> dict:
    if bool(body.path) == bool(body.url):
        raise HTTPException(status_code=422, detail="provide exactly one of path or url")
    app = _app(request)
    intel = app.container.resolve("intelligence")
    out = intel.learn_repository(
        path=body.path, url=body.url, branch=body.branch,
        mission_id=body.mission_id, policy=body.policy, embed=body.embed,
    )
    _emit_engineering_event(app, "EngineeringIngested", out)
    return out


@v1_router.post("/engineering/design-review/{repo_id}", tags=["engineering"])
def eng_design_review(repo_id: str, request: Request) -> dict:
    app = _app(request)
    intel = app.container.resolve("intelligence")
    _, repo_uid = _repo_uid_for(intel, repo_id)
    out = intel.review_design(repo_uid)
    _emit_engineering_event(app, "DesignReviewed", out)
    return out


def _emit_engineering_event(app, event_type: str, out: dict) -> None:
    """Push an engineering event onto the bus so the console updates live (best-effort)."""
    try:
        events = app.container.resolve("events")
    except Exception:  # noqa: BLE001 - events are optional; ingest still succeeds
        return
    try:
        events.emit(
            event_type,
            {
                "outcome": out.get("outcome"),
                "repo_uid": (out.get("repository") or {}).get("repo_uid")
                or out.get("repo_uid"),
                "findings": out.get("findings"),
                "design_findings": out.get("design_findings"),
            },
            source="engineering",
        )
    except Exception:  # noqa: BLE001 - telemetry must never fail the request
        pass


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
    detail = jobs.create_job(
        body.objective, session_id=body.session_id, mission_id=body.mission_id
    )
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


@v1_router.post("/jobs/{job_id}/input", response_model=JobDetailResponse, tags=["jobs"])
def add_job_input(job_id: str, body: JobInputRequest, request: Request) -> JobDetailResponse:
    """Queue human guidance for a job (picked up between research rounds)."""
    jobs = _app(request).container.resolve("jobs")
    try:
        return _job_detail(jobs.add_job_input(job_id, body.text))
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# --- missions / workers / templates (Phase A · §A.7) ---------------------
def _missions(request: Request):
    return _app(request).container.resolve("missions")


def _workers(request: Request):
    return _app(request).container.resolve("workers")


def _templates(request: Request):
    return _app(request).container.resolve("templates")


def _programs(request: Request):
    return _app(request).container.resolve("programs")


def _configuration(request: Request):
    return _app(request).container.resolve("configuration")


def _assets(request: Request):
    return _app(request).container.resolve("assets")


def _mission_error(exc: Exception) -> HTTPException:
    """Map a MissionError/WorkerError/TemplateError/ConfigError to a sensible HTTP status."""
    msg = str(exc)
    low = msg.lower()
    if "not found" in low or "unknown template" in low or "unknown worker" in low:
        return HTTPException(status_code=404, detail=msg)
    if "illegal transition" in low:
        return HTTPException(status_code=409, detail=msg)
    return HTTPException(status_code=400, detail=msg)


def _mission_row(m) -> dict:
    """List projection of a Mission (adds the derived effective priority)."""
    row = m.to_dict()
    row["effective_priority"] = m.effective_priority
    row["max_concurrent_tasks"] = m.max_concurrent_tasks
    return row


@v1_router.get("/missions", tags=["missions"])
def list_missions(
    request: Request, status: str | None = None, label: str | None = None, limit: int = 100
) -> dict:
    svc = _missions(request)
    rows = svc.list_missions(status=status, label=label, limit=limit)
    return {"missions": [_mission_row(m) for m in rows]}


@v1_router.post("/missions", tags=["missions"])
def create_mission(body: CreateMissionRequest, request: Request) -> dict:
    svc = _missions(request)
    deadline = None
    if body.deadline:
        from datetime import datetime

        try:
            deadline = datetime.fromisoformat(body.deadline)
        except ValueError:
            raise HTTPException(status_code=400, detail="deadline must be ISO-8601")
    try:
        mission = svc.create_mission(
            body.title,
            body.objective,
            scheduling_policy=body.scheduling_policy,
            priority=body.priority,
            criticality=body.criticality,
            budget=body.budget,
            deadline=deadline,
            importance=body.importance,
            labels=body.labels,
            metadata=body.metadata,
            knowledge_domains=body.knowledge_domains,
            success_criteria=body.success_criteria,
        )
        if body.activate:
            mission = svc.activate(mission.id, "activated on create")
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return svc.get_mission(mission.id)


@v1_router.post("/missions/instantiate", tags=["missions"])
def instantiate_mission(body: InstantiateMissionRequest, request: Request) -> dict:
    """Create a Mission from a built-in template (mission + config v1 + workers)."""
    templates = _templates(request)
    try:
        result = templates.instantiate(
            body.template,
            title=body.title,
            objective=body.objective,
            config_overrides=body.config_overrides,
            labels=body.labels,
            metadata=body.metadata,
            scheduling_policy=body.scheduling_policy,
            priority=body.priority,
            criticality=body.criticality,
            budget=body.budget,
            activate=body.activate,
            autostart=body.autostart,
        )
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    view = _missions(request).get_mission(result["mission"].id)
    try:
        active = _configuration(request).get_active(result["mission"].id)
        if active is not None:
            view["config"] = active.to_dict()
    except Exception:  # noqa: BLE001 - config layer optional on aggregate view
        pass
    return view


@v1_router.get("/missions/{mission_id}", tags=["missions"])
def get_mission(mission_id: str, request: Request, journal_limit: int = 50) -> dict:
    try:
        view = _missions(request).get_mission(mission_id, journal_limit=journal_limit)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    try:
        active = _configuration(request).get_active(mission_id)
        if active is not None:
            view["config"] = active.to_dict()
    except Exception:  # noqa: BLE001 - config layer optional on aggregate view
        pass
    return view


@v1_router.get("/missions/{mission_id}/config", tags=["missions"])
def get_mission_config(mission_id: str, request: Request) -> dict:
    """Active versioned config for a mission (P6)."""
    _missions(request)  # 404 if mission missing via require below
    try:
        _missions(request).get_mission(mission_id, journal_limit=1)
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)
    cfg = _configuration(request).get_active(mission_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="mission has no active config")
    return {"config": cfg.to_dict()}


@v1_router.put("/missions/{mission_id}/config", tags=["missions"])
def update_mission_config(
    mission_id: str, body: UpdateMissionConfigRequest, request: Request
) -> dict:
    """Write the next config version (immutable history) and optionally activate it."""
    try:
        _missions(request).get_mission(mission_id, journal_limit=1)
        cfg = _configuration(request).update_config(
            mission_id,
            body.document,
            change_note=body.change_note or "operator update",
            activate=body.activate,
        )
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return {"config": cfg.to_dict()}


# --- assets (market_data feeds for paper trading) -----------------------
@v1_router.get("/assets", tags=["assets"])
def list_assets(request: Request, kind: str | None = None) -> dict:
    """List Asset Store entries (filter with ``?kind=market_data``)."""
    rows = _assets(request).list_assets(kind=kind)
    return {"assets": rows}


@v1_router.post("/assets", tags=["assets"])
def register_asset(body: RegisterAssetRequest, request: Request) -> dict:
    """Register/version an asset. For paper trading use ``kind=market_data``.

    No broker login: Atlas paper trading is simulation-only (P10). Pass JSON/CSV
    ``content`` or ``bars``, or ``generate_sample=true`` for a deterministic fixture.
    """
    import json as _json

    from atlas.trading.sample_feed import register_market_feed

    if body.kind != "market_data":
        # Generic path: content required.
        if not body.content:
            raise HTTPException(
                status_code=400,
                detail="content required for non-market_data assets (or use kind=market_data)",
            )
        try:
            result = _assets(request).register(
                body.kind,
                body.name,
                body.content.encode("utf-8"),
                content_type=body.content_type,
                metadata={"filename": body.filename or f"{body.name}.bin"},
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"asset": result.get("asset"), "version": result.get("version")}

    data: bytes | None = None
    filename = body.filename
    content_type = body.content_type
    if body.bars is not None:
        data = _json.dumps(body.bars).encode("utf-8")
        filename = filename or f"{body.name}.json"
        content_type = content_type or "application/json"
    elif body.content is not None:
        data = body.content.encode("utf-8")
        if not filename:
            filename = f"{body.name}.csv" if "," in body.content.split("\n", 1)[0] else f"{body.name}.json"
            content_type = content_type or (
                "text/csv" if filename.endswith(".csv") else "application/json"
            )

    try:
        info = register_market_feed(
            _assets(request),
            name=body.name,
            symbol=body.symbol or body.name,
            data=data,
            filename=filename,
            content_type=content_type,
            generate_sample=body.generate_sample or data is None,
            sample_bars_n=body.sample_bars,
            sample_start=body.sample_start,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return info


@v1_router.get("/missions/{mission_id}/journal", tags=["missions"])
def mission_journal(mission_id: str, request: Request, limit: int = 100) -> dict:
    try:
        entries = _missions(request).journal_entries(mission_id, limit=limit)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return {"journal": [e.to_dict() for e in entries]}


_MISSION_ACTIONS = {"activate", "pause", "resume", "complete", "archive"}


@v1_router.post("/missions/{mission_id}/{action}", tags=["missions"])
def mission_action(
    mission_id: str, action: str, body: MissionActionRequest, request: Request
) -> dict:
    if action not in _MISSION_ACTIONS:
        raise HTTPException(status_code=404, detail=f"unknown action: {action}")
    svc = _missions(request)
    try:
        getattr(svc, action)(mission_id, body.reason)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return svc.get_mission(mission_id)


@v1_router.get("/templates", tags=["missions"])
def list_templates(request: Request) -> dict:
    templates = _templates(request)
    return {
        "templates": [
            {
                "name": t.name,
                "template_version": t.template_version,
                "description": t.description,
                "worker_specs": t.worker_specs,
                "config_schema_type": t.config_schema_type,
                "knowledge_domains": t.knowledge_domains,
                "default_config": t.default_config,
                "success_criteria": t.success_criteria,
            }
            for t in templates.list_templates()
        ]
    }


# --- Intelligence Programs (MI.1) ----------------------------------------
@v1_router.get("/programs", tags=["programs"])
def list_programs(request: Request) -> dict:
    """List Market / Engineering / Personal Programs with member status."""
    return {"programs": _programs(request).list(), "version": "mi.1"}


@v1_router.get("/programs/{program_id}", tags=["programs"])
def get_program(program_id: str, request: Request) -> dict:
    try:
        return _programs(request).describe(program_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@v1_router.post("/programs/{program_id}/plan", tags=["programs"])
def plan_program(
    program_id: str,
    request: Request,
    body: PlanProgramRequest | None = None,
) -> dict:
    """OX.2 — preview Program start plan (no missions created). API start stays immediate."""
    payload = body or PlanProgramRequest()
    try:
        programs = _programs(request)
        preview = programs.preview_start(
            program_id,
            title_prefix=payload.title_prefix,
            preset=payload.preset,
            member_overrides=payload.member_overrides,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)

    plan_doc: dict = {}
    try:
        planning = _app(request).container.resolve("planning")
        plan_doc = planning.plan_program_start(
            preset=payload.preset or "india_equity_learner",
            program_id=program_id,
            capital=payload.capital,
            universe=payload.universe,
            mode=payload.mode,
            broker_profile=payload.broker_profile,
            objective=payload.objective,
            activate=False,
        )
    except Exception:  # noqa: BLE001
        plan_doc = {"kind": "program_start_plan", "steps": [], "version": "ox.2"}

    return {
        "plan": plan_doc,
        "preview": preview,
        "side_effecting": False,
        "start": f"POST /v1/programs/{program_id}/start",
    }


@v1_router.post("/programs/{program_id}/start", tags=["programs"])
def start_program(
    program_id: str,
    request: Request,
    body: StartProgramRequest | None = None,
    activate: bool = True,
) -> dict:
    """Start startable Program members (optional OX.1 preset: india_equity_learner).

    Always immediate (OX.2 API/scheduler mode) — no preview step.
    """
    payload = body or StartProgramRequest(activate=activate)
    try:
        return _programs(request).start(
            program_id,
            activate=payload.activate if body is not None else activate,
            title_prefix=payload.title_prefix,
            preset=payload.preset,
            member_overrides=payload.member_overrides,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)


@v1_router.get("/programs/{program_id}/context", tags=["programs"])
def program_context(
    program_id: str,
    request: Request,
    q: str = "",
    limit: int = 12,
) -> dict:
    """Mission Context for a Program (MCA.1)."""
    try:
        _programs(request).describe(program_id)  # 404 if unknown
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        ctx = _app(request).container.resolve("mission_context")
        return ctx.gather(q, program_id=program_id, limit=limit)
    except Exception:  # noqa: BLE001 — fall back to ProgramService wrapper
        return _programs(request).context(q, program_id=program_id, limit=limit)


@v1_router.post("/programs/{program_id}/share", tags=["programs"])
def program_share(
    program_id: str, body: ProgramShareRequest, request: Request
) -> dict:
    """Share resume / past work once — Personal + Engineering both consume it."""
    try:
        return _programs(request).share_materials(
            program_id,
            body.path,
            kind=body.kind,
            domain=body.domain,
            process_now=body.process_now,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@v1_router.post("/programs/{program_id}/chat", tags=["programs"])
def program_chat(
    program_id: str, body: ProgramChatRequest, request: Request
) -> dict:
    """Program-scoped chat — share host paths or get operator guidance."""
    try:
        return _programs(request).chat(
            program_id, body.message, session_id=body.session_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@v1_router.get("/context", tags=["programs"])
def mission_context(request: Request, q: str = "", limit: int = 12) -> dict:
    """Mission Context API — everything relevant to ``q`` (MCA.1)."""
    try:
        ctx = _app(request).container.resolve("mission_context")
        return ctx.gather(q, limit=limit)
    except Exception:  # noqa: BLE001
        return _programs(request).context(q, limit=limit)


@v1_router.get("/planning/plan", tags=["programs"])
def planning_plan_get(
    request: Request,
    goal: str = "",
    program_id: str | None = None,
    limit: int = 12,
) -> dict:
    """Planning OS — goal → gaps → compare → risk → decide (PA.1)."""
    try:
        planning = _app(request).container.resolve("planning")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"planning unavailable: {exc}") from exc
    return planning.plan(goal, program_id=program_id, limit=limit)


@v1_router.get("/planning/daily-investment-plan", tags=["programs"])
@v1_router.get("/market/daily-plan", tags=["programs"])
def daily_investment_plan(
    request: Request,
    program_id: str = "market_intelligence",
    capital: float = 10000.0,
    portfolio_key: str | None = None,
    max_candidates: int = 5,
    deploy_fraction: float = 0.40,
) -> dict:
    """IL.6 — Daily Investment Plan from M0 ranked watchlist (simulation sizing only)."""
    try:
        planning = _app(request).container.resolve("planning")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"planning unavailable: {exc}") from exc
    return planning.plan_daily_investment(
        program_id=program_id,
        capital=capital,
        portfolio_key=portfolio_key,
        max_candidates=max_candidates,
        deploy_fraction=deploy_fraction,
    )


@v1_router.get("/market/watchlist", tags=["programs"])
def market_watchlist(
    request: Request,
    program_id: str = "market_intelligence",
    limit: int = 20,
) -> dict:
    """Latest M0 ranked watchlist snapshot (operator dashboard).

    Memory → disk → active ``investment_universe`` worker checkpoint.
    """
    from atlas.investment import watchlists as wl

    snap = wl.latest(program_id)
    source = "memory_or_disk" if snap else None

    if not snap:
        # Recover from M0 worker checkpoints (system.checkpoints)
        try:
            cps = _app(request).container.resolve("checkpoints")
            workers = _workers(request)
            for w in workers.list_workers(status="running") or []:
                wtype = getattr(w, "type", None) or (w.get("type") if isinstance(w, dict) else None)
                if str(wtype) != "investment_universe":
                    continue
                wid = getattr(w, "id", None) or (w.get("id") if isinstance(w, dict) else None)
                mid = getattr(w, "mission_id", None) or (
                    w.get("mission_id") if isinstance(w, dict) else None
                )
                st = cps.load("worker", str(wid)) or {}
                if not isinstance(st, dict):
                    continue
                ranked = list(st.get("ranked") or [])
                if not ranked and st.get("watchlist_symbols"):
                    ranked = [
                        {"symbol": s, "rank": i + 1}
                        for i, s in enumerate(st["watchlist_symbols"])
                    ]
                if not ranked:
                    continue
                snap = wl.publish(
                    program_id=str(st.get("program_id") or program_id),
                    index=str(st.get("index") or "NIFTY50"),
                    watchlist=list(st.get("watchlist") or ranked),
                    ranked=ranked,
                    mission_id=str(mid) if mid else None,
                    mode="auto",
                    extra={
                        "phase": st.get("phase"),
                        "confidence": st.get("confidence"),
                        "recovered_from": "worker_checkpoint",
                        "daily_plan_summary": st.get("daily_plan_summary"),
                    },
                )
                source = "worker_checkpoint"
                break
        except Exception:  # noqa: BLE001
            snap = snap

    if not snap:
        return {
            "program_id": program_id,
            "watchlist": [],
            "ranked": [],
            "count": 0,
            "note": (
                "No watchlist yet — open Investment Universe and wait for a tick, "
                "or chat: start India learner now."
            ),
            "version": "il.2",
        }
    ranked = list(snap.get("ranked") or snap.get("watchlist") or [])
    lim = max(1, min(100, int(limit)))
    return {
        "program_id": snap.get("program_id") or program_id,
        "index": snap.get("index"),
        "mission_id": snap.get("mission_id"),
        "updated_at": snap.get("updated_at"),
        "extra": snap.get("extra") or {},
        "ranked": ranked[:lim],
        "watchlist": list(snap.get("watchlist") or [])[:lim],
        "count": len(ranked),
        "source": source or "store",
        "version": "il.2",
    }


@v1_router.get("/governance/daily", tags=["programs"])
def governance_daily(request: Request, limit: int = 200) -> dict:
    """Daily Learning Governance Report — Layer 2 (OI-MP3)."""
    try:
        gov = _app(request).container.resolve("governance")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"governance unavailable: {exc}") from exc
    return gov.daily(limit=limit)


@v1_router.get("/introspection/report", tags=["programs"])
def introspection_report(request: Request, limit: int = 200) -> dict:
    """System Introspection report — knowledge / gaps / readers / cost (OI-F3)."""
    try:
        intro = _app(request).container.resolve("introspection")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"introspection unavailable: {exc}"
        ) from exc
    return intro.report(limit=limit)


@v1_router.get("/scheduler/hierarchy", tags=["programs"])
def scheduler_hierarchy_all(request: Request, program_id: str | None = None) -> dict:
    """Program → Mission → Worker schedule hierarchy (SCHED.1)."""
    try:
        hier = _app(request).container.resolve("scheduler_hierarchy")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"scheduler_hierarchy unavailable: {exc}"
        ) from exc
    return hier.view(program_id)


@v1_router.post("/scheduler/resolve", tags=["programs"])
def scheduler_resolve(request: Request, body: dict | None = None) -> dict:
    """Resolve effective tick interval (worker > mission cadence > program default)."""
    try:
        hier = _app(request).container.resolve("scheduler_hierarchy")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"scheduler_hierarchy unavailable: {exc}"
        ) from exc
    payload = body or {}
    return hier.resolve_interval(
        program_id=payload.get("program_id"),
        template=payload.get("template"),
        worker_type=payload.get("worker_type"),
        cadence=payload.get("cadence"),
        worker_interval=payload.get("worker_interval"),
    )


@v1_router.post("/planning/plan", tags=["programs"])
def planning_plan_post(request: Request, body: dict | None = None) -> dict:
    """Planning OS (POST) — body: ``{goal, program_id?, limit?}``."""
    try:
        planning = _app(request).container.resolve("planning")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"planning unavailable: {exc}") from exc
    payload = body or {}
    return planning.plan(
        str(payload.get("goal") or ""),
        program_id=payload.get("program_id"),
        limit=int(payload.get("limit") or 12),
    )


@v1_router.get("/world-models", tags=["programs"])
def list_world_models(request: Request) -> dict:
    """List World Model packs (WM.1 — structure, not Knowledge claims)."""
    try:
        reg = _app(request).container.resolve("world_models")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"world_models unavailable: {exc}") from exc
    return reg.as_dict()


@v1_router.get("/world-models/{pack_id}", tags=["programs"])
def get_world_model(pack_id: str, request: Request, kind: str = "", q: str = "", limit: int = 50) -> dict:
    """Describe a World Model pack and optionally list matching facts."""
    try:
        reg = _app(request).container.resolve("world_models")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"world_models unavailable: {exc}") from exc
    pack = reg.get(pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"unknown world model pack: {pack_id}")
    desc = pack.describe() if hasattr(pack, "describe") else {"id": pack_id}
    return {
        "pack": desc,
        "facts": reg.facts(
            pack_id=pack_id,
            kind=kind or None,
            q=q or None,
            limit=limit,
        ),
        "version": getattr(reg, "VERSION", "wm.1"),
    }


@v1_router.get("/market/providers", tags=["programs"])
def list_market_providers(request: Request) -> dict:
    """List MarketReader adapters (MI.3 / OI-D1)."""
    try:
        reader = _app(request).container.resolve("market_reader")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"market_reader unavailable: {exc}") from exc
    return {
        "providers": reader.list_providers(),
        "version": getattr(reader, "VERSION", "mi.3"),
    }


@v1_router.get("/market/company-providers", tags=["programs"])
def list_company_providers(request: Request) -> dict:
    """List company/filing adapters (MI.5 — official preferred, no scrape)."""
    try:
        svc = _app(request).container.resolve("company_data")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"company_data unavailable: {exc}") from exc
    return {
        "providers": svc.list_providers(),
        "version": getattr(svc, "VERSION", "mi.5"),
    }


@v1_router.get("/market/broker-profiles", tags=["programs"])
def list_broker_profiles(request: Request) -> dict:
    """List Broker Profiles for sim fee/tax (MI.6 — Market Program config, P10)."""
    try:
        ledger = _app(request).container.resolve("portfolio_ledger")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"portfolio_ledger unavailable: {exc}") from exc
    return {
        "profiles": ledger.list_profiles(),
        "version": getattr(ledger, "VERSION", "mi.6"),
    }


@v1_router.get("/market/instrument-packs", tags=["programs"])
def list_instrument_packs() -> dict:
    """IL.11 — Simulation Engine instrument packs (ready vs stub capability gaps)."""
    from atlas.investment.packs import list_packs

    packs = list_packs()
    return {
        "packs": packs,
        "count": len(packs),
        "ready": [p["id"] for p in packs if p.get("ready")],
        "version": "il.11",
    }


@v1_router.get("/market/holidays", tags=["programs"])
def list_market_holidays(
    calendar: str = "india_equity",
    year: int | None = None,
    session: str | None = None,
) -> dict:
    """IL.5+ — holidays Atlas detects for session gates (seeded calendars)."""
    from atlas.trading.holidays import holidays_view

    return holidays_view(calendar_id=calendar, year=year, session_id=session)


@v1_router.get("/market/session-status", tags=["programs"])
def get_market_session_status(session: str = "nse_equity") -> dict:
    """Whether the named market_session is open right now (hours + Atlas holidays)."""
    from atlas.trading.sessions import session_status

    st = session_status(session)
    return {
        "session_id": st.session_id,
        "open": st.open,
        "reason": st.reason,
        "local_now": st.local_now,
        "holiday": st.holiday,
        "version": "il.5.holidays",
    }


@v1_router.post("/market/holidays", tags=["programs"])
def post_market_holiday(payload: dict) -> dict:
    """Operator overlay: add a closed day Atlas should detect for a calendar."""
    from atlas.trading.holidays import add_operator_holiday, holidays_view

    calendar = str(payload.get("calendar") or payload.get("calendar_id") or "india_equity")
    day = payload.get("day") or payload.get("date")
    name = str(payload.get("name") or "operator_holiday")
    if not day:
        raise HTTPException(status_code=400, detail="day (YYYY-MM-DD) required")
    hol = add_operator_holiday(calendar, day, name)
    return {
        "holiday": hol.as_dict(),
        "calendar": holidays_view(calendar_id=calendar, year=hol.day.year),
    }


@v1_router.get("/market/screener-signals", tags=["programs"])
def get_screener_signals(program_id: str = "market_intelligence") -> dict:
    """IL.8 — latest operator screener snapshot (no scrape)."""
    from atlas.investment.screener_signals import signals_view

    return signals_view(program_id)


@v1_router.post("/market/screener-snapshot", tags=["programs"])
def post_screener_snapshot(body: ScreenerSnapshotRequest) -> dict:
    """IL.8 — upsert hermetic / operator screener rows for M0 ranking."""
    from atlas.investment.screener_signals import publish_snapshot

    snap = publish_snapshot(
        body.symbols,
        program_id=body.program_id,
        as_of=body.as_of,
        note=body.note,
    )
    return {"snapshot": snap, "version": "il.8"}


@v1_router.post("/market/screener-signals/compute", tags=["programs"])
def compute_screener_signals(body: ScreenerComputeRequest) -> dict:
    """IL.8 — pure compute from bars + quality (hermetic, no I/O)."""
    from atlas.investment.screener_signals import compute_from_bars_quality

    rows = compute_from_bars_quality(
        bars_by_symbol=body.bars_by_symbol,
        quality_by_symbol=body.quality_by_symbol,
        symbols=body.symbols,
    )
    return {"symbols": rows, "count": len(rows), "version": "il.8"}


@v1_router.get("/market/filings", tags=["programs"])
def get_market_filings(
    symbol: str | None = None,
    program_id: str = "market_intelligence",
    use_hermetic: bool = True,
) -> dict:
    """IL.5+ — hermetic / operator filing refs (no live scrape)."""
    from atlas.investment.filings import filings_view

    return filings_view(
        symbol=symbol, program_id=program_id, use_hermetic=use_hermetic
    )


@v1_router.post("/market/filings-snapshot", tags=["programs"])
def post_filings_snapshot(body: FilingsSnapshotRequest) -> dict:
    """IL.5+ — upsert ToS-compliant operator filing metadata for M2."""
    from atlas.investment.filings import VERSION, publish_snapshot

    snap = publish_snapshot(
        body.symbols,
        program_id=body.program_id,
        as_of=body.as_of,
        note=body.note,
    )
    return {"snapshot": snap, "version": VERSION}


@v1_router.get("/market/portfolios", tags=["programs"])
def list_virtual_portfolios(
    request: Request,
    program_id: str | None = None,
) -> dict:
    """IL.10 — list virtual portfolios (persona + mission binding)."""
    from atlas.investment import portfolios as vp

    rows = vp.list_portfolios(program_id=program_id)
    return {"portfolios": rows, "count": len(rows), "version": "il.10"}


@v1_router.post("/market/portfolios", tags=["programs"])
def create_virtual_portfolio(
    request: Request,
    body: CreateVirtualPortfolioRequest,
) -> dict:
    """IL.10 — create a virtual portfolio book (one Decision Simulation per book)."""
    from atlas.investment import portfolios as vp

    templates = None
    if body.instantiate:
        try:
            templates = _app(request).container.resolve("templates")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"templates unavailable: {exc}"
            ) from exc
    try:
        row = vp.create_book(
            label=body.label,
            persona=body.persona,
            capital=body.capital,
            program_id=body.program_id,
            portfolio_key=body.portfolio_key,
            universe=body.universe,
            broker_profile=body.broker_profile,
            asset_class=body.asset_class,
            instantiate=body.instantiate,
            templates=templates,
            activate=body.activate,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"portfolio": row, "version": "il.10"}


@v1_router.get("/market/portfolios/{portfolio_ref}", tags=["programs"])
def get_virtual_portfolio(portfolio_ref: str, request: Request) -> dict:
    """IL.10 — get by portfolio_key or id; attach sim snapshot when mission bound."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown portfolio: {portfolio_ref}")
    snap = None
    mid = row.get("mission_id")
    if mid:
        try:
            portfolio_svc = _app(request).container.resolve("portfolio")
            # Prefer ledger name = portfolio_key under that mission
            ensured = portfolio_svc.ensure_portfolio(
                mission_id=mid,
                name=row.get("portfolio_key") or "default",
                starting_cash=float((row.get("persona") or {}).get("capital") or 0),
            )
            snap = portfolio_svc.snapshot(ensured["id"])
        except Exception:  # noqa: BLE001
            snap = None
    return {"portfolio": row, "snapshot": snap, "version": "il.10"}


@v1_router.get("/market/portfolios/{portfolio_ref}/ledger", tags=["programs"])
def portfolio_ledger_statement(portfolio_ref: str, request: Request) -> dict:
    """IL.7 — fee/TDS rollup statement for a virtual portfolio book."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown portfolio: {portfolio_ref}")
    mid = row.get("mission_id") or row.get("ledger_mission_id")
    if not mid:
        raise HTTPException(
            status_code=404,
            detail="portfolio has no bound Decision Simulation / ledger mission yet",
        )
    try:
        ledger = _app(request).container.resolve("portfolio_ledger")
        portfolio_svc = _app(request).container.resolve("portfolio")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ensured = portfolio_svc.ensure_portfolio(
        mission_id=mid,
        name=row.get("portfolio_key") or "default",
        starting_cash=float((row.get("persona") or {}).get("capital") or 0),
    )
    stmt = ledger.statement(
        ensured["id"],
        broker_profile=str(row.get("broker_profile") or "") or None,
    )
    return {"portfolio": row, "statement": stmt, "version": "il.7"}


@v1_router.post("/market/portfolios/{portfolio_ref}/withdraw", tags=["programs"])
def withdraw_from_portfolio(
    portfolio_ref: str,
    request: Request,
    body: WithdrawPortfolioRequest,
) -> dict:
    """IL.7 — simulate a cash withdrawal (optional TDS) from a virtual book."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown portfolio: {portfolio_ref}")
    mid = body.mission_id or row.get("mission_id") or row.get("ledger_mission_id")
    if not mid:
        raise HTTPException(
            status_code=400,
            detail="portfolio needs a bound mission before withdrawals",
        )
    try:
        ledger = _app(request).container.resolve("portfolio_ledger")
        portfolio_svc = _app(request).container.resolve("portfolio")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ensured = portfolio_svc.ensure_portfolio(
        mission_id=mid,
        name=row.get("portfolio_key") or "default",
        starting_cash=float((row.get("persona") or {}).get("capital") or 0),
    )
    profile = body.broker_profile or row.get("broker_profile") or "zerodha"
    try:
        out = ledger.withdraw(
            ensured["id"],
            amount=body.amount,
            broker_profile=profile,
            tds_pct=body.tds_pct,
            note=body.note,
            mission_id=mid,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"portfolio": row, "withdrawal": out, "version": "il.7"}


@v1_router.get("/goals", tags=["programs"])
def list_goals(
    request: Request,
    status: str | None = "active",
    program_id: str | None = None,
    portfolio_key: str | None = None,
    q: str = "",
    limit: int = 50,
) -> dict:
    """OX.3 — list or search durable Goals (objectives first)."""
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    if (q or "").strip():
        return goals.search(q, limit=limit)
    return goals.list(
        status=status,
        program_id=program_id,
        portfolio_key=portfolio_key,
        limit=limit,
    )


@v1_router.post("/goals", tags=["programs"])
def create_goal(request: Request, body: CreateGoalRequest) -> dict:
    """OX.3 — create a Goal from an objective (Program/Portfolio optional)."""
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    try:
        goal = goals.create(
            body.title,
            objective=body.objective,
            success_criteria=body.success_criteria,
            program_id=body.program_id,
            portfolio_key=body.portfolio_key,
            portfolio_id=body.portfolio_id,
            status=body.status,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"goal": goal, "version": getattr(goals, "VERSION", "ox.3")}


@v1_router.get("/goals/{goal_id}", tags=["programs"])
def get_goal(goal_id: str, request: Request) -> dict:
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    goal = goals.get(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"unknown goal: {goal_id}")
    return {"goal": goal, "version": getattr(goals, "VERSION", "ox.4")}


@v1_router.get("/goals/{goal_id}/progress", tags=["programs"])
def goal_progress(goal_id: str, request: Request, persist: bool = True) -> dict:
    """OX.4 — deterministic progress narrative (paragraph + bullets)."""
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    report = goals.progress(goal_id, persist=persist)
    if not report.get("ok"):
        raise HTTPException(status_code=404, detail=report.get("error") or "goal_not_found")
    return report


@v1_router.get("/learner/status", tags=["programs"])
def learner_status(request: Request, q: str = "india learner") -> dict:
    """OX.4 / IL.9 — India learner progress narrative + happy-path checklist."""
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    return goals.learner_status(query=q or "india learner")


@v1_router.get("/learner/happy-path", tags=["programs"])
def learner_happy_path(capital: float = 10000.0) -> dict:
    """IL.9 — static India ₹10k learner guide (no JSON instruments required)."""
    from atlas.investment.happy_path import happy_path_guide

    return happy_path_guide(capital=capital)


@v1_router.patch("/goals/{goal_id}", tags=["programs"])
def update_goal(goal_id: str, request: Request, body: UpdateGoalRequest) -> dict:
    try:
        goals = _app(request).container.resolve("goals")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"goals unavailable: {exc}") from exc
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        goal = goals.update(goal_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if goal is None:
        raise HTTPException(status_code=404, detail=f"unknown goal: {goal_id}")
    return {"goal": goal, "version": getattr(goals, "VERSION", "ox.3")}


@v1_router.get("/workers", tags=["workers"])
def list_workers(
    request: Request, mission_id: str | None = None, status: str | None = None
) -> dict:
    workers = _workers(request)
    rows = workers.list_workers(mission_id=mission_id, status=status)
    return {"workers": [w.to_dict() for w in rows]}


@v1_router.get("/workers/{worker_id}", tags=["workers"])
def get_worker(worker_id: str, request: Request) -> dict:
    worker = _workers(request).get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return worker.to_dict()


@v1_router.post("/workers/{worker_id}/input", tags=["workers"])
def worker_input(worker_id: str, body: WorkerInputRequest, request: Request) -> dict:
    """Queue a live operator input for a worker (drained at its next tick, Q4).

    Declared before the generic ``/{action}`` route so ``input`` isn't captured as an action.
    """
    workers = _workers(request)
    try:
        workers.enqueue_input(worker_id, body.payload)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return {"queued": True, "worker_id": worker_id}


_WORKER_ACTIONS = {"pause", "resume", "stop"}


@v1_router.post("/workers/{worker_id}/{action}", tags=["workers"])
def worker_action(
    worker_id: str, action: str, body: WorkerActionRequest, request: Request
) -> dict:
    if action not in _WORKER_ACTIONS:
        raise HTTPException(status_code=404, detail=f"unknown action: {action}")
    workers = _workers(request)
    method = "stop_worker" if action == "stop" else action
    try:
        worker = getattr(workers, method)(worker_id, body.reason)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)
    return worker.to_dict()


@v1_router.post("/knowledge/search", response_model=SearchResponse, tags=["knowledge"])
def search(body: SearchRequest, request: Request) -> SearchResponse:
    knowledge = _app(request).container.resolve("knowledge")
    ranked = knowledge.retrieve(
        body.query,
        k=body.limit,
        domains=body.domains,
        tiers=body.tiers,
        role=body.role,
        mode=body.mode,
        policy_scope=body.policy_scope,
        mission_id=body.mission_id,
    )
    return SearchResponse(
        results=[
            SearchResultOut(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                ordinal=h.ordinal,
                content=h.content,
                similarity=h.similarity,
                dense_score=h.dense_score,
                lexical_score=h.lexical_score,
                rrf_score=h.rrf_score,
                score=h.score,
            )
            for h in ranked.hits
        ],
        role=ranked.role,
        mode=ranked.mode,
        diagnostics_id=ranked.diagnostics_id,
        context=ranked.context,
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


@v1_router.post("/ingest", response_model=BridgeIngestResponse, tags=["knowledge"])
def ingest_bridge(body: BridgeIngestRequest, request: Request) -> BridgeIngestResponse:
    """Unified Asset-first ingest (OI-C5): path or inline content → bridge → optional drain."""
    try:
        bridge = _app(request).container.resolve("ingestion_bridge")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"ingestion_bridge unavailable: {exc}"
        ) from exc

    if body.path:
        result = bridge.ingest_file(
            body.path,
            kind=body.kind,
            domain=body.domain,
            title=body.title,
            embed=body.embed,
            extract_findings=body.extract_findings,
            source="document" if body.kind == "document" else body.kind,
        )
    elif body.content:
        result = bridge.ingest_bytes(
            body.content.encode("utf-8"),
            filename=body.filename or (body.title or "inline.txt"),
            kind=body.kind,
            domain=body.domain,
            title=body.title,
            embed=body.embed,
            extract_findings=body.extract_findings,
            source="document" if body.kind == "document" else body.kind,
        )
    else:
        raise HTTPException(status_code=400, detail="path or content required")

    findings = 0
    if body.drain_candidates and body.extract_findings:
        try:
            candidates = _app(request).container.resolve("candidates")
            drained = candidates.consume_pending(limit=200)
            findings = len(drained)
        except Exception:  # noqa: BLE001
            findings = 0

    return BridgeIngestResponse(
        asset_id=result.asset_id,
        asset_version=result.asset_version,
        document_id=result.document_id,
        chunks=int(result.chunks or 0),
        candidates=int(result.candidates or 0),
        findings=findings,
        deduped=bool(result.deduped),
        outcome=str(result.outcome or "ok"),
        reason=result.reason,
        asset_reused=bool(result.asset_reused),
    )


@v1_router.post("/candidates/drain", tags=["knowledge"])
def candidates_drain(request: Request, body: dict | None = None) -> dict:
    """Manually drain pending knowledge candidates through the Consolidator (OI-C5)."""
    try:
        candidates = _app(request).container.resolve("candidates")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"candidates unavailable: {exc}") from exc
    payload = body or {}
    limit = int(payload.get("limit") or 200)
    drained = candidates.consume_pending(limit=limit)
    return {"drained": len(drained), "items": drained[:20]}


@v1_router.post("/candidates/prune", tags=["knowledge"])
def candidates_prune(request: Request, body: dict | None = None) -> dict:
    """Prune consumed/discarded candidates older than N days (OI-C5)."""
    try:
        candidates = _app(request).container.resolve("candidates")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"candidates unavailable: {exc}") from exc
    payload = body or {}
    return candidates.prune_task(payload)


@v1_router.get("/knowledge/orphans", tags=["knowledge"])
def knowledge_orphans(request: Request, limit: int = 50) -> dict:
    """Documents still missing an Asset link (OI-C4 backlog)."""
    knowledge = _app(request).container.resolve("knowledge")
    docs = knowledge.list_documents_without_asset(limit=limit)
    return {
        "count": knowledge.count_documents_without_asset(),
        "documents": [
            {
                "id": d.id,
                "source": d.source,
                "title": d.title,
                "uri": d.uri,
                "domain": d.domain,
                "status": d.status,
                "checksum": d.checksum,
            }
            for d in docs
        ],
        "version": "c4.1",
    }


@v1_router.post("/knowledge/backfill-assets", tags=["knowledge"])
def knowledge_backfill_assets(request: Request, body: dict | None = None) -> dict:
    """Lazy backfill: register Assets for orphan documents (OI-C4)."""
    try:
        bridge = _app(request).container.resolve("ingestion_bridge")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"ingestion_bridge unavailable: {exc}"
        ) from exc
    payload = body or {}
    limit = int(payload.get("limit") or 25)
    return bridge.backfill_orphan_documents(limit=limit)


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


@v1_router.get("/memory/hierarchy", tags=["memory"])
def memory_hierarchy(request: Request) -> dict:
    """Memory OS layers — working → session → long_term → Knowledge / Experience (MEM.1)."""
    try:
        mos = _app(request).container.resolve("memory_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"memory_os unavailable: {exc}") from exc
    return mos.hierarchy()


@v1_router.post("/memory/promote", tags=["memory"])
def memory_promote(request: Request, body: dict | None = None) -> dict:
    """Promote a memory item up the hierarchy (working→session→long_term)."""
    try:
        mos = _app(request).container.resolve("memory_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"memory_os unavailable: {exc}") from exc
    payload = body or {}
    memory_id = str(payload.get("memory_id") or payload.get("id") or "")
    to_layer = str(payload.get("to_layer") or payload.get("layer") or "long_term")
    if not memory_id:
        raise HTTPException(status_code=400, detail="memory_id required")
    return mos.promote(
        memory_id,
        to_layer=to_layer,
        forget_source=bool(payload.get("forget_source")),
        importance=payload.get("importance"),
    )


@v1_router.post("/memory/os/remember", tags=["memory"])
def memory_os_remember(request: Request, body: dict | None = None) -> dict:
    """Remember at an explicit hierarchy layer (working|session|long_term)."""
    try:
        mos = _app(request).container.resolve("memory_os")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"memory_os unavailable: {exc}") from exc
    payload = body or {}
    content = str(payload.get("content") or "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="content required")
    return mos.remember(
        content,
        layer=str(payload.get("layer") or "long_term"),
        scope=str(payload.get("scope") or "global"),
        importance=float(payload.get("importance") or 0.0),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
        session_id=payload.get("session_id"),
        ttl_seconds=payload.get("ttl_seconds"),
    )


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


@v1_router.get("/capabilities/gaps", tags=["plugins"])
def capabilities_gaps(
    request: Request,
    include_missions: bool = True,
    include_decisions: bool = True,
    limit: int = 100,
) -> dict:
    """P15 capability-gap self-report (OI-F5): catalog + mission needs + decision backlog."""
    registry = _app(request).capabilities
    report = registry.self_report_gaps(include_missions=include_missions)
    decision_gaps: list[dict] = []
    if include_decisions:
        try:
            decision = _app(request).container.resolve("decision")
            decision_gaps = list(decision.list_gaps(limit=limit) or [])
        except Exception:  # noqa: BLE001 — decisions optional for this surface
            decision_gaps = []
    report["decision_gaps"] = decision_gaps
    report["summary"] = {
        **dict(report.get("summary") or {}),
        "decision_gaps": len(decision_gaps),
    }
    report["ok"] = bool(report.get("ok")) and not decision_gaps
    return report


@v1_router.get("/capabilities/inspect", tags=["plugins"])
def capabilities_inspect_all(request: Request) -> dict:
    """Live self-inspection of every registered capability (CAP.1 / §5.10)."""
    return {
        "capabilities": _app(request).capabilities.inspect_all(),
        "version": "cap.1",
    }


@v1_router.get("/capabilities/inspect/{name}", tags=["plugins"])
def capabilities_inspect_one(name: str, request: Request) -> dict:
    """Inspect one capability (aliases resolved)."""
    from atlas.exceptions import CapabilityMissingError

    registry = _app(request).capabilities
    try:
        canon = registry.resolve_name(name)
        return registry.inspect(canon).as_dict()
    except CapabilityMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@v1_router.post("/capabilities/needs", tags=["plugins"])
def capabilities_check_needs(request: Request, body: dict | None = None) -> dict:
    """Check whether named mission needs are satisfied (CAP.1 — declare, don't import)."""
    payload = body or {}
    needs = payload.get("needs")
    if not needs:
        mission = str(payload.get("mission") or payload.get("template") or "")
        if mission:
            from atlas.capabilities.needs import needs_for_mission

            needs = list(needs_for_mission(mission))
        else:
            raise HTTPException(
                status_code=400, detail="needs[] or mission/template required"
            )
    if isinstance(needs, str):
        needs = [needs]
    return _app(request).capabilities.check_needs(
        needs, require_healthy=bool(payload.get("require_healthy"))
    )


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
