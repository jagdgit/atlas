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
    InvokeToolRequest,
    InvokeToolResponse,
    InstantiateMissionRequest,
    CreateMissionRequest,
    MissionActionRequest,
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


def _mission_error(exc: Exception) -> HTTPException:
    """Map a MissionError/WorkerError/TemplateError to a sensible HTTP status."""
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
    return _missions(request).get_mission(result["mission"].id)


@v1_router.get("/missions/{mission_id}", tags=["missions"])
def get_mission(mission_id: str, request: Request, journal_limit: int = 50) -> dict:
    try:
        return _missions(request).get_mission(mission_id, journal_limit=journal_limit)
    except Exception as exc:  # noqa: BLE001 - domain error → HTTP
        raise _mission_error(exc)


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
            }
            for t in templates.list_templates()
        ]
    }


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
