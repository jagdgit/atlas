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
    # OI-C9 — admit mission/domain-scoped policy rules during re-rank
    policy_scope: str | None = None
    mission_id: str | None = None


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


class BridgeIngestRequest(BaseModel):
    """Unified Asset-first ingest (OI-C5) — path on the Atlas host or inline content."""

    path: str | None = None
    content: str | None = None
    filename: str | None = None
    kind: str = "document"
    domain: str = "external"
    title: str | None = None
    embed: bool = True
    extract_findings: bool = True
    drain_candidates: bool = True


class BridgeIngestResponse(BaseModel):
    asset_id: str | None = None
    asset_version: int | None = None
    document_id: str | None = None
    chunks: int = 0
    candidates: int = 0
    findings: int = 0
    deduped: bool = False
    outcome: str = "ok"
    reason: str | None = None
    asset_reused: bool = False


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


class EngineeringIngestRequest(BaseModel):
    # Ingest a repository into Engineering Intelligence (Phase B · §B.7). Exactly one of
    # path/url; optionally attach to a mission and toggle code embeddings.
    path: str | None = None
    url: str | None = None
    branch: str | None = None
    mission_id: str | None = None
    policy: str | None = None
    embed: bool | None = None
    # Operator context — "my work from 2022 to March 2025" (feeds Personal timeline; never posts).
    note: str | None = Field(
        default=None,
        description="Free-text owner note, e.g. 'my work from 2022 to March 2025'",
    )
    period_start: str | None = Field(
        default=None, description="Optional period start (YYYY or YYYY-MM)"
    )
    period_end: str | None = Field(
        default=None, description="Optional period end (YYYY or YYYY-MM or present)"
    )


class PolicyRuleRequest(BaseModel):
    # Create/upsert an operator policy rule (Phase C · §C.5, CC8). Influence, not arbitration.
    subject: str = Field(min_length=1)          # topic/source/finding the rule is about
    rule: str = Field(pattern="^(prefer|avoid|trust|distrust)$")
    scope: str = "global"
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    enabled: bool = True
    created_by: str | None = None
    provenance: dict[str, Any] | None = None


class PersonalFactRequest(BaseModel):
    # Operator adds an authoritative personal fact directly (Phase C · §C.7). Starts life verified.
    category: str = Field(pattern="^(identity|skill|timeline|professional)$")
    key: str = Field(min_length=1)
    subject: str = ""
    statement: str = ""
    value: dict[str, Any] | None = None
    actor: str | None = None


class PersonalCorrectRequest(BaseModel):
    # Operator edits (and thereby verifies) an inferred personal fact.
    statement: str | None = None
    value: dict[str, Any] | None = None
    actor: str | None = None


class PersonalLearnCvRequest(BaseModel):
    """Parse a host-path CV into inferred Personal facts."""

    path: str = Field(min_length=1)
    actor: str | None = None


class LinkedInCoachRequest(BaseModel):
    """LinkedIn improvement suggestions only — Atlas never writes to LinkedIn (P10)."""

    linkedin_path: str | None = None
    linkedin_text: str | None = None
    linkedin_url: str | None = None
    include_inferred: bool = True


class BestJobsRequest(BaseModel):
    """Rank open jobs for the Personal profile (recommend-only; never apply)."""

    feed_path: str | None = Field(
        default=None,
        description="Optional JSON job feed export (e.g. LinkedIn search export)",
    )
    limit: int = Field(default=10, ge=1, le=50)
    include_inferred_skills: bool = True


class ArchiveIngestRequest(BaseModel):
    """Start Owner Knowledge archive learning (USB / years-of-work dumps)."""

    path: str = Field(min_length=1)
    kind: str = Field(default="document", pattern="^(code|document|conversation)$")
    domain: str = "personal"
    parallel: bool = Field(
        default=True,
        description="True = new mission/worker (parallel). False = add to shared Personal Observer.",
    )
    title: str | None = None
    note: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    files_per_tick: int = Field(default=40, ge=1, le=500)
    process_now: bool = False
    confirm: bool = Field(
        default=False,
        description="Operator confirmed a prior needs_confirmation estimate (IR-RO1).",
    )
    confirmation_token: str | None = Field(
        default=None,
        description="Token from a prior needs_confirmation response.",
    )
    force: bool = Field(
        default=False,
        description="Skip confirmation thresholds (still respects Host Guard deferral).",
    )


class ArchiveEstimateRequest(BaseModel):
    """Dry-run Resource Planner estimate for an archive path (IR-RO1)."""

    path: str = Field(min_length=1)
    kind: str = Field(default="document", pattern="^(code|document|conversation)$")
    files_per_tick: int = Field(default=40, ge=1, le=500)


class KnowledgeResolveRequest(BaseModel):
    """Operator Conflict Resolver action (OI-B3)."""

    action: str = Field(pattern="^(hold|supersede|reactivate)$")
    note: str = ""
    clear_contradicting: bool = False
    actor: str | None = None


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
    mission_id: str | None = None


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
    mission_id: str | None = None
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


# --- missions / workers / templates (Phase A · §A.7) ---------------------


class CreateMissionRequest(BaseModel):
    """Operator-created mission (Q1). Created in ``draft`` unless ``activate`` is set."""

    title: str = Field(min_length=1, max_length=300)
    objective: str = ""
    scheduling_policy: str = "background"
    priority: int = Field(default=0, ge=0, le=100)
    criticality: str = "normal"
    budget: dict[str, Any] | None = None
    deadline: str | None = None
    importance: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None
    knowledge_domains: list[str] | None = None
    success_criteria: dict[str, Any] | None = None
    activate: bool = False


class InstantiateMissionRequest(BaseModel):
    """Create a Mission + config v1 (+ workers) from a built-in template (B7)."""

    template: str = Field(min_length=1)
    title: str | None = None
    objective: str = ""
    config_overrides: dict[str, Any] | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None
    scheduling_policy: str = "background"
    priority: int = Field(default=0, ge=0, le=100)
    criticality: str = "normal"
    budget: dict[str, Any] | None = None
    activate: bool = True
    autostart: bool = True


class StartProgramRequest(BaseModel):
    """Start a Program's startable members (OX.1 presets supported)."""

    activate: bool = True
    title_prefix: str | None = None
    preset: str | None = Field(
        default=None,
        description="e.g. india_equity_learner — ₹10k NIFTY auto-universe live sim",
    )
    member_overrides: dict[str, dict[str, Any]] | None = None
    capital: float | None = Field(
        default=None,
        description="OX.2 plan helper — starting cash for india_equity_learner preview",
    )
    universe: str | None = Field(
        default=None,
        description="OX.2 plan helper — e.g. NIFTY50",
    )


class PlanProgramRequest(BaseModel):
    """OX.2 — preview Program start plan without creating missions."""

    preset: str | None = Field(
        default="india_equity_learner",
        description="e.g. india_equity_learner",
    )
    title_prefix: str | None = None
    member_overrides: dict[str, dict[str, Any]] | None = None
    capital: float = 10000.0
    universe: str = "NIFTY50"
    mode: str = "auto"
    broker_profile: str = "zerodha"
    objective: str | None = None


class ProgramShareRequest(BaseModel):
    """Share resume / past-work once — Personal + Engineering consume the same job."""

    path: str = Field(min_length=1, description="Host filesystem path Atlas can read")
    kind: str | None = Field(
        default=None,
        description="code | document | conversation — inferred from path when omitted",
    )
    domain: str = "personal"
    process_now: bool = True


class ProgramChatRequest(BaseModel):
    """Program-scoped chat (share materials + operator guidance)."""

    message: str = Field(min_length=1)
    session_id: str | None = None


class CreateVirtualPortfolioRequest(BaseModel):
    """IL.10 — register a virtual portfolio (+ optional Decision Simulation mission)."""

    label: str = Field(..., min_length=1, max_length=128)
    capital: float = 10000.0
    universe: str = "NIFTY50"
    broker_profile: str = "paper_demo"
    asset_class: str = "cash_equity"
    program_id: str = "market_intelligence"
    portfolio_key: str | None = None
    persona: dict[str, Any] | None = None
    instantiate: bool = Field(
        default=True,
        description="If true, spawn a Decision Simulation mission for this book",
    )
    activate: bool = True


class ScreenerSnapshotRequest(BaseModel):
    """IL.8 — operator / API screener snapshot (no scrape)."""

    program_id: str = "market_intelligence"
    as_of: str | None = None
    note: str = ""
    # Either map symbol → fields, or list of {symbol, ...}
    symbols: dict[str, dict[str, Any]] | list[dict[str, Any]] = Field(default_factory=dict)


class InvestmentResearchStartRequest(BaseModel):
    """IRA.2b — on-demand Minimum Viable Research (or deepen)."""

    mode: str = Field(default="mvr", description="mvr | deep")
    force: bool = False
    program_id: str = "market_intelligence"
    trigger: str = "on_demand"


class FilingsSnapshotRequest(BaseModel):
    """IL.5+ — operator filing refs (no scrape; ToS-compliant source assumed)."""

    program_id: str = "market_intelligence"
    as_of: str | None = None
    note: str = ""
    # Map symbol → [filing…] / {filings:[…]} or list of {symbol, filings|title…}
    symbols: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)


class ResearchOperatorSnapshotRequest(BaseModel):
    """IRA F1 — operator research snapshot (ladder layer 1). Incremental refresh only."""

    program_id: str = "market_intelligence"
    as_of: str | None = None
    note: str = ""
    evidence_confidence: str = Field(
        default="verified",
        description="verified | estimated — propagates into valuation confidence",
    )
    auto_refresh: bool = True
    # Numeric / optional fields (never invent — omit unknowns)
    pe: float | None = None
    roe: float | None = None
    roic: float | None = None
    debt_to_equity: float | None = None
    fcf: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    revenue_cagr: float | None = None
    earnings_cagr: float | None = None
    price: float | None = None
    shares: float | None = None
    capex: float | None = None
    fcf_growth: float | None = None
    discount_rate: float | None = None
    promoter_holding: float | None = None
    sector: str | None = None


class ResearchFilingRefsRequest(BaseModel):
    """IRA.24 — operator filing refs (ladder layer 3). Titles/URLs only — no scrape."""

    program_id: str = "market_intelligence"
    as_of: str | None = None
    note: str = ""
    auto_refresh: bool = True
    filings: list[dict[str, Any]] = Field(default_factory=list)


class ResearchCriticalFlagRequest(BaseModel):
    """IRA.26b — critical evidence that can invalidate thesis / MoS path."""

    program_id: str = "market_intelligence"
    text: str = Field(..., min_length=3)
    kind: str = Field(
        default="thesis_invalidating",
        description="thesis_invalidating | valuation_irrelevant | governance | covenant | fraud",
    )
    affects: list[str] | None = None


class ResearchManagementPackRequest(BaseModel):
    """IRA F3 — management / capital-allocation checklist answers (operator)."""

    program_id: str = "market_intelligence"
    operator_note: str = ""
    evidence_level: str = Field(default="F", description="A–G; operator notes typically F")
    auto_refresh: bool = True
    # {checklist_id: answer_text} or list of {id, answer, status?}
    answers: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)


class ScreenerComputeRequest(BaseModel):
    """IL.8 — hermetic compute from bars + quality (no network)."""

    bars_by_symbol: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    quality_by_symbol: dict[str, dict[str, Any]] = Field(default_factory=dict)
    symbols: list[str] | None = None


class WithdrawPortfolioRequest(BaseModel):
    """IL.7 — simulate withdrawing cash from a virtual portfolio book."""

    amount: float = Field(..., gt=0)
    tds_pct: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Optional TDS rate; default from Broker Profile withdrawal_tds_pct",
    )
    broker_profile: str | None = None
    note: str = ""
    mission_id: str | None = None


class CreateGoalRequest(BaseModel):
    """OX.3 — create a durable Goal (objective first)."""

    title: str = Field(..., min_length=1, max_length=500)
    objective: dict[str, Any] | str | None = None
    success_criteria: dict[str, Any] | str | None = None
    program_id: str | None = None
    portfolio_key: str | None = None
    portfolio_id: str | None = None
    status: str = "active"
    metadata: dict[str, Any] | None = None


class UpdateGoalRequest(BaseModel):
    """OX.3 — patch a Goal (status, links, progress, criteria)."""

    title: str | None = None
    objective: dict[str, Any] | str | None = None
    success_criteria: dict[str, Any] | str | None = None
    status: str | None = None
    program_id: str | None = None
    portfolio_key: str | None = None
    portfolio_id: str | None = None
    progress: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class MissionActionRequest(BaseModel):
    """Reason attached to a mission lifecycle action (journaled, P9)."""

    reason: str = Field(default="", max_length=2000)


class SpawnChildMissionRequest(BaseModel):
    """IR-M1 — spawn a linked child under a parent mission."""

    title: str = Field(min_length=1, max_length=300)
    objective: str = ""
    role: str = Field(default="child", max_length=64)
    wait_on_child: bool = True
    activate: bool = True
    metadata: dict[str, Any] | None = None


class SetResearchConfidenceRequest(BaseModel):
    """IR-M3 — attach research confidence for scheduler attention."""

    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: str | None = None
    source: str = "research"


class WorkerActionRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class WorkerInputRequest(BaseModel):
    """A live operator input drained at the top of the worker's next tick (Q4)."""

    payload: dict[str, Any] = Field(default_factory=dict)


class UpdateMissionConfigRequest(BaseModel):
    """Create the next mission-config version (P6/B6). Activates by default so the worker picks it up."""

    document: dict[str, Any] = Field(default_factory=dict)
    change_note: str = Field(default="", max_length=2000)
    activate: bool = True


class RegisterAssetRequest(BaseModel):
    """Register (or version) an Asset Store blob — used for paper-trading OHLCV feeds.

    Provide ``content`` (JSON/CSV text) *or* structured ``bars``, *or* set
    ``generate_sample`` to mint a deterministic fixture series (no live broker / no login).
    """

    kind: str = Field(default="market_data", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    symbol: str = Field(default="", max_length=64)
    content: str | None = None
    bars: list[dict[str, Any]] | None = None
    filename: str | None = Field(default=None, max_length=260)
    content_type: str | None = Field(default=None, max_length=120)
    generate_sample: bool = False
    sample_bars: int = Field(default=60, ge=5, le=500)
    sample_start: float = Field(default=100.0, gt=0)


class ApprovalActionRequest(BaseModel):
    """Operator decision on a proposed approval (Phase D · §D.3/D.5, P14). Journaled + reversible."""

    actor: str | None = None
    note: str | None = Field(default=None, max_length=2000)
