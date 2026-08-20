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
    DepositPortfolioRequest,
    ScreenerSnapshotRequest,
    ScreenerComputeRequest,
    FilingsSnapshotRequest,
    InvestmentResearchStartRequest,
    ResearchBusinessIdentityRequest,
    ResearchOperatorSnapshotRequest,
    ResearchFilingRefsRequest,
    ResearchCriticalFlagRequest,
    ResearchManagementPackRequest,
    CreateGoalRequest,
    UpdateGoalRequest,
    BeliefConsultRequest,
    BeliefReviseRequest,
    BeliefPromoteRequest,
    BeliefCandidateRequest,
    LearningLoopRequest,
    StartProgramRequest,
    ApprovalActionRequest,
    CreateMissionRequest,
    MissionActionRequest,
    SpawnChildMissionRequest,
    SetResearchConfidenceRequest,
    PersonalLearnCvRequest,
    LinkedInCoachRequest,
    LinkedInExportIngestRequest,
    BestJobsRequest,
    CareerImportFeedRequest,
    CareerWatchlistUpsertRequest,
    CareerDiscoverRequest,
    CareerGatedApplyRequest,
    ArchiveEstimateRequest,
    ArchiveIngestRequest,
    RegisterAssetRequest,
    UpdateMissionConfigRequest,
    WorkerActionRequest,
    WorkerInputRequest,
    OpsCleanupRequest,
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


@v1_router.get("/ops/summary", tags=["ops"])
def ops_summary(request: Request) -> dict:
    """ARMF Phase E — lightweight Ops first paint (program health + archive + startup)."""
    dash = _app(request).container.resolve("ops_dashboard")
    if hasattr(dash, "summary"):
        return dash.summary()
    # Backward compatible if an older dashboard is loaded
    snap = dash.snapshot()
    return {
        "version": "armf.e1",
        "atlas": snap.get("atlas"),
        "program_health": snap.get("program_health"),
        "capacity_signal": snap.get("capacity_signal"),
        "archive_lane": snap.get("archive_lane"),
        "startup": snap.get("startup"),
        "generated_at": snap.get("generated_at"),
    }


@v1_router.post("/ops/cleanup", tags=["ops"])
def ops_cleanup(body: OpsCleanupRequest, request: Request) -> dict:
    """ARMF Phase B — dry-run or apply zombie / long no-progress cleanup.

    Default targets ``hello_watcher`` and unprotected long no-progress workers.
    Market / Engineering / Personal / Archive require ``include_protected=true``.
    Apply archives missions (non-destructive). Always prefer dry-run first.
    """
    from atlas.ops.cleanup import (
        DEFAULT_MIN_STARVATION_AGE_SECONDS,
        OpsCleanupService,
    )

    clock = None
    try:
        clock = _app(request).container.resolve("clock")
    except Exception:  # noqa: BLE001
        clock = None
    svc = OpsCleanupService(
        workers=_workers(request),
        missions=_missions(request),
        clock=clock,
    )
    min_age = (
        DEFAULT_MIN_STARVATION_AGE_SECONDS
        if body.min_starvation_age_seconds is None
        else float(body.min_starvation_age_seconds)
    )
    return svc.run(
        dry_run=bool(body.dry_run),
        include_protected=bool(body.include_protected),
        include_duplicates=bool(getattr(body, "include_duplicates", False)),
        duplicate_types=getattr(body, "duplicate_types", None),
        duplicate_keep=str(getattr(body, "duplicate_keep", None) or "oldest"),
        zombie_types=body.zombie_types,
        min_starvation_age_seconds=min_age,
        worker_ids=body.worker_ids,
        mission_ids=body.mission_ids,
        reason=body.reason or "",
    )


@v1_router.get("/resources/guard", tags=["resources"])
def resources_guard(request: Request) -> dict:
    """Host-respect posture — tick caps, RAM reserve, deferred/queued work."""
    try:
        return _app(request).container.resolve("host_guard").status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"host guard unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/watchdog", tags=["resources"])
def resources_watchdog(request: Request) -> dict:
    """IR-RO11 — Runtime memory watchdog (Layer 2 RSS / budget posture)."""
    try:
        return _app(request).container.resolve("memory_watchdog").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"memory watchdog unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/queue", tags=["resources"])
def resources_queue(request: Request, limit: int = 200) -> dict:
    """IR-RO2 — Mission Queue snapshot (READY / WAITING_* / RUNNING + owners)."""
    try:
        queue = _app(request).container.resolve("mission_queue")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"mission queue unavailable: {exc}"
        ) from exc
    return queue.snapshot(limit=max(1, min(int(limit or 200), 500)))


@v1_router.get("/resources/scheduler", tags=["resources"])
def resources_scheduler(request: Request) -> dict:
    """IR-RO5 — Resource Scheduler snapshot (Candidate Selector + REALTIME reserve)."""
    try:
        return _app(request).container.resolve("resource_scheduler").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"resource scheduler unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/reservations", tags=["resources"])
def resources_reservations(request: Request) -> dict:
    """IR-RO7 — active resource leases / Holding Reservation."""
    try:
        return _app(request).container.resolve("reservation_manager").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"reservations unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/storage", tags=["resources"])
def resources_storage(request: Request) -> dict:
    """IR-RO6 — storage pressure watermarks."""
    try:
        return _app(request).container.resolve("storage_pressure").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"storage pressure unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/budgets", tags=["resources"])
def resources_budgets(request: Request) -> dict:
    """IR-RO4 — dynamic effective tick slots within hard ceilings + hysteresis."""
    try:
        return _app(request).container.resolve("budget_controller").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"budget controller unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/machine-profile", tags=["resources"])
def resources_machine_profile(request: Request) -> dict:
    """IR-RO8 — host → conservative/balanced/maximum suggestion + preferred ticks."""
    from atlas.core.resources.machine_profile import detect_machine_profile, profile_catalog

    try:
        hard = _app(request).container.resolve("host_guard").status().get("max_concurrent_ticks")
    except Exception:  # noqa: BLE001
        hard = None
    suggestion = detect_machine_profile(hard_tick_ceiling=hard)
    configured = None
    try:
        from atlas.config import get_config

        configured = get_config().resources.profile
    except Exception:  # noqa: BLE001
        configured = None
    return {
        **suggestion.as_dict(),
        "configured_profile": configured,
        "catalog": profile_catalog(),
    }


@v1_router.get("/resources/work-admission", tags=["resources"])
def resources_work_admission(request: Request) -> dict:
    """IR-RO10 — should-run-now policy (BATCH quiet window when enforced)."""
    try:
        return _app(request).container.resolve("work_admission").snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"work admission unavailable: {exc}"
        ) from exc


@v1_router.get("/resources/power", tags=["resources"])
def resources_power(request: Request) -> dict:
    """IR-RO9 — power/UPS/battery posture (honest not-monitored when absent)."""
    from atlas.core.resources.power import probe_power, read_thermal_zones

    power = probe_power()
    zones = [z.as_dict() for z in read_thermal_zones()]
    hottest = max((z["celsius"] for z in zones), default=None)
    return {
        **power.as_dict(),
        "thermal": {
            "monitored": bool(zones),
            "hottest_c": hottest,
            "zones": zones,
        },
    }


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
        prediction=payload.get("prediction")
        if isinstance(payload.get("prediction"), dict)
        else None,
        outcome_structured=payload.get("outcome_structured")
        if isinstance(payload.get("outcome_structured"), dict)
        else None,
        affected_beliefs=list(payload.get("affected_beliefs") or []) or None,
        no_belief_link_reason=payload.get("no_belief_link_reason"),
        require_belief_link=bool(payload.get("require_belief_link", False)),
    )


@v1_router.post("/experience/learning-loop", tags=["experience"])
def experience_learning_loop(request: Request, body: LearningLoopRequest) -> dict:
    """OI-SELF-EXP — write experience with prediction/delta and ingest Belief Core."""
    try:
        eos = _app(request).container.resolve("experience_os")
        rs = _app(request).container.resolve("reasoning")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"learning-loop unavailable: {exc}") from exc
    kwargs = {
        "title": body.title,
        "observation": body.observation,
        "decision": body.decision,
        "outcome": body.outcome,
        "reflection": body.reflection,
        "lesson": body.lesson,
        "reasoning": body.reasoning,
        "domain": body.domain,
        "tags": list(body.tags or ["learning_loop", "self0_exp"]),
        "prediction": body.prediction or {},
        "outcome_structured": body.outcome_structured or {},
        "affected_beliefs": list(body.affected_beliefs or []),
        "no_belief_link_reason": body.no_belief_link_reason,
        "require_belief_link": True,
    }
    out = rs.close_experience_loop(
        eos, kwargs, ingest_beliefs=body.ingest_beliefs, actor="api"
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@v1_router.post("/personal/linkedin/ingest-export", tags=["personal"])
def personal_linkedin_ingest_export(
    body: LinkedInExportIngestRequest, request: Request
) -> dict:
    """Unpack a LinkedIn data-export (.zip / folder) for coaching only (CI.0/CI.1)."""
    container = _app(request).container
    personal = container.resolve("personal")
    assets = None
    missions = None
    configuration = None
    templates = None
    try:
        assets = container.resolve("assets")
    except Exception:  # noqa: BLE001
        pass
    try:
        missions = container.resolve("missions")
    except Exception:  # noqa: BLE001
        pass
    try:
        configuration = container.resolve("configuration")
    except Exception:  # noqa: BLE001
        pass
    try:
        templates = container.resolve("templates")
    except Exception:  # noqa: BLE001
        pass
    try:
        return personal.ingest_linkedin_export(
            body.path,
            include_inferred=body.include_inferred,
            linkedin_url=body.linkedin_url,
            assets=assets,
            register_snapshot=body.register_snapshot,
            missions=missions,
            configuration=configuration,
            templates=templates,
            wire_observer=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@v1_router.get("/personal/career/watchlist", tags=["personal"])
def personal_career_watchlist_get(
    request: Request,
    status: str | None = None,
    kind: str | None = None,
) -> dict:
    """CI.1.4 — list Career Memory watchlist items."""
    from atlas.career import watchlist as wl

    return wl.list_items(status=status, kind=kind)


@v1_router.post("/personal/career/watchlist", tags=["personal"])
def personal_career_watchlist_upsert(
    body: CareerWatchlistUpsertRequest, request: Request
) -> dict:
    """CI.1.4 — upsert operator_status on a company/job/skill/role."""
    from atlas.career import watchlist as wl

    try:
        return wl.upsert(
            label=body.label,
            kind=body.kind,
            operator_status=body.operator_status,
            notes=body.notes,
            external_id=body.external_id,
            url=body.url,
            item_id=body.item_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@v1_router.get("/personal/career/brief", tags=["personal"])
def personal_career_brief(
    request: Request,
    include_jobs: bool = True,
    job_limit: int = 5,
) -> dict:
    """CI.1.5 — Career morning brief (watchlist + optional Advisor ranks)."""
    from atlas.career.brief import build_morning_brief

    container = _app(request).container
    personal = container.resolve("personal")
    assets = None
    postings_reader = None
    decision_engine = None
    try:
        assets = container.resolve("assets")
    except Exception:  # noqa: BLE001
        pass
    try:
        decision_engine = container.resolve("decision")
    except Exception:  # noqa: BLE001
        pass
    return build_morning_brief(
        personal=personal,
        assets=assets,
        postings_reader=postings_reader,
        decision_engine=decision_engine,
        include_jobs=include_jobs,
        job_limit=max(1, min(20, job_limit)),
    )


@v1_router.get("/personal/career/market", tags=["personal"])
def personal_career_market(request: Request, feed_path: str | None = None) -> dict:
    """CI.2.3 — skill demand aggregates from sample/feed postings."""
    from atlas.career.ckg import skill_demand
    from atlas.career.feeds import load_postings_json, sample_fixture_path

    path = (feed_path or "").strip() or str(sample_fixture_path())
    try:
        posts = load_postings_json(__import__("pathlib").Path(path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    demand = skill_demand(posts)
    return {"ok": True, "market": demand, "path": path, "can_apply": False}


@v1_router.get("/personal/career/timeline", tags=["personal"])
def personal_career_timeline(request: Request) -> dict:
    """CI.2.5 timeline item — Career Timeline from Personal facts."""
    from atlas.career.ckg import career_timeline

    personal = _app(request).container.resolve("personal")
    facts = []
    try:
        facts = personal.list_facts(limit=200) or []
    except Exception:  # noqa: BLE001
        try:
            facts = personal.timeline(limit=200) or []
        except Exception:  # noqa: BLE001
            facts = []
    return {"ok": True, "timeline": career_timeline(personal_facts=facts), "can_apply": False}


@v1_router.get("/personal/career/gaps", tags=["personal"])
def personal_career_gaps(request: Request, feed_path: str | None = None) -> dict:
    """CI.2.6 / CI.4.4 — skill gaps + proposed learning plans."""
    from atlas.career.feeds import load_postings_json, sample_fixture_path
    from atlas.career.research import learning_plans_from_postings
    from atlas.personal.skill_hygiene import skill_names_from_facts

    personal = _app(request).container.resolve("personal")
    try:
        facts = personal.skills(include_inferred=True) or []
    except Exception:  # noqa: BLE001
        facts = []
    skills = skill_names_from_facts(facts, include_inferred=True)
    path = (feed_path or "").strip() or str(sample_fixture_path())
    try:
        posts = load_postings_json(__import__("pathlib").Path(path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out = learning_plans_from_postings(posts, skills)
    return {"ok": True, **out, "can_apply": False, "can_write_linkedin": False}


@v1_router.post("/personal/career/discover", tags=["personal"])
def personal_career_discover(body: CareerDiscoverRequest, request: Request) -> dict:
    """CI.3 — JobBoardAdapter.discover (sensors only)."""
    from atlas.career.boards import discover_all

    return discover_all(body.model_dump())


@v1_router.post("/personal/career/gated-apply", tags=["personal"])
def personal_career_gated_apply(body: CareerGatedApplyRequest, request: Request) -> dict:
    """CI.5 — gated apply intent; LinkedIn always CapabilityGap."""
    from atlas.career.research import gated_apply
    from atlas.decision.rules import CapabilityGap

    try:
        return gated_apply(
            body.posting,
            enabled=body.enabled,
            approved=body.approved,
            channel=body.channel,
        )
    except CapabilityGap as gap:
        return {
            "ok": False,
            "capability_gap": gap.capability,
            "detail": gap.detail,
            "can_apply": False,
        }


@v1_router.post("/personal/career/import-feed", tags=["personal"])
def personal_career_import_feed(
    body: CareerImportFeedRequest, request: Request
) -> dict:
    """Register jobs JSON as ``job_postings`` and wire Career Advisor sources (CI.0.2)."""
    from atlas.career.feeds import import_job_feed, sample_fixture_path

    container = _app(request).container
    try:
        assets = container.resolve("assets")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"assets unavailable: {exc}") from exc
    path = (body.path or "").strip() or str(sample_fixture_path())
    configuration = None
    missions = None
    try:
        configuration = container.resolve("configuration")
    except Exception:  # noqa: BLE001
        pass
    try:
        missions = container.resolve("missions")
    except Exception:  # noqa: BLE001
        pass
    try:
        return import_job_feed(
            assets=assets,
            path=path,
            asset_name=body.asset_name,
            configuration=configuration,
            missions=missions,
            wire_career_advisor=body.wire_career_advisor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    # Owner period/note → Personal timeline (Confirm/Reject); Engineering already learned the code.
    if out.get("outcome") == "ok" and (body.note or body.period_start or body.period_end):
        try:
            personal = app.container.resolve("personal")
            repo = out.get("repository") or {}
            ctx = personal.note_project_period(
                project=str(repo.get("name") or body.path or body.url or "repository"),
                note=body.note,
                period_start=body.period_start,
                period_end=body.period_end,
                repo_uid=repo.get("repo_uid"),
                root=repo.get("root") or body.path or body.url,
                actor="operator",
            )
            out["owner_context"] = ctx
        except Exception as exc:  # noqa: BLE001 - ingest still succeeds without timeline note
            out["owner_context"] = {"error": str(exc)}
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
    # Attach checkpoint progress (archive done/total) onto mission workers.
    try:
        workers = _workers(request)
        if hasattr(workers, "enrich_worker"):
            view["workers"] = [
                workers.enrich_worker(w) for w in (view.get("workers") or [])
            ]
    except Exception:  # noqa: BLE001 - progress is best-effort for the UI
        pass
    try:
        view["dag"] = _missions(request).get_dag(mission_id)
    except Exception:  # noqa: BLE001
        pass
    return view


@v1_router.get("/missions/{mission_id}/dag", tags=["missions"])
def get_mission_dag(mission_id: str, request: Request) -> dict:
    """IR-M1 — parent/child DAG snapshot for one mission."""
    try:
        return _missions(request).get_dag(mission_id)
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)


@v1_router.post("/missions/{mission_id}/children", tags=["missions"])
def spawn_mission_child(
    mission_id: str, body: SpawnChildMissionRequest, request: Request
) -> dict:
    """IR-M1 — spawn Extract/Verify/Summarize-style child under parent."""
    try:
        child = _missions(request).spawn_child(
            mission_id,
            body.title,
            body.objective,
            role=body.role,
            wait_on_child=body.wait_on_child,
            activate=body.activate,
            metadata=body.metadata,
        )
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)
    return {
        "child": _mission_row(child),
        "dag": _missions(request).get_dag(mission_id),
    }


@v1_router.post("/missions/{mission_id}/research-confidence", tags=["missions"])
def set_mission_research_confidence(
    mission_id: str, body: SetResearchConfidenceRequest, request: Request
) -> dict:
    """IR-M3 — store confidence so low-confidence work gets more scheduler attention."""
    try:
        mission = _missions(request).set_research_confidence(
            mission_id,
            confidence_score=body.confidence_score,
            confidence=body.confidence,
            source=body.source,
        )
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)
    return {"mission": _mission_row(mission)}


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
    """Write the next config version (immutable history) and optionally activate it.

    When ``tick_interval_seconds`` is present, align the mission worker schedule
    interval and pull ``next_run_at`` forward so catch-up config is not ignored until
    the old 24h (or longer) slot fires.
    """
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

    # Sync schedule interval when operator updates tick_interval_seconds (Career, etc.).
    try:
        doc = body.document or {}
        if "tick_interval_seconds" in doc:
            iv = max(60, int(doc.get("tick_interval_seconds") or 3600))
            workers = _workers(request)
            schedules = None
            try:
                schedules = _app(request).container.resolve("schedules")
            except Exception:  # noqa: BLE001
                schedules = None
            for w in workers.list_workers(mission_id=mission_id) or []:
                sid = getattr(w, "schedule_id", None) or (
                    w.get("schedule_id") if isinstance(w, dict) else None
                )
                if not sid or schedules is None:
                    continue
                if hasattr(schedules, "set_interval"):
                    schedules.set_interval(sid, iv)
                if hasattr(schedules, "bump_next_run"):
                    schedules.bump_next_run(sid, delay_seconds=15.0)
    except Exception:  # noqa: BLE001 - config write already succeeded
        pass

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
    capital: float | None = None,
    portfolio_key: str | None = None,
    max_candidates: int = 5,
    deploy_fraction: float = 0.40,
) -> dict:
    """IL.6 — Daily Investment Plan from M0 ranked watchlist (simulation sizing only).

    When ``capital`` is provided it sizes the plan (prefer live ledger cash from the UI).
    Otherwise capital is taken from the virtual book persona, defaulting to ₹10,000.
    """
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


@v1_router.get("/market/government-policy", tags=["programs"])
def market_government_policy(request: Request) -> dict:
    """India government budget/policy snapshot feeding sector ranking nudges."""
    from atlas.config import get_config
    from atlas.investment.government_policy import ensure_defaults, format_policy_brief

    snap = ensure_defaults(get_config().paths.data)
    return {**snap, "brief": format_policy_brief(snap)}


@v1_router.post("/market/government-policy", tags=["programs"])
def market_government_policy_update(request: Request, body: dict | None = None) -> dict:
    """Add operator policy/budget items (title, summary, sectors, delta)."""
    from atlas.config import get_config
    from atlas.investment.government_policy import refresh_catalog

    body = body or {}
    items = body.get("items") or body.get("policies") or []
    if isinstance(body.get("title"), str):
        items = [body, *list(items or [])]
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be a list")
    include_defaults = body.get("include_defaults")
    if include_defaults is None:
        include_defaults = True
    snap = refresh_catalog(
        get_config().paths.data,
        operator_items=[i for i in items if isinstance(i, dict)],
        include_defaults=bool(include_defaults),
    )
    return snap


@v1_router.get("/market/news-feeds", tags=["programs"])
def get_market_news_feeds() -> dict:
    """IIP.9 — RSS allow-list status + last fetch (no scrape)."""
    from atlas.config import get_config
    from atlas.investment.rss_feeds import allowlist_view, load_last_fetch

    data_dir = str(get_config().paths.data)
    return {
        **allowlist_view(),
        "last_fetch": load_last_fetch(data_dir),
    }


@v1_router.post("/market/news-feeds/fetch", tags=["programs"])
def post_market_news_feeds_fetch(body: dict | None = None) -> dict:
    """IIP.9 — fetch enabled allow-listed RSS/Atom feeds (bounded)."""
    from atlas.config import get_config
    from atlas.investment import rss_feeds as rss

    body = body or {}
    feeds = rss.merge_allowlist(
        body.get("feeds") if isinstance(body.get("feeds"), list) else None,
        include_defaults=bool(body.get("include_defaults", True)),
    )
    enable_ids = {str(x).strip() for x in (body.get("enable") or []) if str(x).strip()}
    if enable_ids:
        for row in feeds:
            if row.get("id") in enable_ids:
                row["enabled"] = True
    # Explicit feed dicts in body.feeds with enabled=true
    if isinstance(body.get("feeds"), list):
        for row in feeds:
            for raw in body["feeds"]:
                if isinstance(raw, dict) and str(raw.get("id")) == str(row.get("id")):
                    if "enabled" in raw:
                        row["enabled"] = bool(raw["enabled"])
                    if raw.get("url"):
                        row["url"] = raw["url"]
    kinds = body.get("kinds")
    result = rss.fetch_allowlist(
        feeds,
        kinds=[str(k) for k in kinds] if isinstance(kinds, list) else None,
        max_per_feed=int(body.get("max_per_feed") or 15),
    )
    data_dir = str(get_config().paths.data)
    rss.save_last_fetch(data_dir, result)
    into_policy = bool(body.get("into_policy"))
    policy_snap = None
    if into_policy:
        from atlas.investment.government_policy import refresh_catalog

        policy_items = rss.items_as_policy(result)
        policy_snap = refresh_catalog(
            data_dir,
            operator_items=policy_items,
            include_defaults=bool(body.get("include_defaults", True)),
        )
    return {
        "ok": True,
        "fetch": {
            "item_count": result.get("item_count"),
            "ok_feeds": result.get("ok_feeds"),
            "feeds": result.get("feeds"),
            "fetched_at": result.get("fetched_at"),
            "titles": [
                {"title": i.get("title"), "source": i.get("source")}
                for i in (result.get("items") or [])[:20]
            ],
        },
        "policy_snapshot": (
            {
                "item_count": policy_snap.get("item_count"),
                "updated_at": policy_snap.get("updated_at"),
            }
            if policy_snap
            else None
        ),
        "note": "Allow-list RSS/Atom only — HTML responses are refused.",
    }


@v1_router.get("/market/chart-links/{symbol}", tags=["programs"])
def get_market_chart_links(symbol: str) -> dict:
    """IIP.9 — TradingView / Yahoo chart links (non-primary)."""
    from atlas.investment.chart_links import chart_links_for

    return chart_links_for(symbol)


def _ist_today() -> str:
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()


def _investor_portfolio_doc(request: Request, program_id: str = "market_intelligence") -> dict | None:
    """Live learner book for preview/send — same path the evening worker uses."""
    try:
        from atlas.workers.investor_reports import InvestorReportsWorker

        app = _app(request)
        c = app.container
        mailer = c.resolve("investor_mailer")
        portfolio = None
        market_reader = None
        try:
            portfolio = c.resolve("portfolio")
        except Exception:  # noqa: BLE001
            try:
                portfolio = c.resolve("sim_portfolio")
            except Exception:  # noqa: BLE001
                portfolio = None
        try:
            market_reader = c.resolve("market_reader")
        except Exception:  # noqa: BLE001
            market_reader = None
        data_dir = getattr(mailer, "_data_dir", None)
        if not data_dir:
            try:
                from atlas.config import get_config

                data_dir = str(get_config().paths.data)
            except Exception:  # noqa: BLE001
                data_dir = None
        worker = InvestorReportsWorker(
            mailer=mailer,
            portfolio=portfolio,
            market_reader=market_reader,
            data_dir=data_dir,
        )
        # Prefer explicit config key; fall back to India learner.
        pkey = "india_equity_learner"
        if program_id and program_id != "market_intelligence":
            pkey = program_id
        return worker._portfolio_doc(pkey, ist_date=_ist_today())
    except Exception:  # noqa: BLE001
        return None


@v1_router.post("/market/investor-report/morning", tags=["programs"])
def market_investor_morning_report(
    request: Request,
    program_id: str = "market_intelligence",
    force: bool = True,
) -> dict:
    """Send the morning investment plan email to configured receivers."""
    try:
        mailer = _app(request).container.resolve("investor_mailer")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investor mailer unavailable: {exc}") from exc
    portfolio = _investor_portfolio_doc(request, program_id=program_id)
    return mailer.send_morning(program_id=program_id, portfolio=portfolio, force=force)


@v1_router.post("/market/investor-report/evening", tags=["programs"])
def market_investor_evening_report(
    request: Request,
    program_id: str = "market_intelligence",
    force: bool = True,
) -> dict:
    """Send the post-NSE evening EOD digest email to configured receivers."""
    try:
        mailer = _app(request).container.resolve("investor_mailer")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investor mailer unavailable: {exc}") from exc
    portfolio = _investor_portfolio_doc(request, program_id=program_id)
    return mailer.send_evening(program_id=program_id, portfolio=portfolio, force=force)


@v1_router.get("/market/investor-report/status", tags=["programs"])
def market_investor_report_status(request: Request) -> dict:
    """Check whether Gmail/SMTP + receivers are configured (no secrets returned)."""
    try:
        mailer = _app(request).container.resolve("investor_mailer")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investor mailer unavailable: {exc}") from exc
    return mailer.status()


@v1_router.get("/market/investor-report/preview", tags=["programs"])
def market_investor_report_preview(
    request: Request,
    program_id: str = "market_intelligence",
    kind: str = "morning",
) -> dict:
    """Build a report body without sending — for Market page review."""
    try:
        mailer = _app(request).container.resolve("investor_mailer")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investor mailer unavailable: {exc}") from exc
    portfolio = _investor_portfolio_doc(request, program_id=program_id)
    k = str(kind or "morning").strip().lower()
    if k == "evening":
        return mailer.preview_evening(program_id=program_id, portfolio=portfolio)
    if k in {"weekly", "research_weekly", "weekly_research"}:
        return mailer.preview_weekly_research(program_id=program_id)
    return mailer.preview_morning(program_id=program_id, portfolio=portfolio)


@v1_router.post("/market/investor-report/weekly", tags=["programs"])
def market_investor_weekly_report(
    request: Request,
    program_id: str = "market_intelligence",
    force: bool = True,
) -> dict:
    """Send the weekly research learning digest email."""
    try:
        mailer = _app(request).container.resolve("investor_mailer")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investor mailer unavailable: {exc}") from exc
    return mailer.send_weekly_research(program_id=program_id, force=force)


@v1_router.get("/market/research", tags=["programs"])
def market_research_list(
    request: Request,
    program_id: str = "market_intelligence",
) -> dict:
    """IRA — list researched symbols (awareness summaries)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    rows = research.list_researched(program_id=program_id)
    digest = research.daily_digest(program_id=program_id) if hasattr(research, "daily_digest") else {}
    return {"program_id": program_id, "count": len(rows), "items": rows, "digest": digest}


@v1_router.get("/market/research/compare", tags=["programs"])
def market_research_compare(
    request: Request,
    a: str,
    b: str,
    program_id: str = "market_intelligence",
    portfolio_ref: str | None = None,
) -> dict:
    """SI.6 — Why A vs B? Opportunity comparison (research framing, not a buy ticket)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    holdings: dict | None = None
    if portfolio_ref:
        try:
            from atlas.investment import portfolios as vp

            row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
            mid = (row or {}).get("mission_id") or (row or {}).get("ledger_mission_id")
            if mid:
                portfolio_svc = _app(request).container.resolve("portfolio")
                ensured = portfolio_svc.ensure_portfolio(
                    mission_id=mid,
                    name=(row or {}).get("portfolio_key") or "default",
                    starting_cash=float(((row or {}).get("persona") or {}).get("capital") or 0),
                )
                snap = portfolio_svc.snapshot(ensured["id"]) if hasattr(portfolio_svc, "snapshot") else None
                if snap is None and hasattr(portfolio_svc, "get_snapshot"):
                    snap = portfolio_svc.get_snapshot(ensured["id"])
                positions = (snap or {}).get("positions") or (snap or {}).get("holdings") or []
                holdings = {}
                for p in positions:
                    if not isinstance(p, dict):
                        continue
                    sym = p.get("symbol") or p.get("ticker")
                    qty = p.get("qty") if p.get("qty") is not None else p.get("quantity")
                    if sym:
                        holdings[str(sym)] = qty if qty is not None else 1
        except Exception:  # noqa: BLE001
            holdings = None
    return research.compare(a, b, program_id=program_id, holdings=holdings)


@v1_router.get("/market/research/{symbol}", tags=["programs"])
def market_research_get(
    request: Request,
    symbol: str,
    program_id: str = "market_intelligence",
    full: bool = False,
) -> dict:
    """IRA.2 — Research Awareness for a symbol (coverage ≠ confidence)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    awareness = research.awareness(symbol, program_id=program_id)
    out: dict = {"awareness": awareness}
    if full:
        out["dossier"] = research.dossier(symbol, program_id=program_id)
    return out


@v1_router.post("/market/research/{symbol}", tags=["programs"])
def market_research_start(
    request: Request,
    symbol: str,
    body: InvestmentResearchStartRequest | None = None,
) -> dict:
    """IRA.2b — start on-demand MVR (or deepen) research for any ticker path."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    body = body or InvestmentResearchStartRequest()
    return research.start(
        symbol,
        program_id=body.program_id,
        mode=body.mode,
        force=bool(body.force),
        allow_without_identity=bool(body.allow_without_identity),
        trigger=body.trigger or "on_demand",
    )


@v1_router.get("/market/research/{symbol}/identity", tags=["programs"])
def market_research_identity_get(
    request: Request,
    symbol: str,
    program_id: str = "market_intelligence",
) -> dict:
    """SI.1 — business identity for a symbol (resolve-on-read, no MVR)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    out = research.get_identity(symbol, program_id=program_id)
    return {
        "symbol": out.get("symbol"),
        "program_id": program_id,
        "business_identity": out.get("business_identity"),
        "gate": out.get("gate"),
    }


@v1_router.post("/market/research/{symbol}/identity", tags=["programs"])
def market_research_identity_set(
    request: Request,
    symbol: str,
    body: ResearchBusinessIdentityRequest,
) -> dict:
    """SI.1 — operator sets/confirms business identity (mandatory before MVR)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    payload = {
        k: getattr(body, k)
        for k in (
            "business_type",
            "industry",
            "sector",
            "subsector",
            "capital_intensity",
            "key_drivers",
            "revenue_model",
            "distinctiveness_seed",
            "pack_id",
        )
        if getattr(body, k, None) is not None
    }
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one identity field (sector, business_type, pack_id, …)",
        )
    return research.set_identity(
        symbol,
        payload,
        program_id=body.program_id,
        start_mvr=bool(body.start_mvr),
    )


@v1_router.post("/market/research/{symbol}/snapshot", tags=["programs"])
def market_research_operator_snapshot(
    request: Request,
    symbol: str,
    body: ResearchOperatorSnapshotRequest,
) -> dict:
    """IRA F1 — operator snapshot (layer 1) → ResearchMemory → incremental section refresh."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    fields = {
        k: getattr(body, k)
        for k in (
            "pe",
            "roe",
            "roic",
            "debt_to_equity",
            "fcf",
            "operating_margin",
            "net_margin",
            "revenue_cagr",
            "earnings_cagr",
            "price",
            "shares",
            "capex",
            "fcf_growth",
            "discount_rate",
            "promoter_holding",
            "sector",
        )
        if getattr(body, k, None) is not None
    }
    if not fields:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field (pe, fcf, price, shares, roe, …)",
        )
    return research.apply_operator_snapshot(
        symbol,
        fields,
        program_id=body.program_id,
        as_of=body.as_of,
        note=body.note,
        evidence_confidence=body.evidence_confidence,
        auto_refresh=bool(body.auto_refresh),
    )


@v1_router.post("/market/research/{symbol}/filings", tags=["programs"])
def market_research_filing_refs(
    request: Request,
    symbol: str,
    body: ResearchFilingRefsRequest,
) -> dict:
    """IRA.24 — attach filing refs (no scrape) → memory → incremental refresh."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    if not body.filings:
        raise HTTPException(status_code=400, detail="filings[] required (title + kind)")
    return research.apply_filing_refs(
        symbol,
        body.filings,
        program_id=body.program_id,
        as_of=body.as_of,
        note=body.note,
        auto_refresh=bool(body.auto_refresh),
    )


@v1_router.post("/market/research/{symbol}/critical-flag", tags=["programs"])
def market_research_critical_flag(
    request: Request,
    symbol: str,
    body: ResearchCriticalFlagRequest,
) -> dict:
    """IRA.26b — raise critical evidence (can block paper buys / force avoid)."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    return research.raise_critical_flag(
        symbol,
        text=body.text,
        kind=body.kind,
        program_id=body.program_id,
        affects=body.affects,
    )


@v1_router.post("/market/research/{symbol}/management", tags=["programs"])
def market_research_management_pack(
    symbol: str,
    body: ResearchManagementPackRequest,
    request: Request,
) -> dict:
    """IRA F3 — management checklist answers → section evidence + questions."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    if not body.answers:
        raise HTTPException(status_code=400, detail="answers required (checklist id → text)")
    return research.apply_management_pack(
        symbol,
        body.answers,
        program_id=body.program_id,
        operator_note=body.operator_note,
        evidence_level=body.evidence_level,
        auto_refresh=body.auto_refresh,
    )


@v1_router.post("/market/research-refresh", tags=["programs"])
def market_research_refresh(
    request: Request,
    program_id: str = "market_intelligence",
    max_symbols: int = 8,
    symbol: str | None = None,
) -> dict:
    """IRA.7 — incremental TTL refresh for stale dossier sections."""
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    return research.refresh_stale(
        symbol,
        program_id=program_id,
        max_symbols=max_symbols,
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


@v1_router.get("/market/universes", tags=["programs"])
def list_market_universes(request: Request) -> dict:
    """IIP.1 — list index/theme universes + enabled union."""
    from atlas.config import get_config
    from atlas.investment.universe_manager import universes_view

    return universes_view(str(get_config().paths.data))


@v1_router.post("/market/universes/enabled", tags=["programs"])
def set_market_universes_enabled(request: Request, body: dict | None = None) -> dict:
    """IIP.1 — persist which universes are enabled for the learner."""
    from atlas.config import get_config
    from atlas.investment.universe_manager import save_enabled, universes_view

    body = body or {}
    enabled = body.get("enabled") or body.get("universes") or []
    if not isinstance(enabled, list):
        raise HTTPException(status_code=400, detail="enabled must be a list of universe ids")
    data_dir = str(get_config().paths.data)
    save_enabled(data_dir, [str(x) for x in enabled])
    return universes_view(data_dir)


@v1_router.get("/market/feed-failures", tags=["programs"])
def list_market_feed_failures(
    request: Request,
    limit: int = 100,
    provider: str | None = None,
    symbol: str | None = None,
) -> dict:
    """Recent web/live market-data fetch failures for operator triage."""
    from atlas.config import get_config
    from atlas.investment.feed_failures import list_failures

    return list_failures(
        str(get_config().paths.data),
        limit=max(1, min(500, int(limit or 100))),
        provider=provider,
        symbol=symbol,
    )


@v1_router.get("/market/intelligence-catalog", tags=["programs"])
def market_intelligence_catalog(request: Request) -> dict:
    """Operator review: methodology, websites/sources, capabilities, live hooks."""
    from atlas.config import get_config
    from atlas.investment.feed_failures import list_failures
    from atlas.investment.intelligence_catalog import catalog_skeleton
    from atlas.investment.universe_manager import universes_view

    base = catalog_skeleton()
    cfg = get_config()
    data_dir = str(cfg.paths.data)
    yahoo_on = bool(getattr(cfg.market, "yahoo_enabled", False))
    providers: list[dict] = []
    try:
        reader = _app(request).container.resolve("market_reader")
        providers = reader.list_providers()
    except Exception:  # noqa: BLE001
        providers = []
    base["live"] = {
        "yahoo_enabled": yahoo_on,
        "providers": providers,
        "universes": universes_view(data_dir),
        "feed_failures": list_failures(data_dir, limit=40),
    }
    try:
        from atlas.investment.discovery import load_latest_discovery
        from atlas.investment.themes import themes_view

        base["live"]["themes"] = themes_view()
        base["live"]["discovery"] = load_latest_discovery(data_dir)
    except Exception:  # noqa: BLE001
        base["live"]["themes"] = {"themes": [], "count": 0}
        base["live"]["discovery"] = {"interesting": []}
    try:
        from atlas.investment.fundamentals import fundamentals_view

        base["live"]["fundamentals"] = fundamentals_view(data_dir, limit=25)
    except Exception:  # noqa: BLE001
        base["live"]["fundamentals"] = {"count": 0, "rows": []}
    try:
        from atlas.investment.fundamentals import learner_fundamentals_gaps, watchlist_symbols

        wl = watchlist_symbols("market_intelligence", limit=40)
        if wl and isinstance(base.get("live", {}).get("fundamentals"), dict):
            gaps = learner_fundamentals_gaps(data_dir, wl, program_id="market_intelligence")
            base["live"]["fundamentals"]["learner_gaps"] = gaps
    except Exception:  # noqa: BLE001
        pass
    try:
        from atlas.investment.company_documents import documents_view

        base["live"]["company_documents"] = documents_view(data_dir, limit=25)
    except Exception:  # noqa: BLE001
        base["live"]["company_documents"] = {"documents": [], "count": 0}
    try:
        from atlas.investment import mkg as mkg_mod

        graph = mkg_mod.ensure_seeded(data_dir)
        base["live"]["mkg"] = mkg_mod.graph_view(graph, limit_nodes=20, limit_edges=30)
        base["live"]["mkg_demo"] = {
            "why_own_waaree": mkg_mod.why_own(graph, "WAAREE.NS"),
            "who_benefits_defence": mkg_mod.who_benefits(graph, theme_id="defence", limit=12),
        }
    except Exception:  # noqa: BLE001
        base["live"]["mkg"] = {"stats": {"nodes": 0, "edges": 0}}
    try:
        from atlas.investment.thesis_tracker import list_trackers

        base["live"]["thesis_tracker"] = list_trackers(data_dir, limit=25)
    except Exception:  # noqa: BLE001
        base["live"]["thesis_tracker"] = {"trackers": [], "count": 0, "priors": {}}
    try:
        from atlas.investment.rss_feeds import allowlist_view, load_last_fetch

        base["live"]["news_feeds"] = {
            **allowlist_view(),
            "last_fetch": load_last_fetch(data_dir),
        }
    except Exception:  # noqa: BLE001
        base["live"]["news_feeds"] = {"feeds": [], "enabled_count": 0}
    try:
        from atlas.investment.chart_links import chart_links_for

        base["live"]["chart_links_demo"] = chart_links_for("INFY.NS")
    except Exception:  # noqa: BLE001
        base["live"]["chart_links_demo"] = {}
    return base


@v1_router.get("/market/fundamentals", tags=["programs"])
def get_market_fundamentals(
    program_id: str = "market_intelligence",
    limit: int = 40,
    include_learner_gaps: bool = True,
) -> dict:
    """IIP.3 / DI.4 — durable fundamentals store status (operator / Screener import)."""
    from atlas.config import get_config
    from atlas.investment.fundamentals import fundamentals_view

    data_dir = str(get_config().paths.data)
    gap_symbols = None
    if include_learner_gaps:
        try:
            from atlas.investment import watchlists as wl

            snap = wl.latest(program_id)
            if isinstance(snap, dict):
                gap_symbols = list(snap.get("watchlist_symbols") or [])[:40]
                if not gap_symbols:
                    watch = snap.get("watchlist") or []
                    gap_symbols = [
                        str(w.get("symbol"))
                        for w in watch
                        if isinstance(w, dict) and w.get("symbol")
                    ][:40]
        except Exception:  # noqa: BLE001
            gap_symbols = None
    return fundamentals_view(
        data_dir,
        program_id=program_id,
        limit=limit,
        gap_symbols=gap_symbols,
    )


@v1_router.get("/market/fundamentals/learner-template", tags=["programs"])
def get_market_fundamentals_learner_template(
    request: Request,
    program_id: str = "market_intelligence",
    only_gaps: bool = True,
    limit: int = 40,
    open_books_only: bool = False,
    portfolio_key: str = "india_equity_learner",
) -> dict:
    """DI.4 / E2 — CSV gap-fill template for learner PE/FCF (never invent).

    ``open_books_only=true`` restricts rows to current holdings (Screener densify).
    """
    from atlas.config import get_config
    from atlas.investment.fundamentals import learner_gap_fill_template

    data_dir = str(get_config().paths.data)
    symbols: list[str] = []
    if open_books_only:
        try:
            from atlas.investment.open_book_packs import resolve_open_symbols

            portfolio_svc = None
            try:
                portfolio_svc = _app(request).container.resolve("portfolio")
            except Exception:  # noqa: BLE001
                portfolio_svc = None
            if portfolio_svc is not None:
                symbols = resolve_open_symbols(
                    portfolio=portfolio_svc,
                    portfolio_key=str(portfolio_key or "india_equity_learner"),
                    limit=max(1, min(int(limit or 40), 80)),
                )
        except Exception:  # noqa: BLE001
            symbols = []
    if not symbols:
        try:
            from atlas.investment import watchlists as wl

            snap = wl.latest(program_id)
            if isinstance(snap, dict):
                symbols = list(snap.get("watchlist_symbols") or [])
                if not symbols:
                    watch = snap.get("watchlist") or snap.get("ranked") or []
                    symbols = [
                        str(w.get("symbol"))
                        for w in watch
                        if isinstance(w, dict) and w.get("symbol")
                    ]
        except Exception:  # noqa: BLE001
            symbols = []
    lim = max(1, min(int(limit or 40), 80))
    out = learner_gap_fill_template(
        data_dir,
        symbols[:lim],
        program_id=program_id,
        only_gaps=bool(only_gaps),
    )
    out["open_books_only"] = bool(open_books_only)
    out["portfolio_key"] = portfolio_key
    return out


@v1_router.post("/market/fundamentals/import", tags=["programs"])
def post_market_fundamentals_import(request: Request, body: dict | None = None) -> dict:
    """IIP.3 — import JSON rows or CSV text into fundamentals store."""
    from atlas.config import get_config
    from atlas.investment.fundamentals import import_csv_text, import_json_payload

    body = body or {}
    program_id = str(body.get("program_id") or "market_intelligence")
    source = str(body.get("source") or "operator_import")
    note = str(body.get("note") or "")
    data_dir = str(get_config().paths.data)
    if body.get("csv"):
        result = import_csv_text(
            data_dir,
            str(body["csv"]),
            program_id=program_id,
            source=str(body.get("source") or "screener_export"),
            note=note,
        )
    else:
        payload = body.get("rows") or body.get("symbols") or body.get("json")
        if payload is None:
            raise HTTPException(
                status_code=400,
                detail="Provide csv=... or rows=/symbols=/json= fundamentals payload",
            )
        result = import_json_payload(
            data_dir,
            payload,
            program_id=program_id,
            source=source,
            note=note,
        )

    # Optional: push each imported row into IRA operator-snapshot ladder
    if body.get("push_to_ira") and result.get("rows"):
        ira_out: list[dict] = []
        try:
            research = _app(request).container.resolve("investment_research")
        except Exception:  # noqa: BLE001
            research = None
        if research is not None:
            for row in result["rows"][: int(body.get("push_to_ira_limit") or 40)]:
                sym = row.get("symbol")
                if not sym:
                    continue
                fields = {
                    k: row[k]
                    for k in (
                        "roe",
                        "roce",
                        "roic",
                        "debt_to_equity",
                        "pe",
                        "pb",
                        "fcf",
                        "operating_margin",
                        "net_margin",
                        "revenue_cagr",
                        "earnings_cagr",
                        "promoter_holding",
                        "pledge_pct",
                        "price",
                        "shares",
                        "sector",
                    )
                    if row.get(k) is not None
                }
                # IRA / ranking expect fraction ROE when >1.5 stored as percent
                for ratio in ("roe", "roic"):
                    if fields.get(ratio) is not None and float(fields[ratio]) > 1.5:
                        fields[ratio] = float(fields[ratio]) / 100.0
                try:
                    ira_out.append(
                        research.apply_operator_snapshot(
                            str(sym),
                            fields,
                            program_id=program_id,
                            as_of=row.get("as_of"),
                            note=note or "Fundamentals import (IIP.3)",
                            evidence_confidence=str(
                                body.get("evidence_confidence") or "estimated"
                            ),
                            auto_refresh=bool(body.get("auto_refresh", False)),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    ira_out.append({"symbol": sym, "error": str(exc)[:200]})
        result["ira"] = {"pushed": len(ira_out), "items": ira_out[:10]}

    # DI.4 — recompute learner gaps after import so operator sees residual holes
    if body.get("include_learner_gaps", True):
        try:
            from atlas.investment import watchlists as wl
            from atlas.investment.fundamentals import learner_fundamentals_gaps

            snap = wl.latest(program_id)
            gap_symbols: list[str] = []
            if isinstance(snap, dict):
                gap_symbols = list(snap.get("watchlist_symbols") or [])[:40]
                if not gap_symbols:
                    watch = snap.get("watchlist") or []
                    gap_symbols = [
                        str(w.get("symbol"))
                        for w in watch
                        if isinstance(w, dict) and w.get("symbol")
                    ][:40]
            if gap_symbols:
                result["learner_gaps"] = learner_fundamentals_gaps(
                    data_dir, gap_symbols, program_id=program_id
                )
        except Exception:  # noqa: BLE001
            pass
    return result


@v1_router.post("/market/fundamentals/import-drop", tags=["programs"])
def post_market_fundamentals_import_drop(
    program_id: str = "market_intelligence",
) -> dict:
    """IIP.3 — ingest files from data/imports/fundamentals/."""
    from atlas.config import get_config
    from atlas.investment.fundamentals import import_drop_folder

    return import_drop_folder(str(get_config().paths.data), program_id=program_id)


@v1_router.post("/market/fundamentals/yahoo-enrich", tags=["programs"])
def post_market_fundamentals_yahoo_enrich(body: dict | None = None) -> dict:
    """LI.2 / LQ.7 — Yahoo fundamentals as medium-confidence evidence (never sole truth).

    With no ``symbols``, runs LQ.7 watchlist-gap enrich.
    Slow-and-steady: small ``batch_size`` (default 3); respects shared Yahoo rate gate.
    """
    from atlas.config import get_config
    from atlas.investment.fundamentals import enrich_from_yahoo, enrich_watchlist_gaps

    body = body or {}
    cfg = get_config()
    program_id = str(body.get("program_id") or "market_intelligence")
    enabled = bool(body.get("enabled", getattr(cfg.market, "yahoo_enabled", False)))
    symbols = body.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    batch_size = body.get("batch_size")
    limit = int(body.get("limit") or 40)
    if not symbols:
        return enrich_watchlist_gaps(
            str(cfg.paths.data),
            program_id=program_id,
            enabled=enabled,
            limit=limit,
            batch_size=int(batch_size) if batch_size is not None else None,
        )
    return enrich_from_yahoo(
        str(cfg.paths.data),
        [str(s) for s in symbols],
        program_id=program_id,
        enabled=enabled,
        only_gaps=bool(body.get("only_gaps", True)),
        batch_size=int(batch_size) if batch_size is not None else None,
    )


@v1_router.get("/market/fundamentals/yahoo-rate-gate", tags=["programs"])
def get_market_fundamentals_yahoo_rate_gate() -> dict:
    """LQ.7 — shared Yahoo pacing / cooldown status (API + worker)."""
    from atlas.config import get_config
    from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

    return get_yahoo_rate_gate(str(get_config().paths.data)).status()


@v1_router.get("/market/company-documents", tags=["programs"])
def get_market_company_documents(
    program_id: str = "market_intelligence",
    symbol: str | None = None,
    limit: int = 40,
) -> dict:
    """IIP.4 — list imported company documents (AR / quarterly / deck / transcript)."""
    from atlas.config import get_config
    from atlas.investment.company_documents import list_documents

    return list_documents(
        str(get_config().paths.data),
        program_id=program_id,
        symbol=symbol,
        limit=limit,
    )


@v1_router.post("/market/company-documents/import", tags=["programs"])
def post_market_company_documents_import(
    request: Request,
    body: dict | None = None,
) -> dict:
    """IIP.4 — import company PDF/TXT by host path or pasted text → IRA."""
    from atlas.config import get_config

    body = body or {}
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    path = body.get("path")
    text = body.get("text")
    if not path and text is None:
        raise HTTPException(status_code=400, detail="Provide path= or text=")
    program_id = str(body.get("program_id") or "market_intelligence")
    push = body.get("push_to_ira", True)
    if push:
        try:
            research = _app(request).container.resolve("investment_research")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"investment research unavailable: {exc}"
            ) from exc
        return research.apply_company_document(
            symbol,
            kind=str(body.get("kind") or "annual"),
            path=str(path) if path else None,
            text=str(text) if text is not None else None,
            title=str(body.get("title") or ""),
            as_of=body.get("as_of"),
            period=str(body.get("period") or ""),
            note=str(body.get("note") or ""),
            program_id=program_id,
            auto_refresh=bool(body.get("auto_refresh", True)),
            apply_numeric_fields=bool(body.get("apply_numeric_fields", True)),
            ocr_enabled=bool(body.get("ocr_enabled", True)),
        )
    from atlas.investment.company_documents import ingest_path

    return ingest_path(
        str(get_config().paths.data),
        path or "",
        symbol=symbol,
        kind=str(body.get("kind") or "annual"),
        program_id=program_id,
        as_of=body.get("as_of"),
        period=str(body.get("period") or ""),
        note=str(body.get("note") or ""),
        title=str(body.get("title") or ""),
        text_override=str(text) if text is not None else None,
        ocr_enabled=bool(body.get("ocr_enabled", True)),
    )


@v1_router.post("/market/company-documents/import-drop", tags=["programs"])
def post_market_company_documents_import_drop(
    request: Request,
    body: dict | None = None,
) -> dict:
    """IIP.4 — ingest drop folder + optionally push each file to IRA."""
    from atlas.config import get_config
    from atlas.investment.company_documents import import_drop_folder
    from pathlib import Path

    body = body or {}
    program_id = str(body.get("program_id") or "market_intelligence")
    data_dir = str(get_config().paths.data)
    push = body.get("push_to_ira", True)
    # Import files into manifests first (moves to done/)
    dropped = import_drop_folder(data_dir, program_id=program_id)
    if not push:
        return dropped
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        dropped["ira_error"] = str(exc)[:200]
        return dropped
    ira_items: list[dict] = []
    done_dir = Path(data_dir) / "imports" / "company_documents" / "done"
    for row in dropped.get("files") or []:
        if row.get("error") or not row.get("symbol"):
            continue
        fname = row.get("file")
        fpath = done_dir / fname if fname else None
        if not fpath or not fpath.is_file():
            continue
        try:
            ira_items.append(
                research.apply_company_document(
                    str(row["symbol"]),
                    kind=str(row.get("kind") or "annual"),
                    path=str(fpath),
                    program_id=program_id,
                    note=f"drop:{fname}",
                    auto_refresh=bool(body.get("auto_refresh", False)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            ira_items.append({"symbol": row.get("symbol"), "error": str(exc)[:200]})
    dropped["ira"] = {
        "pushed": sum(1 for x in ira_items if x.get("ok")),
        "items": [
            {
                "symbol": x.get("symbol"),
                "claims_count": x.get("claims_count"),
                "coverage_after": x.get("coverage_after"),
                "lifted": x.get("lifted"),
                "error": x.get("error"),
            }
            for x in ira_items[:20]
        ],
    }
    return dropped


@v1_router.get("/market/mkg", tags=["programs"])
def get_market_mkg(
    limit_nodes: int = 40,
    limit_edges: int = 60,
    reseed: bool = False,
) -> dict:
    """IIP.5 — Market Knowledge Graph snapshot."""
    from atlas.config import get_config
    from atlas.investment import mkg as mkg_mod

    data_dir = str(get_config().paths.data)
    graph = mkg_mod.ensure_seeded(data_dir, force=reseed)
    return mkg_mod.graph_view(graph, limit_nodes=limit_nodes, limit_edges=limit_edges)


@v1_router.get("/market/mkg/neighborhood", tags=["programs"])
def get_market_mkg_neighborhood(
    symbol: str | None = None,
    node: str | None = None,
    depth: int = 1,
    limit: int = 80,
) -> dict:
    """IIP.5 — 1-hop neighborhood around a company or node."""
    from atlas.config import get_config
    from atlas.investment import mkg as mkg_mod

    if not symbol and not node:
        raise HTTPException(status_code=400, detail="symbol= or node= required")
    graph = mkg_mod.ensure_seeded(str(get_config().paths.data))
    return mkg_mod.neighborhood(graph, symbol=symbol, node=node, depth=depth, limit=limit)


@v1_router.get("/market/mkg/why-own/{symbol}", tags=["programs"])
def get_market_mkg_why_own(
    symbol: str,
    program_id: str = "market_intelligence",
) -> dict:
    """IIP.5 — Why own/watch X? (theme + policy edges + fundamentals cites)."""
    from atlas.config import get_config
    from atlas.investment import mkg as mkg_mod

    data_dir = str(get_config().paths.data)
    graph = mkg_mod.ensure_seeded(data_dir)
    fin = mkg_mod.financial_cites_for(data_dir, symbol, program_id=program_id)
    return mkg_mod.why_own(graph, symbol, financial_cites=fin)


@v1_router.get("/market/mkg/who-benefits", tags=["programs"])
def get_market_mkg_who_benefits(theme_id: str, limit: int = 40) -> dict:
    """IIP.5 — Who benefits from theme Y?"""
    from atlas.config import get_config
    from atlas.investment import mkg as mkg_mod

    if not (theme_id or "").strip():
        raise HTTPException(status_code=400, detail="theme_id required")
    graph = mkg_mod.ensure_seeded(str(get_config().paths.data))
    return mkg_mod.who_benefits(graph, theme_id=theme_id, limit=limit)


@v1_router.post("/market/mkg/reseed", tags=["programs"])
def post_market_mkg_reseed() -> dict:
    """IIP.5 — rebuild hermetic MKG from themes + policy catalog."""
    from atlas.config import get_config
    from atlas.investment import mkg as mkg_mod
    from atlas.investment.mkg.store import store_path

    data_dir = str(get_config().paths.data)
    graph = mkg_mod.ensure_seeded(data_dir, force=True)
    return {
        "ok": True,
        "stats": graph.get("stats"),
        "path": str(store_path(data_dir)),
        "graph": mkg_mod.graph_view(graph, limit_nodes=15, limit_edges=20),
    }


@v1_router.get("/market/score/{symbol}", tags=["programs"])
def get_market_investment_score(
    request: Request,
    symbol: str,
    horizon: str = "long_term",
    program_id: str = "market_intelligence",
) -> dict:
    """IIP.6 — multi-axis investment score + dual confidence."""
    from atlas.investment.scoring import score_from_awareness

    try:
        research = _app(request).container.resolve("investment_research")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"investment research unavailable: {exc}") from exc
    aw = research.awareness(symbol, program_id=program_id)
    score = score_from_awareness(aw, horizon=horizon)
    gate = research.gate_buy(symbol, program_id=program_id)
    return {
        "symbol": score.get("symbol") or symbol,
        "score": score,
        "gate": {
            "allowed": gate.get("allowed"),
            "action": gate.get("action"),
            "reasons": gate.get("reasons"),
            "score_band": gate.get("score_band"),
            "research_confidence": gate.get("research_confidence"),
            "investment_confidence": gate.get("investment_confidence"),
        },
        "note": score.get("note"),
    }


@v1_router.get("/market/decisions/{decision_id}", tags=["programs"])
def get_market_decision_packet(request: Request, decision_id: str) -> dict:
    """DI.1 — fetch a frozen Decision Packet by id (immutable)."""
    from atlas.investment.decision_packets import PACKET_VERSION, mirror_by_id_path

    try:
        store = _app(request).container.resolve("decision_packets")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"decision packets unavailable: {exc}") from exc
    packet = store.get(decision_id)
    if not packet:
        raise HTTPException(status_code=404, detail=f"decision packet {decision_id} not found")
    mirror = None
    data_dir = getattr(store, "data_dir", None)
    if data_dir:
        mirror = str(mirror_by_id_path(data_dir, decision_id))
    return {
        "packet": packet,
        "mirror_path": mirror,
        "version": packet.get("version") or PACKET_VERSION,
    }


@v1_router.get("/market/decisions/{decision_id}/genealogy", tags=["programs"])
def get_market_decision_genealogy(
    request: Request,
    decision_id: str,
    laboratory_id: str | None = None,
    persist: bool = True,
) -> dict:
    """GENE.1 / OI-GENE0 — assemble Decision→…→lesson→next with honest gaps."""
    from atlas.investment.decision_genealogy import VERSION, build_genealogy

    packets = None
    attrs = None
    data_dir = None
    try:
        packets = _app(request).container.resolve("decision_packets")
        data_dir = getattr(packets, "data_dir", None)
    except Exception:  # noqa: BLE001
        packets = None
    try:
        attrs = _app(request).container.resolve("decision_attributions")
    except Exception:  # noqa: BLE001
        attrs = None
    if packets is None and not data_dir:
        raise HTTPException(status_code=503, detail="decision packets unavailable")
    doc = build_genealogy(
        decision_id,
        data_dir=data_dir,
        packets_store=packets,
        attributions_store=attrs,
        laboratory_id=laboratory_id,
        persist=bool(persist),
    )
    hops = doc.get("hops") or []
    if hops and hops[0].get("hop") == "decision" and not hops[0].get("present"):
        raise HTTPException(
            status_code=404, detail=f"decision packet {decision_id} not found"
        )
    return {"genealogy": doc, "version": doc.get("version") or VERSION}


@v1_router.get("/market/decisions/{decision_id}/replay", tags=["programs"])
def get_market_decision_replay(
    request: Request,
    decision_id: str,
    laboratory_id: str | None = None,
    strategy_tag: str | None = None,
    experiment_id: str | None = None,
) -> dict:
    """DI.Attr / LI.4 — Replay: frozen packet + timeline + attribution.

    Optional ``laboratory_id`` / ``strategy_tag`` / ``experiment_id`` filters
    return 404 when the decision does not match (no invented data).
    """
    try:
        store = _app(request).container.resolve("decision_attributions")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision attributions unavailable: {exc}"
        ) from exc
    replay = store.build_replay(
        decision_id,
        laboratory_id=laboratory_id,
        strategy_tag=strategy_tag,
        experiment_id=experiment_id,
    )
    if replay.get("matched") is False:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"replay filters did not match {decision_id}",
                "mismatch_reasons": replay.get("mismatch_reasons") or [],
                "filters": replay.get("filters"),
            },
        )
    if not replay.get("packet"):
        # Still return timeline/attr if packet missing
        try:
            packets = _app(request).container.resolve("decision_packets")
            pkt = packets.get(decision_id)
            if pkt:
                replay["packet"] = pkt
        except Exception:  # noqa: BLE001
            pass
    if not replay.get("packet") and not replay.get("attributions"):
        raise HTTPException(status_code=404, detail=f"no replay data for {decision_id}")
    return replay


@v1_router.get("/market/replays", tags=["programs"])
def get_market_replays(
    request: Request,
    laboratory_id: str = "india_equity_learner",
    strategy_tag: str | None = None,
    experiment_id: str | None = None,
    limit: int = 40,
) -> dict:
    """LI.4 — list replay candidates filtered by lab / strategy / experiment."""
    try:
        store = _app(request).container.resolve("decision_attributions")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision attributions unavailable: {exc}"
        ) from exc
    items = store.list_replay_candidates(
        laboratory_id=laboratory_id,
        strategy_tag=strategy_tag,
        experiment_id=experiment_id,
        limit=max(1, min(200, int(limit))),
    )
    return {
        "ok": True,
        "laboratory_id": laboratory_id,
        "strategy_tag": strategy_tag,
        "experiment_id": experiment_id,
        "count": len(items),
        "items": items,
        "version": "li.4.replay_filters",
    }


@v1_router.get("/market/attributions", tags=["programs"])
def list_market_attributions(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    decision_id: str | None = None,
    limit: int = 40,
) -> dict:
    """DI.Attr — list outcome attributions."""
    try:
        store = _app(request).container.resolve("decision_attributions")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision attributions unavailable: {exc}"
        ) from exc
    lim = max(1, min(int(limit or 40), 100))
    if decision_id:
        items = store.list_for_decision(decision_id, limit=lim)
    else:
        items = store.list_portfolio(portfolio_key=portfolio_key, limit=lim)
    return {
        "count": len(items),
        "items": items,
        "portfolio_key": portfolio_key,
        "decision_id": decision_id,
        "version": "di.attr.1",
    }


@v1_router.post("/market/attributions", tags=["programs"])
def post_market_attribution(request: Request, body: dict | None = None) -> dict:
    """DI.Attr — operator/manual attribution for a decision."""
    try:
        store = _app(request).container.resolve("decision_attributions")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision attributions unavailable: {exc}"
        ) from exc
    body = body or {}
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    result = store.record(
        decision_id=str(body["decision_id"]) if body.get("decision_id") else None,
        symbol=symbol,
        portfolio_key=str(body.get("portfolio_key") or "india_equity_learner"),
        trigger=str(body.get("trigger") or "manual"),
        checkpoint=body.get("checkpoint"),
        pnl=float(body["pnl"]) if body.get("pnl") is not None else None,
        price_change_pct=float(body["price_change_pct"])
        if body.get("price_change_pct") is not None
        else None,
        what_changed=body.get("what_changed")
        if isinstance(body.get("what_changed"), dict)
        else None,
        what_atlas_missed=list(body.get("what_atlas_missed") or [])
        if body.get("what_atlas_missed")
        else None,
        extra=body.get("extra") if isinstance(body.get("extra"), dict) else None,
        failure_cause=body.get("failure_cause"),
    )
    return {"ok": True, **result}


@v1_router.get("/market/learning-intelligence", tags=["programs"])
def get_market_learning_intelligence(
    request: Request,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    evolution_limit: int = 40,
) -> dict:
    """LI.5b — Atlas IQ skill axes, evolution narratives, hypotheses, readiness."""
    from atlas.config import get_config
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore
    from atlas.investment.decision_timeline import DecisionTimelineStore
    from atlas.investment.laboratory import normalize_laboratory_id
    from atlas.investment.learning_intelligence import build_learning_intelligence_report
    from atlas.investment.ml_export import build_export_quality_report
    from atlas.investment.observations import DecisionObservationStore

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    data_dir = str(get_config().paths.data)
    packets: list = []
    attributions: list = []
    observations: list = []
    pending = 0
    done = 0
    process_score = None
    try:
        packets = DecisionPacketStore(data_dir=data_dir).list_day(
            portfolio_key=lab, limit=100
        )
    except Exception:  # noqa: BLE001
        packets = []
    try:
        attributions = DecisionAttributionStore(data_dir=data_dir).list_portfolio(
            portfolio_key=lab, limit=100
        )
    except Exception:  # noqa: BLE001
        attributions = []
    try:
        observations = DecisionObservationStore(data_dir=data_dir).list_since(
            since_hours=72.0, limit=80
        )
    except Exception:  # noqa: BLE001
        observations = []
    try:
        counts = DecisionTimelineStore(data_dir=data_dir).learning_counts(
            portfolio_key=lab
        )
        pending = int(counts.get("pending_revisits") or 0)
        done = int(counts.get("done_revisits") or 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        port = _app(request).container.resolve("portfolio")
        snap = None
        if hasattr(port, "snapshot"):
            snap = port.snapshot(portfolio_key=lab)
        elif hasattr(port, "get"):
            snap = port.get(lab)
        if isinstance(snap, dict):
            prox = snap.get("process_proxies")
            if isinstance(prox, dict):
                process_score = prox.get("process_score")
    except Exception:  # noqa: BLE001
        pass
    quality = build_export_quality_report(
        packets=packets if isinstance(packets, list) else [],
        attributions=attributions if isinstance(attributions, list) else [],
        laboratory_id=lab,
    )
    return build_learning_intelligence_report(
        data_dir,
        laboratory_id=lab,
        program_id=program_id,
        packets=packets if isinstance(packets, list) else [],
        attributions=attributions if isinstance(attributions, list) else [],
        process_score=process_score,
        pending_revisits=pending,
        done_revisits=done,
        observation_count=len(observations) if isinstance(observations, list) else 0,
        evolution_limit=max(1, min(200, int(evolution_limit))),
        quality=quality,
    )


@v1_router.get("/market/hypotheses", tags=["programs"])
def get_market_hypotheses(
    laboratory_id: str | None = "india_equity_learner",
    include_world: bool = True,
    status: str | None = None,
    limit: int = 40,
) -> dict:
    """LI.5b / LI.0a.9 — list scientific hypotheses (not per-symbol theses)."""
    from atlas.config import get_config
    from atlas.investment.hypothesis_learning import list_hypotheses

    items = list_hypotheses(
        str(get_config().paths.data),
        laboratory_id=laboratory_id or None,
        include_world=bool(include_world),
        status=status,
        limit=max(1, min(200, int(limit))),
    )
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "version": "li.5b.hypothesis_learning",
    }


@v1_router.post("/market/hypotheses", tags=["programs"])
def post_market_hypothesis(body: dict | None = None) -> dict:
    """LI.5b — create a scientific hypothesis (world or lab-scoped)."""
    from atlas.config import get_config
    from atlas.investment.hypothesis_learning import create_hypothesis

    body = body or {}
    try:
        return {
            "ok": True,
            **create_hypothesis(
                str(get_config().paths.data),
                statement=str(body.get("statement") or ""),
                domain_tags=list(body.get("domain_tags") or [])
                if body.get("domain_tags")
                else None,
                laboratory_id=body.get("laboratory_id"),
                transfer_class=str(body.get("transfer_class") or "world"),
                linked_decision_ids=list(body.get("linked_decision_ids") or [])
                if body.get("linked_decision_ids")
                else None,
                linked_experiment_ids=list(body.get("linked_experiment_ids") or [])
                if body.get("linked_experiment_ids")
                else None,
                extra=body.get("extra") if isinstance(body.get("extra"), dict) else None,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@v1_router.post("/market/hypotheses/{hypothesis_id}/verdict", tags=["programs"])
def post_market_hypothesis_verdict(hypothesis_id: str, body: dict | None = None) -> dict:
    """LI.5b — gated hypothesis verdict job (thin evidence → inconclusive)."""
    from atlas.config import get_config
    from atlas.investment.hypothesis_learning import record_verdict

    body = body or {}
    try:
        return {
            "ok": True,
            **record_verdict(
                str(get_config().paths.data),
                hypothesis_id=hypothesis_id,
                verdict=str(body.get("verdict") or ""),
                laboratory_id=body.get("laboratory_id"),
                evidence_n=int(body["evidence_n"]) if body.get("evidence_n") is not None else None,
                note=str(body.get("note") or ""),
                force=bool(body.get("force") or False),
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@v1_router.get("/market/di-dashboards", tags=["programs"])
def get_market_di_dashboards(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    ist_date: str | None = None,
) -> dict:
    """DI.3 — staged dashboards D1–D6 with sample gates (never mix strategy_tags)."""
    from atlas.config import get_config
    from atlas.investment.di_dashboards import collect_dashboard_inputs

    data_dir = str(get_config().paths.data)
    portfolio: dict | None = None
    try:
        port = _app(request).container.resolve("portfolio")
        if hasattr(port, "snapshot"):
            snap = port.snapshot(portfolio_key=portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
        elif hasattr(port, "get"):
            snap = port.get(portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
    except Exception:  # noqa: BLE001
        portfolio = None
    return collect_dashboard_inputs(
        data_dir=data_dir,
        portfolio_key=portfolio_key,
        portfolio=portfolio,
        ist_date=ist_date,
    )


@v1_router.get("/market/process-proxies", tags=["programs"])
def get_market_process_proxies(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    ist_date: str | None = None,
) -> dict:
    """DI.5 — process proxies scorecard (FOMO/revenge/hesitation/… — no emotions)."""
    from atlas.config import get_config
    from atlas.investment.process_proxies import collect_process_scorecard

    data_dir = str(get_config().paths.data)
    portfolio: dict | None = None
    try:
        port = _app(request).container.resolve("portfolio")
        if hasattr(port, "snapshot"):
            snap = port.snapshot(portfolio_key=portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
        elif hasattr(port, "get"):
            snap = port.get(portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
    except Exception:  # noqa: BLE001
        portfolio = None
    return collect_process_scorecard(
        data_dir=data_dir,
        portfolio_key=portfolio_key,
        portfolio=portfolio,
        ist_date=ist_date,
    )


@v1_router.get("/market/meta-learning", tags=["programs"])
def get_market_meta_learning(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    lookback_days: int = 14,
) -> dict:
    """DI.6 — weekly meta-learning / Intelligence Dashboard digest (proposals only)."""
    from atlas.config import get_config
    from atlas.investment.meta_learning import collect_meta_learning_inputs

    data_dir = str(get_config().paths.data)
    portfolio: dict | None = None
    try:
        port = _app(request).container.resolve("portfolio")
        if hasattr(port, "snapshot"):
            snap = port.snapshot(portfolio_key=portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
        elif hasattr(port, "get"):
            snap = port.get(portfolio_key)
            if isinstance(snap, dict):
                portfolio = snap
    except Exception:  # noqa: BLE001
        portfolio = None
    return collect_meta_learning_inputs(
        data_dir=data_dir,
        portfolio_key=portfolio_key,
        portfolio=portfolio,
        lookback_days=max(1, min(int(lookback_days or 14), 60)),
    )


@v1_router.post("/market/meta-learning/run", tags=["programs"])
def post_market_meta_learning_run(
    request: Request,
    body: dict | None = None,
) -> dict:
    """DI.6 — force-build meta-learning digest (same as weekly worker; no strategy edit)."""
    from atlas.config import get_config
    from atlas.investment.meta_learning import collect_meta_learning_inputs

    body = body or {}
    portfolio_key = str(body.get("portfolio_key") or "india_equity_learner")
    lookback_days = max(1, min(int(body.get("lookback_days") or 14), 60))
    data_dir = str(get_config().paths.data)
    doc = collect_meta_learning_inputs(
        data_dir=data_dir,
        portfolio_key=portfolio_key,
        lookback_days=lookback_days,
    )
    return {"ok": True, "digest": doc}


@v1_router.get("/market/ml-export", tags=["programs"])
def get_market_ml_export_status(
    portfolio_key: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict:
    """DI.7 / LI.4 — ML export gate status + quality report (never enables live NN)."""
    from atlas.config import get_config
    from atlas.investment.ml_export import ml_export_status

    return ml_export_status(
        data_dir=str(get_config().paths.data),
        portfolio_key=portfolio_key,
        lookback_limit=max(50, min(int(lookback_limit or 500), 2000)),
    )


@v1_router.get("/market/export-quality", tags=["programs"])
def get_market_export_quality(
    laboratory_id: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict:
    """LI.4/LI.5b — export quality report + readiness gauge (never enables live NN)."""
    from atlas.config import get_config
    from atlas.investment.ml_export import collect_export_quality_report

    return {
        "ok": True,
        **collect_export_quality_report(
            data_dir=str(get_config().paths.data),
            laboratory_id=laboratory_id,
            lookback_limit=max(50, min(int(lookback_limit or 500), 2000)),
        ),
    }


@v1_router.get("/market/atlasnet-prep", tags=["programs"])
def get_market_atlasnet_prep_status(
    laboratory_id: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict:
    """LI.6 — AtlasNet prep status (lab-partitioned export readiness; no NN)."""
    from atlas.config import get_config
    from atlas.investment.atlasnet_prep import atlasnet_prep_status

    return atlasnet_prep_status(
        data_dir=str(get_config().paths.data),
        laboratory_id=laboratory_id,
        lookback_limit=max(50, min(int(lookback_limit or 500), 2000)),
    )


@v1_router.post("/market/atlasnet-prep", tags=["programs"])
def post_market_atlasnet_prep(body: dict | None = None) -> dict:
    """LI.6 — quality-gated lab-partitioned export + walk-forward contract stub.

    Requires sample gate + readiness (or force_override + override_note).
    Never trains or deploys live/paper NN.
    """
    from atlas.config import get_config
    from atlas.investment.atlasnet_prep import export_atlasnet_prep

    body = body or {}
    force = bool(body.get("force_override") or body.get("force"))
    note = str(body.get("override_note") or body.get("note") or "")
    if force and not note.strip():
        raise HTTPException(
            status_code=400,
            detail="force_override requires a non-empty override_note",
        )
    return export_atlasnet_prep(
        data_dir=str(get_config().paths.data),
        laboratory_id=str(
            body.get("laboratory_id") or body.get("portfolio_key") or "india_equity_learner"
        ),
        force_override=force,
        override_note=note,
        lookback_limit=max(50, min(int(body.get("lookback_limit") or 500), 2000)),
        train_frac=float(body.get("train_frac") or 0.7),
    )


@v1_router.get("/market/atlasnet-hard-gate", tags=["programs"])
def get_market_atlasnet_hard_gate(
    laboratory_id: str = "india_equity_learner",
    lookback_limit: int = 800,
) -> dict:
    """LQ.9 — §8.2 AtlasNet hard gate status (prep ≠ train)."""
    from atlas.config import get_config
    from atlas.investment.atlasnet_prep import atlasnet_prep_status

    st = atlasnet_prep_status(
        data_dir=str(get_config().paths.data),
        laboratory_id=laboratory_id,
        lookback_limit=max(50, min(int(lookback_limit or 800), 5000)),
    )
    return {
        "version": "lq.9.hard_gate",
        "laboratory_id": st.get("laboratory_id"),
        "hard_gate": st.get("hard_gate"),
        "train_allowed": st.get("train_allowed"),
        "export_allowed": st.get("export_allowed"),
        "live_nn_trading": False,
        "atlasnet_status": st.get("atlasnet_status"),
        "next_step": st.get("next_step"),
    }


@v1_router.post("/market/atlasnet-train", tags=["programs"])
def post_market_atlasnet_train(body: dict | None = None) -> dict:
    """LQ.9 — train/paper-NN entry. Blocked unless §8.2 hard gate clears.

    ``force_override`` cannot unlock training (prep export only).
    """
    from atlas.config import get_config
    from atlas.investment.atlasnet_prep import request_atlasnet_train

    body = body or {}
    return request_atlasnet_train(
        data_dir=str(get_config().paths.data),
        laboratory_id=str(
            body.get("laboratory_id") or body.get("portfolio_key") or "india_equity_learner"
        ),
        intent=str(body.get("intent") or "train"),
        lookback_limit=max(50, min(int(body.get("lookback_limit") or 800), 5000)),
        learned_beats_rules=bool(body.get("learned_beats_rules")),
        force_override=bool(body.get("force_override") or body.get("force")),
        override_note=str(body.get("override_note") or body.get("note") or ""),
    )


@v1_router.post("/market/ml-export", tags=["programs"])
def post_market_ml_export(body: dict | None = None) -> dict:
    """DI.7 — gated ML-ready JSONL export + offline rules-baseline eval.

    Requires ≥300 trusted closed attributable exits on a strategy_tag, or
    ``force_override`` + ``override_note``. Never trains or deploys live NN.
    """
    from atlas.config import get_config
    from atlas.investment.ml_export import export_ml_dataset

    body = body or {}
    force = bool(body.get("force_override") or body.get("force"))
    note = str(body.get("override_note") or body.get("note") or "")
    if force and not note.strip():
        raise HTTPException(
            status_code=400,
            detail="force_override requires override_note (operator rationale)",
        )
    return export_ml_dataset(
        data_dir=str(get_config().paths.data),
        portfolio_key=str(body.get("portfolio_key") or "india_equity_learner"),
        force_override=force,
        override_note=note,
        lookback_limit=max(50, min(int(body.get("lookback_limit") or 500), 2000)),
    )


@v1_router.get("/market/decisions", tags=["programs"])
def list_market_decision_packets(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    ist_date: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> dict:
    """DI.1 — list Decision Packets by IST day and/or symbol."""
    from atlas.investment.decision_packets import ist_today, summarize_packet

    try:
        store = _app(request).container.resolve("decision_packets")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"decision packets unavailable: {exc}") from exc
    lim = max(1, min(int(limit or 50), 200))
    if symbol:
        items = store.list_symbol(
            symbol=symbol, limit=lim, portfolio_key=portfolio_key or None
        )
        return {
            "count": len(items),
            "items": [summarize_packet(p) for p in items],
            "symbol": symbol,
            "portfolio_key": portfolio_key,
        }
    day = ist_date or ist_today()
    items = store.list_day(portfolio_key=portfolio_key, ts_ist=day, limit=lim)
    return {
        "count": len(items),
        "items": [summarize_packet(p) for p in items],
        "ist_date": day,
        "portfolio_key": portfolio_key,
    }


@v1_router.get("/market/timeline/{symbol}", tags=["programs"])
def get_market_timeline(
    request: Request,
    symbol: str,
    kind: str | None = None,
    limit: int = 100,
) -> dict:
    """DI.2 — Market Timeline events for a symbol (append-only)."""
    try:
        store = _app(request).container.resolve("decision_timeline")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"decision timeline unavailable: {exc}") from exc
    lim = max(1, min(int(limit or 100), 500))
    events = store.list_symbol(symbol=symbol, limit=lim, kind=kind)
    return {
        "symbol": symbol,
        "count": len(events),
        "kind": kind,
        "events": events,
        "version": "di.timeline.1",
    }


@v1_router.get("/market/timeline", tags=["programs"])
def get_market_timeline_overview(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    ist_date: str | None = None,
) -> dict:
    """DI.2 — evolution counts + due revisits for a book."""
    from atlas.investment.decision_timeline import ist_today

    try:
        store = _app(request).container.resolve("decision_timeline")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"decision timeline unavailable: {exc}") from exc
    day = ist_date or ist_today()
    due = store.list_due(as_of_ist=day, portfolio_key=portfolio_key, limit=40)
    counts = store.learning_counts(portfolio_key=portfolio_key)
    return {
        "portfolio_key": portfolio_key,
        "ist_date": day,
        "counts": counts,
        "due_revisits": due,
        "due_count": len(due),
        "version": "di.timeline.1",
    }


@v1_router.post("/market/timeline/run-revisits", tags=["programs"])
def post_market_timeline_run_revisits(
    request: Request,
    portfolio_key: str = "india_equity_learner",
    limit: int = 20,
) -> dict:
    """DI.2 — operator force-run due evolution revisits (simulation)."""
    try:
        store = _app(request).container.resolve("decision_timeline")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"decision timeline unavailable: {exc}") from exc
    research = None
    market = None
    try:
        research = _app(request).container.resolve("investment_research")
    except Exception:  # noqa: BLE001
        research = None
    try:
        market = _app(request).container.resolve("market_reader")
    except Exception:  # noqa: BLE001
        market = None

    def mark_fn(symbol: str):
        if market is None:
            return None
        try:
            out = market.bars_for(symbol, provider="yahoo", limit=1)
            bars = list((out or {}).get("bars") or [])
            if bars and bars[-1].get("close") is not None:
                return float(bars[-1]["close"])
        except Exception:  # noqa: BLE001
            return None
        return None

    def awareness_fn(symbol: str):
        if research is None:
            return None
        try:
            return research.awareness(symbol, program_id="market_intelligence")
        except Exception:  # noqa: BLE001
            return None

    observations = None
    try:
        observations = _app(request).container.resolve("decision_observations")
    except Exception:  # noqa: BLE001
        observations = None

    def observations_fn(symbol: str):
        if observations is None:
            return []
        try:
            return list(
                observations.list_symbol(symbol=symbol, limit=20, since_hours=168.0) or []
            )
        except Exception:  # noqa: BLE001
            return []

    return store.run_due_revisits(
        portfolio_key=portfolio_key,
        limit=max(1, min(int(limit or 20), 50)),
        mark_fn=mark_fn,
        awareness_fn=awareness_fn,
        observations_fn=observations_fn,
    )


@v1_router.get("/market/opportunities", tags=["programs"])
def get_market_opportunities(
    laboratory_id: str = "india_equity_learner",
    status: str | None = None,
    kind: str | None = None,
    symbol: str | None = None,
    limit: int = 40,
) -> dict:
    """LI.3b — forgotten opportunities (lab-scoped; not trade win-rate)."""
    from atlas.config import get_config
    from atlas.investment.opportunity_tracker import (
        list_opportunities,
        opportunity_counts,
    )

    data_dir = str(get_config().paths.data)
    items = list_opportunities(
        data_dir,
        laboratory_id=laboratory_id,
        status=status,
        kind=kind,
        symbol=symbol,
        limit=max(1, min(200, int(limit))),
    )
    return {
        "ok": True,
        "items": items,
        "count": len(items),
        "counts": opportunity_counts(data_dir, laboratory_id=laboratory_id),
        "version": "li.3b.opportunity_tracker",
    }


@v1_router.post("/market/opportunities", tags=["programs"])
def post_market_opportunity(body: dict | None = None) -> dict:
    """LI.3b — record ignored/missed/rejected/deferred opportunity (lab-scoped)."""
    from atlas.config import get_config
    from atlas.investment.opportunity_tracker import record_opportunity

    body = body or {}
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    kind = str(body.get("kind") or "").strip()
    if not kind:
        raise HTTPException(
            status_code=400,
            detail="kind is required (ignored|missed|rejected|deferred)",
        )
    try:
        return {
            "ok": True,
            **record_opportunity(
                str(get_config().paths.data),
                laboratory_id=str(body.get("laboratory_id") or "india_equity_learner"),
                symbol=symbol,
                kind=kind,
                reason=str(body.get("reason") or ""),
                source=str(body.get("source") or "operator"),
                mark=float(body["mark"]) if body.get("mark") is not None else None,
                horizon=body.get("horizon"),
                related_decision_id=body.get("related_decision_id"),
                related_discovery_id=body.get("related_discovery_id"),
                extra=body.get("extra") if isinstance(body.get("extra"), dict) else None,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@v1_router.post("/market/opportunities/{opportunity_id}/resolve", tags=["programs"])
def post_market_opportunity_resolve(opportunity_id: str, body: dict | None = None) -> dict:
    """LI.3b — attach material-move outcome (not strategy PnL)."""
    from atlas.config import get_config
    from atlas.investment.opportunity_tracker import resolve_material_move

    body = body or {}
    if body.get("mark_now") is None:
        raise HTTPException(status_code=400, detail="mark_now is required")
    try:
        row = resolve_material_move(
            str(get_config().paths.data),
            laboratory_id=str(body.get("laboratory_id") or "india_equity_learner"),
            opportunity_id=opportunity_id,
            mark_now=float(body["mark_now"]),
            adverse=body.get("adverse") if "adverse" in body else None,
            note=str(body.get("note") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"opportunity {opportunity_id} not found")
    return {"ok": True, "opportunity": row}


@v1_router.get("/market/observations/{observation_id}", tags=["programs"])
def get_market_observation(request: Request, observation_id: str) -> dict:
    """DI.Obs — fetch one observation by id."""
    from atlas.investment.observations import OBS_VERSION

    try:
        store = _app(request).container.resolve("decision_observations")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision observations unavailable: {exc}"
        ) from exc
    row = store.get(observation_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"observation {observation_id} not found")
    return {"observation": row, "version": row.get("payload_version") or OBS_VERSION}


@v1_router.get("/market/observations", tags=["programs"])
def list_market_observations(
    request: Request,
    symbol: str | None = None,
    kind: str | None = None,
    since_hours: float = 72.0,
    limit: int = 40,
) -> dict:
    """DI.Obs — list recent observations (by symbol or global since window)."""
    from atlas.investment.observations import summarize_observation

    try:
        store = _app(request).container.resolve("decision_observations")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision observations unavailable: {exc}"
        ) from exc
    lim = max(1, min(int(limit or 40), 200))
    if symbol:
        items = store.list_symbol(
            symbol=symbol, limit=lim, kind=kind, since_hours=since_hours
        )
    else:
        items = store.list_since(since_hours=since_hours, limit=lim)
        if kind:
            items = [r for r in items if r.get("kind") == kind]
    return {
        "count": len(items),
        "items": [summarize_observation(r) for r in items],
        "symbol": symbol,
        "kind": kind,
        "since_hours": since_hours,
        "version": "di.obs.1",
    }


@v1_router.post("/market/observations", tags=["programs"])
def post_market_observation(request: Request, body: dict | None = None) -> dict:
    """DI.Obs — operator/manual observation (never invents facts beyond payload)."""
    try:
        store = _app(request).container.resolve("decision_observations")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"decision observations unavailable: {exc}"
        ) from exc
    body = body or {}
    kind = str(body.get("kind") or "").strip()
    if not kind:
        raise HTTPException(status_code=400, detail="kind is required")
    try:
        result = store.record(
            kind=kind,
            symbol=str(body["symbol"]).strip() if body.get("symbol") else None,
            payload=body.get("payload") if isinstance(body.get("payload"), dict) else body,
            source=str(body.get("source") or "operator"),
            confidence=str(body.get("confidence") or "estimated"),
            ttl_hours=float(body["ttl_hours"]) if body.get("ttl_hours") is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@v1_router.post("/market/portfolio/pre-trade", tags=["programs"])
def post_market_portfolio_pre_trade(request: Request, body: dict | None = None) -> dict:
    """IIP.7 — pre-trade portfolio gate (concentration, cash, persona, score)."""
    from atlas.investment.portfolio_optimizer import optimize_candidate, pre_trade_check
    from atlas.investment.portfolios import normalize_persona

    body = body or {}
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    side = str(body.get("side") or "buy").lower()
    price = float(body.get("price") or 0)
    quantity = body.get("quantity")
    persona = normalize_persona(body.get("persona") if isinstance(body.get("persona"), dict) else {})
    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {
        "cash": float(body.get("cash") or persona.get("capital") or 10000),
        "equity": float(body.get("equity") or body.get("cash") or persona.get("capital") or 10000),
        "positions": body.get("positions") or [],
    }
    score = body.get("investment_score") if isinstance(body.get("investment_score"), dict) else {}
    research_gate = body.get("research_gate") if isinstance(body.get("research_gate"), dict) else {}

    # Optionally pull live score + research gate
    if body.get("use_live_research", True):
        try:
            research = _app(request).container.resolve("investment_research")
            aw = research.awareness(
                symbol,
                program_id=str(body.get("program_id") or "market_intelligence"),
            )
            if not score:
                score = aw.get("investment_score") or {}
            if not research_gate:
                research_gate = research.gate_buy(
                    symbol,
                    program_id=str(body.get("program_id") or "market_intelligence"),
                )
            val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
            if body.get("mos_pct") is None and val.get("margin_of_safety_pct") is not None:
                body = {**body, "mos_pct": val.get("margin_of_safety_pct")}
        except Exception:  # noqa: BLE001
            pass

    cfg = {
        "max_names": body.get("max_names"),
        "max_name_pct": body.get("max_name_pct"),
        "sector_cap_pct": body.get("sector_cap_pct"),
        "min_cash_pct": body.get("min_cash_pct"),
        "min_investment_confidence": body.get("min_investment_confidence") or "low",
        "mos_pct": body.get("mos_pct"),
    }
    if quantity is None or float(quantity or 0) <= 0:
        if price <= 0:
            raise HTTPException(status_code=400, detail="price required to size")
        return optimize_candidate(
            symbol=symbol,
            price=price,
            snapshot=snapshot,
            persona=persona,
            investment_score=score,
            research_gate=research_gate or {"allowed": True},
            mos_pct=body.get("mos_pct"),
            horizon=str(body.get("horizon") or persona.get("time_horizon") or "long_term"),
            asset_class=str(body.get("asset_class") or "cash_equity"),
            cfg=cfg,
        )
    return pre_trade_check(
        side=side,
        symbol=symbol,
        quantity=float(quantity),
        price=price,
        snapshot=snapshot,
        persona=persona,
        investment_score=score,
        research_gate=research_gate or {"allowed": True},
        asset_class=str(body.get("asset_class") or "cash_equity"),
        require_research=bool(body.get("require_research", True)),
        require_score=bool(body.get("require_score", True)),
        cfg=cfg,
    )


@v1_router.get("/market/thesis-tracker", tags=["programs"])
def get_market_thesis_tracker(
    program_id: str = "market_intelligence",
    status: str | None = None,
    limit: int = 40,
) -> dict:
    """IIP.8 — list Thesis Trackers + durable priors."""
    from atlas.config import get_config
    from atlas.investment.thesis_tracker import list_trackers

    return list_trackers(
        str(get_config().paths.data),
        program_id=program_id,
        status=status,
        limit=limit,
    )


@v1_router.get("/market/thesis-tracker/priors", tags=["programs"])
def get_market_thesis_priors(program_id: str = "market_intelligence") -> dict:
    """IIP.8 — durable discovery/scoring priors from closed outcomes."""
    from atlas.config import get_config
    from atlas.investment.thesis_tracker import load_priors, priors_view

    return priors_view(load_priors(str(get_config().paths.data), program_id))


@v1_router.get("/market/thesis-tracker/{symbol}", tags=["programs"])
def get_market_thesis_tracker_symbol(
    symbol: str,
    program_id: str = "market_intelligence",
) -> dict:
    """IIP.8 — single-symbol Thesis Tracker."""
    from atlas.config import get_config
    from atlas.investment.thesis_tracker import load_tracker, normalize_symbol

    data_dir = str(get_config().paths.data)
    tr = load_tracker(data_dir, symbol, program_id)
    if not tr:
        return {
            "symbol": normalize_symbol(symbol),
            "status": "absent",
            "tracker": None,
            "note": "No tracker yet — opens on sim buy / observed fill.",
        }
    return {"symbol": tr.get("symbol"), "status": tr.get("status"), "tracker": tr}


@v1_router.post("/market/thesis-tracker/{symbol}/open", tags=["programs"])
def post_market_thesis_tracker_open(
    request: Request,
    symbol: str,
    body: dict | None = None,
) -> dict:
    """IIP.8 — open/refresh tracker (operator or from live awareness)."""
    from atlas.config import get_config
    from atlas.investment import thesis_tracker as tt

    body = body or {}
    data_dir = str(get_config().paths.data)
    program_id = str(body.get("program_id") or "market_intelligence")
    if body.get("from_awareness", True):
        try:
            research = _app(request).container.resolve("investment_research")
            aw = research.awareness(symbol, program_id=program_id)
            tracker = tt.tracker_from_awareness(
                data_dir,
                aw,
                program_id=program_id,
                decision=body.get("decision"),
            )
            return {"ok": True, "tracker": tracker, "source": "awareness"}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"awareness open failed: {exc}") from exc
    tracker = tt.open_tracker(
        data_dir,
        symbol,
        program_id=program_id,
        hypothesis=str(body.get("hypothesis") or ""),
        theme_links=list(body.get("theme_links") or []),
        assumptions=body.get("assumptions"),
        horizon=str(body.get("horizon") or "long_term"),
        research_confidence=body.get("research_confidence"),
        investment_confidence=body.get("investment_confidence"),
        decision=str(body.get("decision") or "watch"),
        size_note=str(body.get("size_note") or ""),
        force=bool(body.get("force", True)),
    )
    return {"ok": True, "tracker": tracker, "source": "manual"}


@v1_router.post("/market/thesis-tracker/{symbol}/revisit", tags=["programs"])
def post_market_thesis_tracker_revisit(symbol: str, body: dict | None = None) -> dict:
    """IIP.8 — assumption check vs new evidence."""
    from atlas.config import get_config
    from atlas.investment.thesis_tracker import revisit_tracker

    body = body or {}
    tracker = revisit_tracker(
        str(get_config().paths.data),
        symbol,
        program_id=str(body.get("program_id") or "market_intelligence"),
        assumption_updates=body.get("assumption_updates"),
        note=str(body.get("note") or ""),
        evidence_note=str(body.get("evidence_note") or ""),
    )
    return {"ok": True, "tracker": tracker}


@v1_router.post("/market/thesis-tracker/{symbol}/close", tags=["programs"])
def post_market_thesis_tracker_close(symbol: str, body: dict | None = None) -> dict:
    """IIP.8 — close with attribution → update priors."""
    from atlas.config import get_config
    from atlas.investment.thesis_tracker import close_with_attribution

    body = body or {}
    result = str(body.get("result") or "").lower()
    if result not in {"held", "weakened", "falsified"}:
        raise HTTPException(
            status_code=400,
            detail="result must be held | weakened | falsified",
        )
    out = close_with_attribution(
        str(get_config().paths.data),
        symbol,
        program_id=str(body.get("program_id") or "market_intelligence"),
        result=result,
        pnl=body.get("pnl"),
        note=str(body.get("note") or ""),
        trade=body.get("trade") if isinstance(body.get("trade"), dict) else {},
    )
    return {"ok": True, **out}


@v1_router.get("/market/themes", tags=["programs"])
def list_market_themes() -> dict:
    """IIP.2 — macro theme seeds (hypothesis → beneficiaries)."""
    from atlas.investment.themes import themes_view

    return themes_view()


@v1_router.get("/market/discovery", tags=["programs"])
def get_market_discovery(request: Request) -> dict:
    """IIP.2 — latest opportunity discovery run."""
    from atlas.config import get_config
    from atlas.investment.discovery import load_latest_discovery

    return load_latest_discovery(str(get_config().paths.data))


@v1_router.post("/market/discovery/run", tags=["programs"])
def run_market_discovery_now(request: Request, body: dict | None = None) -> dict:
    """Operator-triggered discovery tick (bounded scan)."""
    from atlas.config import get_config
    from atlas.workers.base import TickContext
    from atlas.workers.opportunity_discovery import OpportunityDiscoveryWorker

    body = body or {}
    try:
        reader = _app(request).container.resolve("market_reader")
    except Exception:
        reader = None
    worker = OpportunityDiscoveryWorker(
        market_reader=reader,
        data_dir=str(get_config().paths.data),
    )
    cfg = {
        "provider": str(body.get("provider") or "yahoo"),
        "max_interesting": int(body.get("max_interesting") or 40),
        "max_enqueue_research": int(body.get("max_enqueue_research") or 10),
        "max_scan": int(body.get("max_scan") or 120),
        "include_themes": body.get("include_themes", True),
    }
    if body.get("universes"):
        cfg["universes"] = body["universes"]
    result = worker.do_tick(
        TickContext(
            worker_id="api-discovery",
            mission_id="api-discovery",
            config=cfg,
            state={},
            inputs=[],
            config_version=1,
        )
    )
    latest = worker.latest()
    return {"note": result.note, "state": result.state, "discovery": latest}


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
    """IL.10 — list virtual portfolios (persona + mission binding).

    Registry is disk-backed; on empty/stale process we rebind from mission configs
    and refresh persona.capital from live sim cash so deposits survive restarts.
    """
    from atlas.investment import portfolios as vp

    try:
        _rehydrate_virtual_portfolios(request)
    except Exception:  # noqa: BLE001
        pass
    rows = vp.list_portfolios(program_id=program_id)
    return {"portfolios": rows, "count": len(rows), "version": "il.10"}


@v1_router.get("/market/labs/ledgers", tags=["programs"])
def list_lab_ledgers(request: Request) -> dict:
    """OI-LEDGER-UI0 — portfolio + ledger statement for all known labs."""
    from atlas.investment import portfolios as vp
    from atlas.investment.laboratory import MAIL_LAB_TITLES, MAIL_SNAPSHOT_LABS

    try:
        _rehydrate_virtual_portfolios(request)
    except Exception:  # noqa: BLE001
        pass
    keys = list(MAIL_SNAPSHOT_LABS)
    for row in vp.list_portfolios() or []:
        if isinstance(row, dict) and row.get("portfolio_key"):
            k = str(row["portfolio_key"])
            if k not in keys:
                keys.append(k)
    labs: list[dict] = []
    for key in keys:
        try:
            doc = portfolio_ledger_statement(key, request)
            row = {"portfolio_key": key, **doc}
            row["title"] = MAIL_LAB_TITLES.get(key) or row.get("label") or key
            labs.append(row)
        except HTTPException as exc:
            labs.append(
                {
                    "portfolio_key": key,
                    "title": MAIL_LAB_TITLES.get(key) or key,
                    "error": getattr(exc, "detail", str(exc)),
                }
            )
        except Exception as exc:  # noqa: BLE001
            labs.append(
                {
                    "portfolio_key": key,
                    "title": MAIL_LAB_TITLES.get(key) or key,
                    "error": str(exc),
                }
            )
    return {"labs": labs, "count": len(labs), "version": "jdg.ledger_ui.v1"}


@v1_router.post("/market/bars/bootstrap", tags=["programs"])
def post_bars_bootstrap(
    request: Request,
    max_symbols: int = 8,
    range: str = "10y",
) -> dict:
    """OI-HIST-BARS — kick a budgeted historical bootstrap batch now."""
    from atlas.config import get_config
    from atlas.investment.historical_bars import (
        bootstrap_batch,
        default_priority_symbols,
        load_progress,
    )

    data_dir = str(get_config().paths.data)
    try:
        mr = _app(request).container.resolve("market_reader")
        yahoo = (getattr(mr, "_adapters", None) or {}).get("yahoo")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"market_reader unavailable: {exc}") from exc
    if yahoo is None:
        raise HTTPException(status_code=503, detail="yahoo adapter unavailable")

    def _fetch(symbol: str, **kwargs):
        return list(yahoo.fetch_bars(symbol, **kwargs) or [])

    out = bootstrap_batch(
        data_dir,
        default_priority_symbols(data_dir, limit=80),
        fetch_bars=_fetch,
        max_n=max(1, min(20, int(max_symbols))),
        range_=str(range or "10y"),
    )
    return {"bootstrap": out, "progress": load_progress(data_dir), "version": "jdg.hist_bars.v1"}


def _rehydrate_virtual_portfolios(request: Request) -> int:
    """Rebuild / refresh registry from *active* paper books + sim cash.

    Never invents ``portfolio_key=default`` from null keys, and never resurrects
    archived template missions (that is how the stale ₹1,00,000 book appeared).
    """
    from atlas.investment import portfolios as vp

    live_statuses = {"active", "waiting", "paused", "draft"}
    rebound = 0
    try:
        missions = _missions(request).list_missions(limit=200)
        configuration = _configuration(request)
    except Exception:  # noqa: BLE001
        return 0
    try:
        portfolio_svc = _app(request).container.resolve("portfolio")
    except Exception:  # noqa: BLE001
        portfolio_svc = None

    active_keys: set[str] = set()
    for mission in missions:
        mid = str(getattr(mission, "id", None) or "")
        if not mid:
            continue
        status = str(getattr(mission, "status", "") or "").strip().lower()
        if status and status not in live_statuses:
            continue
        try:
            cfg_row = configuration.get_active(mid)
        except Exception:  # noqa: BLE001
            continue
        if cfg_row is None:
            continue
        doc = getattr(cfg_row, "document", None)
        if not isinstance(doc, dict):
            try:
                d = cfg_row.to_dict() if hasattr(cfg_row, "to_dict") else {}
                doc = d.get("document") if isinstance(d, dict) else {}
            except Exception:  # noqa: BLE001
                doc = {}
        if not isinstance(doc, dict):
            continue
        schema = str(getattr(cfg_row, "schema_type", None) or doc.get("schema_type") or "")
        pkey = str(doc.get("portfolio_key") or "").strip()
        # Explicit book key required — null/blank must NOT become "default".
        if not pkey:
            continue
        paperish = (
            schema in ("paper_trading", "decision_simulation")
            or "paper" in schema
            or doc.get("starting_cash") is not None
            or isinstance(doc.get("persona"), dict)
        )
        if not paperish:
            continue
        try:
            row = vp.ensure_from_config(doc, mission_id=mid)
            rebound += 1
            active_keys.add(str(row.get("portfolio_key") or pkey))
        except Exception:  # noqa: BLE001
            continue
        if portfolio_svc is None:
            continue
        try:
            book = portfolio_svc.ensure_portfolio(
                mission_id=mid,
                name=pkey,
                starting_cash=float((row.get("persona") or {}).get("capital") or 0),
            )
            live = float(book.get("cash") if book.get("cash") is not None else 0)
            vp.sync_live_cash(pkey, live, mission_id=mid)
        except Exception:  # noqa: BLE001
            continue

    # Drop stale template books (e.g. archived "start trade" → default/100k).
    try:
        for row in vp.list_portfolios():
            key = str(row.get("portfolio_key") or "").strip()
            if not key or key in active_keys:
                continue
            mid = str(row.get("mission_id") or "").strip()
            if not mid:
                if key == "default":
                    vp.clear(key)
                continue
            try:
                m = _missions(request).get_mission(mid, journal_limit=0)
                st = str(
                    ((m or {}).get("mission") or {}).get("status")
                    or getattr((m or {}).get("mission"), "status", "")
                    or ""
                ).strip().lower()
            except Exception:  # noqa: BLE001
                st = ""
            if st in {"archived", "completed"} or (key == "default" and st not in live_statuses):
                vp.clear(key)
    except Exception:  # noqa: BLE001
        pass
    return rebound

@v1_router.post("/market/portfolios/{portfolio_ref}/repair-lab", tags=["programs"])
def post_repair_laboratory_pack(portfolio_ref: str) -> dict:
    """PLC.E — align F&O/intraday persona + return suggested Decision Simulation config."""
    from atlas.investment import portfolios as vp

    out = vp.repair_laboratory_pack_alignment(portfolio_ref)
    if out is None:
        raise HTTPException(status_code=404, detail=f"unknown portfolio: {portfolio_ref}")
    return {"version": "plc.e", **out}


@v1_router.get("/market/portfolios/{portfolio_ref}", tags=["programs"])
def get_virtual_portfolio(portfolio_ref: str, request: Request) -> dict:
    """IL.10 — get by portfolio_key or id; attach sim snapshot when mission bound."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        try:
            _rehydrate_virtual_portfolios(request)
        except Exception:  # noqa: BLE001
            pass
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
            try:
                if snap and snap.get("cash") is not None:
                    vp.sync_live_cash(
                        str(row.get("portfolio_key") or portfolio_ref),
                        float(snap["cash"]),
                        mission_id=str(mid),
                    )
                    row = vp.get(portfolio_ref) or row
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            snap = None
    return {"portfolio": row, "snapshot": snap, "version": "il.10"}


@v1_router.get("/market/portfolios/{portfolio_ref}/ledger", tags=["programs"])
def portfolio_ledger_statement(portfolio_ref: str, request: Request) -> dict:
    """IL.7 — fee/TDS rollup statement for a virtual portfolio book."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        try:
            _rehydrate_virtual_portfolios(request)
        except Exception:  # noqa: BLE001
            pass
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
    try:
        live = float(ensured.get("cash") if ensured.get("cash") is not None else 0)
        vp.sync_live_cash(
            str(row.get("portfolio_key") or portfolio_ref),
            live,
            mission_id=str(mid),
        )
        row = vp.get(portfolio_ref) or row
    except Exception:  # noqa: BLE001
        pass
    stmt = ledger.statement(
        ensured["id"],
        broker_profile=str(row.get("broker_profile") or "") or None,
    )
    # Mark holdings to latest daily market close. Without this, snapshot() uses
    # average cost and every new position misleadingly shows zero P&L.
    marks: dict[str, float] = {}
    previous_closes: dict[str, float] = {}
    try:
        market_reader = _app(request).container.resolve("market_reader")
        for pos in stmt.get("positions") or []:
            symbol = str(pos.get("symbol") or "").strip()
            if not symbol:
                continue
            out = market_reader.bars_for(symbol, provider="yahoo", limit=2)
            bars = list((out or {}).get("bars") or [])
            if bars and bars[-1].get("close") is not None:
                marks[symbol] = float(bars[-1]["close"])
            if len(bars) > 1 and bars[-2].get("close") is not None:
                previous_closes[symbol] = float(bars[-2]["close"])
        if marks:
            stmt = ledger.statement(
                ensured["id"],
                prices=marks,
                broker_profile=str(row.get("broker_profile") or "") or None,
            )
    except Exception:  # noqa: BLE001
        pass
    # OI-STAB0: ledger/snapshot now labels mixed marks; keep fallback for empty books
    stmt["valuation_basis"] = stmt.get("valuation_basis") or (
        "latest daily market bars" if marks else "average cost (market marks unavailable)"
    )
    stmt["marks"] = marks
    stmt["previous_closes"] = previous_closes
    try:
        from datetime import datetime as _dt_tag, timezone as _tz_tag, timedelta as _td_tag

        from atlas.investment.trading_kpis import tag_trades_ist_day

        _ist_day = _dt_tag.now(_tz_tag(_td_tag(hours=5, minutes=30))).date().isoformat()
        stmt["recent_trades"] = tag_trades_ist_day(
            stmt.get("recent_trades") or [], ist_date=_ist_day
        )
        stmt["fills_today"] = sum(
            1 for t in stmt["recent_trades"] if isinstance(t, dict) and t.get("ist_day_match")
        )
        stmt["ist_date"] = _ist_day
    except Exception:  # noqa: BLE001
        pass
    deposits = float(stmt.get("deposited") or 0)
    withdrawals = float(stmt.get("withdrawn") or 0) + float(
        stmt.get("withdrawal_tds") or 0
    )
    net_capital = float(stmt.get("starting_cash") or 0) + deposits - withdrawals
    stmt["net_contributed_capital"] = net_capital
    stmt["total_pnl"] = float(stmt.get("equity") or 0) - net_capital
    stmt["total_return_pct"] = (
        100.0 * stmt["total_pnl"] / net_capital if net_capital > 0 else None
    )
    stmt["day_pnl"] = None
    stmt["day_return_pct"] = None
    if marks and previous_closes:
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td

            today_ist = _dt.now(_tz(_td(hours=5, minutes=30))).date()
            day_trades: list[dict] = []
            for trade in stmt.get("recent_trades") or []:
                raw = trade.get("created_at")
                if raw is None:
                    continue
                created = raw if isinstance(raw, _dt) else _dt.fromisoformat(
                    str(raw).replace("Z", "+00:00")
                )
                if created.tzinfo is None:
                    created = created.replace(tzinfo=_tz.utc)
                if created.astimezone(_tz(_td(hours=5, minutes=30))).date() == today_ist:
                    day_trades.append(trade)
            current_qty = {
                str(p.get("symbol")): float(p.get("quantity") or 0)
                for p in stmt.get("positions") or []
                if p.get("symbol")
            }
            start_qty = dict(current_qty)
            for trade in day_trades:
                symbol = str(trade.get("symbol") or "")
                qty = float(trade.get("quantity") or 0)
                if str(trade.get("side") or "").lower() == "buy":
                    start_qty[symbol] = start_qty.get(symbol, 0) - qty
                elif str(trade.get("side") or "").lower() == "sell":
                    start_qty[symbol] = start_qty.get(symbol, 0) + qty
            day_pnl = sum(
                qty * (marks[symbol] - previous_closes[symbol])
                for symbol, qty in start_qty.items()
                if symbol in marks and symbol in previous_closes
            )
            for trade in day_trades:
                symbol = str(trade.get("symbol") or "")
                if symbol not in marks:
                    continue
                qty = float(trade.get("quantity") or 0)
                price = float(trade.get("price") or 0)
                fee = float(trade.get("fee") or 0)
                if str(trade.get("side") or "").lower() == "buy":
                    day_pnl += qty * (marks[symbol] - price) - fee
                elif (
                    str(trade.get("side") or "").lower() == "sell"
                    and symbol in previous_closes
                ):
                    day_pnl += qty * (price - previous_closes[symbol]) - fee
            stmt["day_pnl"] = day_pnl
            opening_equity = float(stmt.get("equity") or 0) - day_pnl
            stmt["day_return_pct"] = (
                100.0 * day_pnl / opening_equity if opening_equity > 0 else None
            )
        except Exception:  # noqa: BLE001
            pass
    # Attach P9 explanations so the Market UI can answer "why did this buy?".
    try:
        decision = _app(request).container.resolve("decision")
        for trade in stmt.get("recent_trades") or []:
            did = trade.get("decision_id")
            if not did:
                continue
            explained = decision.get_decision(did)
            if isinstance(explained, dict):
                trade["decision"] = explained
    except Exception:  # noqa: BLE001
        pass
    # Attach today's session note so Learner can explain zero fills honestly.
    session_note = None
    try:
        from datetime import datetime, timezone, timedelta

        from atlas.config import get_config
        from atlas.investment.session_notes import format_no_fill_reasons, load_day_notes

        data_dir = str(get_config().paths.data)
        ist = timezone(timedelta(hours=5, minutes=30))
        ist_date = datetime.now(ist).date().isoformat()
        notes = load_day_notes(
            data_dir,
            portfolio_key=str(row.get("portfolio_key") or portfolio_ref),
            ist_date=ist_date,
        )
        if notes:
            session_note = {
                "ist_date": ist_date,
                "reason_counts": notes.get("reason_counts") or {},
                "no_fill_reasons": format_no_fill_reasons(notes),
                "samples": list(notes.get("samples") or [])[:8],
            }
    except Exception:  # noqa: BLE001
        session_note = None
    # Operator KPI scorecard (playbook §4) — attach + persist for strategy review.
    kpis = None
    try:
        from atlas.config import get_config
        from atlas.investment import watchlists as wl
        from atlas.investment.trading_kpis import (
            build_trading_kpis,
            save_day_kpis,
        )

        data_dir = str(get_config().paths.data)
        from datetime import datetime, timezone, timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        ist_date = datetime.now(ist).date().isoformat()
        plan = None
        try:
            snap = wl.latest("market_intelligence")
            if isinstance(snap, dict):
                plan = (snap.get("extra") or {}).get("daily_plan") or snap.get(
                    "daily_plan"
                )
        except Exception:  # noqa: BLE001
            plan = None
        kpis = build_trading_kpis(
            portfolio=stmt,
            plan=plan if isinstance(plan, dict) else None,
            session_note=session_note,
            ist_date=ist_date,
        )
        stmt["kpis"] = kpis
        save_day_kpis(
            data_dir,
            portfolio_key=str(row.get("portfolio_key") or portfolio_ref),
            ist_date=ist_date,
            kpis=kpis,
        )
    except Exception:  # noqa: BLE001
        kpis = None
    return {
        "portfolio": row,
        "statement": stmt,
        "session_note": session_note,
        "kpis": kpis,
        "version": "il.7",
    }

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
    candidates: list[str] = []
    for c in (
        body.mission_id,
        row.get("mission_id"),
        row.get("ledger_mission_id"),
    ):
        cs = str(c or "").strip()
        if cs and cs not in candidates:
            candidates.append(cs)
    withdrawals: list[dict] = []
    last_err: Exception | None = None
    profile = body.broker_profile or row.get("broker_profile") or "zerodha"
    for cand in candidates:
        try:
            ensured = portfolio_svc.ensure_portfolio(
                mission_id=cand,
                name=row.get("portfolio_key") or "default",
                starting_cash=float((row.get("persona") or {}).get("capital") or 0),
            )
            piece = ledger.withdraw(
                ensured["id"],
                amount=body.amount,
                broker_profile=profile,
                tds_pct=body.tds_pct,
                note=body.note or "operator withdrawal",
                mission_id=cand,
            )
            withdrawals.append({"mission_id": cand, **(piece if isinstance(piece, dict) else {})})
            last_err = None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    if not withdrawals:
        raise HTTPException(status_code=400, detail=str(last_err or "withdrawal failed"))
    out = withdrawals[0]
    for w in withdrawals:
        if w.get("mission_id") == (row.get("mission_id") or mid):
            out = w
            break
    # Keep virtual-book persona.capital aligned with ledger cash (UI label).
    try:
        person = dict(row.get("persona") or {})
        cash_after = float((out.get("movement") or {}).get("cash_after") or 0)
        if cash_after <= 0:
            for w in withdrawals:
                ca = float((w.get("movement") or {}).get("cash_after") or 0)
                if ca > cash_after:
                    cash_after = ca
        if cash_after >= 0 and (out.get("movement") or {}).get("cash_after") is not None:
            person["capital"] = float((out.get("movement") or {}).get("cash_after"))
        elif cash_after > 0:
            person["capital"] = cash_after
        else:
            person["capital"] = max(0.0, float(person.get("capital") or 0) - float(body.amount))
        vp.register(
            label=str(row.get("label") or row.get("portfolio_key")),
            portfolio_key=str(row.get("portfolio_key")),
            persona=person,
            program_id=str(row.get("program_id") or "market_intelligence"),
            universe=str(row.get("universe") or "NIFTY50"),
            broker_profile=str(row.get("broker_profile") or "zerodha"),
            asset_class=str(row.get("asset_class") or "cash_equity"),
            instrument_pack=row.get("instrument_pack"),
            mission_id=row.get("mission_id"),
            ledger_mission_id=row.get("ledger_mission_id"),
            extra=row.get("extra") if isinstance(row.get("extra"), dict) else None,
        )
        row = vp.get(portfolio_ref) or row
    except Exception:  # noqa: BLE001
        pass
    return {
        "portfolio": row,
        "withdrawal": out,
        "withdrawals": withdrawals,
        "version": "il.7",
    }

@v1_router.post("/market/portfolios/{portfolio_ref}/deposit", tags=["programs"])
def deposit_to_portfolio(
    portfolio_ref: str,
    request: Request,
    body: DepositPortfolioRequest,
) -> dict:
    """IL.7 — simulate depositing cash into a virtual book (add capital)."""
    from atlas.investment import portfolios as vp

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown portfolio: {portfolio_ref}")
    mid = body.mission_id or row.get("mission_id") or row.get("ledger_mission_id")
    if not mid:
        raise HTTPException(
            status_code=400,
            detail="portfolio needs a bound mission before deposits "
            "(start India learner / trade simulation first)",
        )
    try:
        ledger = _app(request).container.resolve("portfolio_ledger")
        portfolio_svc = _app(request).container.resolve("portfolio")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    candidates: list[str] = []
    for c in (
        body.mission_id,
        row.get("mission_id"),
        row.get("ledger_mission_id"),
    ):
        cs = str(c or "").strip()
        if cs and cs not in candidates:
            candidates.append(cs)
    deposits: list[dict] = []
    last_err: Exception | None = None
    # Credit every bound mission book with this key so sim + ledger stay aligned.
    for cand in candidates:
        try:
            ensured = portfolio_svc.ensure_portfolio(
                mission_id=cand,
                name=row.get("portfolio_key") or "default",
                starting_cash=float((row.get("persona") or {}).get("capital") or 0),
            )
            piece = ledger.deposit(
                ensured["id"],
                amount=body.amount,
                note=body.note or "operator deposit",
                mission_id=cand,
            )
            deposits.append({"mission_id": cand, **(piece if isinstance(piece, dict) else {})})
            last_err = None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    if not deposits:
        raise HTTPException(status_code=400, detail=str(last_err or "deposit failed"))
    out = deposits[0]
    # Prefer the primary sim mission’s movement for the payload.
    for d in deposits:
        if d.get("mission_id") == (row.get("mission_id") or mid):
            out = d
            break
    # Keep virtual-book persona.capital in sync for UI (ledger cash is truth).
    try:
        person = dict(row.get("persona") or {})
        cash_after = float((out.get("movement") or {}).get("cash_after") or 0)
        if cash_after <= 0:
            # Reconstruct from primary movement
            for d in deposits:
                ca = float((d.get("movement") or {}).get("cash_after") or 0)
                if ca > cash_after:
                    cash_after = ca
        if cash_after > 0:
            person["capital"] = cash_after
        else:
            person["capital"] = float(person.get("capital") or 0) + float(body.amount)
        vp.register(
            label=str(row.get("label") or row.get("portfolio_key")),
            portfolio_key=str(row.get("portfolio_key")),
            persona=person,
            program_id=str(row.get("program_id") or "market_intelligence"),
            universe=str(row.get("universe") or "NIFTY50"),
            broker_profile=str(row.get("broker_profile") or "zerodha"),
            asset_class=str(row.get("asset_class") or "cash_equity"),
            instrument_pack=row.get("instrument_pack"),
            mission_id=row.get("mission_id"),
            ledger_mission_id=row.get("ledger_mission_id"),
            extra=row.get("extra") if isinstance(row.get("extra"), dict) else None,
        )
        row = vp.get(portfolio_ref) or row
    except Exception:  # noqa: BLE001
        pass
    return {
        "portfolio": row,
        "deposit": out,
        "deposits": deposits,
        "version": "il.7",
    }


@v1_router.post("/market/portfolios/{portfolio_ref}/resume", tags=["programs"])
@v1_router.post("/market/laboratories/{portfolio_ref}/resume", tags=["programs"])
def resume_laboratory_after_outage(portfolio_ref: str, request: Request) -> dict:
    """LI.1b — re-bind durable ledger + mark prices after power/internet outage.

    Does **not** invent fills for the dark window. ``portfolio_ref`` is the
    laboratory_id (1:1 with portfolio_key).
    """
    from atlas.investment import portfolios as vp
    from atlas.investment.laboratory_resume import resume_laboratory_ledger
    from atlas.config import get_config

    row = vp.get(portfolio_ref) or vp.get_by_id(portfolio_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown laboratory: {portfolio_ref}")
    mid = row.get("mission_id") or row.get("ledger_mission_id")
    if not mid:
        raise HTTPException(
            status_code=400,
            detail="laboratory needs a bound mission before resume",
        )
    try:
        portfolio_svc = _app(request).container.resolve("portfolio")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    market_reader = None
    try:
        market_reader = _app(request).container.resolve("market_reader")
    except Exception:  # noqa: BLE001
        market_reader = None
    data_dir = None
    try:
        data_dir = str(get_config().paths.data)
    except Exception:  # noqa: BLE001
        data_dir = None
    person = row.get("persona") if isinstance(row.get("persona"), dict) else {}
    report = resume_laboratory_ledger(
        portfolio_service=portfolio_svc,
        market_reader=market_reader,
        mission_id=str(mid),
        laboratory_id=str(row.get("laboratory_id") or row.get("portfolio_key")),
        starting_cash=float(person.get("capital") or 0),
        data_dir=data_dir,
        personality=person,
    )
    return {"laboratory": row, "resume": report, "version": "li.1b"}


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


def _reasoning(request: Request):
    try:
        return _app(request).container.resolve("reasoning")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"reasoning unavailable: {exc}"
        ) from exc


@v1_router.get("/reasoning/identity", tags=["reasoning"])
def reasoning_identity(request: Request) -> dict:
    """OI-SELF0 — current Atlas identity document."""
    rs = _reasoning(request)
    identity = rs.identity()
    if identity is None:
        raise HTTPException(status_code=404, detail="identity_not_seeded")
    return {"identity": identity, "version": getattr(rs, "VERSION", "self0")}


@v1_router.get("/activity/today", tags=["activity"])
def activity_today(request: Request, limit: int = 200) -> dict:
    """OI-STAB0 P0.0 — today's work journal (IST)."""
    try:
        journal = _app(request).container.resolve("activity_journal")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"activity journal unavailable: {exc}") from exc
    if journal is None:
        raise HTTPException(status_code=503, detail="activity journal not bound")
    brief = journal.format_day_brief()
    events = journal.for_day(limit=limit)
    return {
        **brief,
        "events": [
            {
                "id": str(e.get("id")),
                "ts": e.get("ts").isoformat() if hasattr(e.get("ts"), "isoformat") else e.get("ts"),
                "domain": e.get("domain"),
                "worker": e.get("worker"),
                "action": e.get("action"),
                "target": e.get("target"),
                "result": e.get("result"),
                "summary": e.get("summary"),
            }
            for e in events
        ],
    }


@v1_router.get("/market-data/status", tags=["market"])
def market_data_status(request: Request) -> dict:
    """OI-STAB0 P0.1 — MarketDataService choke status."""
    try:
        mds = _app(request).container.resolve("market_data_service")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if mds is None:
        raise HTTPException(status_code=503, detail="market_data_service not bound")
    return mds.status()


@v1_router.get("/market/session-readiness", tags=["market"])
def market_session_readiness(
    request: Request,
    day: str | None = None,
    laboratory_id: str = "india_equity_learner",
) -> dict:
    """OI-STAB0 D4 — clean equity session gate card (observe+explain)."""
    from atlas.investment.session_readiness import evaluate_equity_session

    try:
        from atlas.config import get_config

        data_dir = get_config().paths.data
    except Exception:  # noqa: BLE001
        data_dir = None
    app = _app(request)
    c = app.container

    def _opt(name: str):
        try:
            return c.resolve(name)
        except Exception:  # noqa: BLE001
            return None

    return evaluate_equity_session(
        data_dir,
        day=day,
        laboratory_id=laboratory_id or "india_equity_learner",
        market_data=_opt("market_data_service"),
        host_guard=_opt("host_guard"),
        budget=_opt("budget_controller"),
        reasoning=_opt("reasoning"),
    )


@v1_router.post("/reasoning/reflect", tags=["reasoning"])
def reasoning_reflect(
    request: Request,
    laboratory_id: str | None = None,
    allow_llm_narrative: bool = True,
) -> dict:
    """OI-SELF-REFLECT — run nightly Belief Core reflection (advice-only)."""
    from atlas.reasoning.reflection import run_nightly_reflection

    return run_nightly_reflection(
        _reasoning(request),
        laboratory_id=laboratory_id,
        allow_llm_narrative=allow_llm_narrative,
    )


@v1_router.post("/reasoning/living-rag", tags=["reasoning"])
def reasoning_living_rag(request: Request, q: str, limit: int = 8) -> dict:
    """OI-SELF-ID — preview Living RAG bundle for a query (no model call)."""
    if not (q or "").strip():
        raise HTTPException(status_code=400, detail="q required")
    from atlas.reasoning.retrieval import build_living_rag_bundle

    eos = None
    knowledge = None
    memory = None
    try:
        eos = _app(request).container.resolve("experience_os")
    except Exception:  # noqa: BLE001
        pass
    try:
        knowledge = _app(request).container.resolve("knowledge")
    except Exception:  # noqa: BLE001
        pass
    try:
        memory = _app(request).container.resolve("memory")
    except Exception:  # noqa: BLE001
        pass
    return build_living_rag_bundle(
        _reasoning(request),
        q,
        experience_os=eos,
        knowledge=knowledge,
        memory=memory,
        belief_limit=limit,
    )


@v1_router.post("/reasoning/seed", tags=["reasoning"])
def reasoning_seed(request: Request) -> dict:
    """OI-SELF-SEED — idempotent identity + operator worldview seed."""
    return _reasoning(request).ensure_seeded()


@v1_router.get("/beliefs", tags=["reasoning"])
def list_beliefs(
    request: Request,
    domain: str | None = None,
    status: str | None = None,
    theme: str | None = None,
    limit: int = 50,
) -> dict:
    rs = _reasoning(request)
    rows = rs.list_beliefs(
        domain=domain, status=status, theme=theme, limit=limit
    )
    return {"beliefs": rows, "count": len(rows), "version": getattr(rs, "VERSION", "self0")}


@v1_router.post("/beliefs/consult", tags=["reasoning"])
def consult_beliefs(request: Request, body: BeliefConsultRequest) -> dict:
    """OI-SELF0 — consult Belief Core (increments Belief Consultations metric)."""
    return _reasoning(request).consult(
        domain=body.domain,
        theme=body.theme,
        query=body.query,
        limit=body.limit,
    )


@v1_router.get("/beliefs/why", tags=["reasoning"])
def belief_why(request: Request, q: str) -> dict:
    """Benchmark: Why do you believe X?"""
    if not (q or "").strip():
        raise HTTPException(status_code=400, detail="q required")
    out = _reasoning(request).why(q)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "not_found")
    return out


@v1_router.get("/beliefs/what-changed", tags=["reasoning"])
def belief_what_changed(request: Request, q: str) -> dict:
    """Benchmark: What changed your mind?"""
    if not (q or "").strip():
        raise HTTPException(status_code=400, detail="q required")
    out = _reasoning(request).what_changed_your_mind(q)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "not_found")
    return out


@v1_router.get("/beliefs/metrics", tags=["reasoning"])
def belief_metrics(request: Request) -> dict:
    """Belief Consultations today + Revisions/7d."""
    return _reasoning(request).metrics()


@v1_router.get("/beliefs/project/{symbol}", tags=["reasoning"])
def project_beliefs_for_symbol(
    symbol: str, request: Request, laboratory_id: str | None = None
) -> dict:
    """WSO projection read-path — Belief Core slice for a symbol (advice-only)."""
    return _reasoning(request).project_for_symbol(
        symbol, laboratory_id=laboratory_id
    )


@v1_router.get("/beliefs/{belief_id}", tags=["reasoning"])
def get_belief(belief_id: str, request: Request) -> dict:
    row = _reasoning(request).get_belief(belief_id)
    if row is None:
        raise HTTPException(status_code=404, detail="belief_not_found")
    return {"belief": row}


@v1_router.post("/beliefs/candidates", tags=["reasoning"])
def propose_belief_candidate(request: Request, body: BeliefCandidateRequest) -> dict:
    rs = _reasoning(request)
    try:
        row = rs.propose_candidate(
            statement=body.statement,
            domain=body.domain,
            confidence=body.confidence,
            themes=body.themes,
            open_questions=body.open_questions,
            evidence_summary=body.evidence_summary,
            origin=body.origin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"belief": row, "version": getattr(rs, "VERSION", "self0")}


@v1_router.post("/beliefs/{belief_id}/promote", tags=["reasoning"])
def promote_belief(
    belief_id: str, request: Request, body: BeliefPromoteRequest
) -> dict:
    rs = _reasoning(request)
    try:
        out = rs.promote(
            belief_id, reason=body.reason, confidence=body.confidence
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return out


@v1_router.post("/beliefs/{belief_id}/revise", tags=["reasoning"])
def revise_belief(belief_id: str, request: Request, body: BeliefReviseRequest) -> dict:
    rs = _reasoning(request)
    try:
        out = rs.revise(
            belief_id,
            reason=body.reason,
            evidence_summary=body.evidence_summary,
            new_statement=body.new_statement,
            new_confidence=body.new_confidence,
            new_status=body.new_status,
            open_questions=body.open_questions,
            use_llm=body.use_llm,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return out


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
    request: Request,
    mission_id: str | None = None,
    status: str | None = None,
    include_checkpoint: bool = True,
) -> dict:
    workers = _workers(request)
    if include_checkpoint and hasattr(workers, "list_workers_enriched"):
        return {
            "workers": workers.list_workers_enriched(
                mission_id=mission_id, status=status
            )
        }
    rows = workers.list_workers(mission_id=mission_id, status=status)
    return {"workers": [w.to_dict() for w in rows]}


@v1_router.get("/workers/{worker_id}", tags=["workers"])
def get_worker(worker_id: str, request: Request) -> dict:
    workers = _workers(request)
    worker = workers.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    if hasattr(workers, "enrich_worker"):
        return workers.enrich_worker(worker)
    return worker.to_dict()


@v1_router.get("/archive/status", tags=["archive"])
def archive_status(request: Request, limit: int = 50) -> dict:
    """Owner Knowledge / archive workers with done/total progress."""
    try:
        svc = _app(request).container.resolve("archive_ingest")
        return svc.status(limit=limit)
    except Exception as exc:  # noqa: BLE001
        workers = _workers(request)
        rows = [
            workers.enrich_worker(w)
            for w in workers.list_workers()
            if getattr(w, "type", None) == "owner_knowledge"
        ][:limit]
        return {
            "workers": rows,
            "count": len(rows),
            "note": f"archive service unavailable ({exc}); raw worker list",
        }


@v1_router.post("/archive/estimate", tags=["archive"])
def archive_estimate(body: ArchiveEstimateRequest, request: Request) -> dict:
    """IR-RO1 — dry-run Resource Planner estimate (no mission created)."""
    try:
        svc = _app(request).container.resolve("archive_ingest")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"archive ingest unavailable: {exc}"
        ) from exc
    try:
        return svc.estimate(
            body.path, kind=body.kind, files_per_tick=body.files_per_tick
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)


@v1_router.post("/archive/ingest", tags=["archive"])
def archive_ingest(body: ArchiveIngestRequest, request: Request) -> dict:
    """Start archive learning — parallel by default (separate mission/worker).

    Large archives may return ``mode=needs_confirmation`` with an estimate and
    ``confirmation_token``; resubmit with ``confirm=true`` to create the mission.
    """
    try:
        svc = _app(request).container.resolve("archive_ingest")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"archive ingest unavailable: {exc}"
        ) from exc
    try:
        return svc.start(
            body.path,
            kind=body.kind,
            domain=body.domain,
            parallel=body.parallel,
            title=body.title,
            note=body.note,
            period_start=body.period_start,
            period_end=body.period_end,
            files_per_tick=body.files_per_tick,
            process_now=body.process_now,
            confirm=body.confirm,
            confirmation_token=body.confirmation_token,
            force=body.force,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _mission_error(exc)


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
    if hasattr(workers, "enrich_worker"):
        return workers.enrich_worker(worker)
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
