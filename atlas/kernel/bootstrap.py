"""Bootstrap: the ordered startup sequence that builds the Application.

Order:
    1. Load + validate configuration
    2. Initialize logging
    3. Ensure runtime directories exist
    4. Build infrastructure (database manager)
    5. Build kernel primitives (events, registry, container, lifecycle)
    6. Register core services (database)
    7. Return a ready-to-start Application

Building does NOT start services. Call ``app.start()`` or ``app.run_forever()``.
"""

from __future__ import annotations

from atlas import capabilities as caps
from atlas.agents.rag_agent import RagAgent
from atlas.agents.react_agent import ReActAgent
from atlas.config import AtlasConfig, get_config
from atlas.conversation.service import ConversationService
from atlas.database.connection import DatabaseManager
from atlas.events.dispatcher import EventDispatcher
from atlas.events.handlers import WILDCARD, LoggingHandler
from atlas.notify import EmailSender, EventBroker, Notifier
from atlas.repositories.event_repo import EventRepository
from atlas.execution.executor import ToolExecutor
from atlas.code.parser import CodeParser
from atlas.code.service import CodeService
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.models.learning import STORE_CODE
from atlas.sandbox.backends import create_backend
from atlas.sandbox.service import PythonSandboxService
from atlas.reports.generator import ReportGenerator
from atlas.reports.service import ReportService
from atlas.research.service import ResearchService
from atlas.verification.engine import EvidenceBudget, VerificationEngine
from atlas.verification.service import VerificationService
from atlas.documents.service import DocumentService
from atlas.ingestion.filesystem_source import FilesystemSource
from atlas.jobs.planner import JobPlanner
from atlas.jobs.service import JobService
from atlas.kernel.application import Application
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.lifecycle import LifecycleManager
from atlas.kernel.registry import ServiceRegistry
from atlas.kernel.service_container import ServiceContainer
from atlas.kernel.tools import ToolRegistry
from atlas.knowledge.service import KnowledgeService
from atlas.llm.ollama_provider import OllamaProvider
from atlas.llm.service import LLMService
from atlas.ops.backup import BackupManager
from atlas.storage import StorageManager, StorageRepository
from atlas.assets import AssetRepository, AssetStore
from atlas.recovery import CheckpointStore, RecoveryManager
from atlas.repositories.recovery_repo import CheckpointRepository, RecoveryRepository
from atlas.missions import MissionRepository, MissionService
from atlas.planner.planner import Planner
from atlas.plugins.manager import PluginManager
from atlas.repositories.agent_run_repo import AgentRunRepository
from atlas.repositories.chunk_repo import ChunkRepository
from atlas.repositories.conversation_repo import ConversationRepository
from atlas.repositories.document_repo import DocumentRepository
from atlas.repositories.embedding_repo import EmbeddingRepository
from atlas.repositories.health_repo import HealthRepository
from atlas.repositories.intelligence_repo import IntelligenceRepository
from atlas.repositories.job_repo import JobRepository
from atlas.repositories.learning_repo import LearningRepository
from atlas.repositories.memory_repo import MemoryRepository
from atlas.repositories.retrieval_diagnostics_repo import RetrievalDiagnosticsRepository
from atlas.repositories.finding_repo import FindingRepository
from atlas.repositories.task_repo import TaskRepository
from atlas.scheduler.handlers import HandlerRegistry
from atlas.scheduler.service import SchedulerService
from atlas.services.agent_service import AgentService
from atlas.services.assistant_service import AssistantService
from atlas.services.database_service import DatabaseService
from atlas.services.health import HealthMonitor
from atlas.services.learning_service import LearningService
from atlas.services.memory_service import MemoryService
from atlas.system.time import ClockService
from atlas.system.versioning import build_artifact_versions
from atlas.utils.logging import get_logger, setup_logging


def build_application(config: AtlasConfig | None = None) -> Application:
    # 1. Config
    cfg = config or get_config()

    # 2. Logging
    setup_logging(cfg)
    logger = get_logger("atlas.kernel")

    # 3. Runtime directories
    cfg.paths.ensure_exist()

    # 4. Infrastructure
    db_manager = DatabaseManager(cfg.database)

    # 5. Kernel primitives
    # Durable event bus (Phase 0 · §2.5, P1): persist every event to audit.events
    # BEFORE dispatch, so the stream is replayable after a crash. Persistence is
    # best-effort inside the dispatcher (a DB blip never blocks the in-process bus).
    event_repo = EventRepository(db_manager)
    events = EventDispatcher(get_logger("atlas.events"), store=event_repo)
    events.subscribe(WILDCARD, LoggingHandler(get_logger("atlas.events")))

    # Notifier (Phase 0 · §2.5, A1): one wildcard subscriber fanning events out to the
    # operator — web/SSE first (EventBroker, consumed by the dashboard over SSE), email
    # second (best-effort, only for notable events when SMTP is configured). The SMTP
    # password is a secret read from the env var named by email.password_env (A1).
    import os as _os

    event_broker = EventBroker(
        max_queue=cfg.notifications.sse_max_queue,
        logger=get_logger("atlas.notify.broker"),
    )
    email_sender = EmailSender(
        host=cfg.email.host,
        port=cfg.email.port,
        username=cfg.email.username,
        password=_os.environ.get(cfg.email.password_env, ""),
        from_addr=cfg.email.from_addr,
        to_addrs=cfg.email.to_addrs,
        use_tls=cfg.email.use_tls,
        timeout=cfg.email.timeout,
        logger=get_logger("atlas.notify.email"),
    )
    notifier = Notifier(
        event_broker,
        email_sender,
        enabled=cfg.notifications.enabled,
        channels=cfg.notifications.channels,
        notable_types=cfg.notifications.notable_types,
        logger=get_logger("atlas.notify"),
    )
    events.subscribe(WILDCARD, notifier)

    registry = ServiceRegistry()
    container = ServiceContainer()
    # default_version → Atlas build version, so capabilities without an explicit
    # version still stamp a real version (P2), never a hardcoded "v1".
    capabilities = CapabilityRegistry(default_version=cfg.system.version)
    tools = ToolRegistry()
    lifecycle = LifecycleManager(registry, logger)

    # Clock / Time service (Phase 0 · ATLAS_OS_ROADMAP §5.7, P1): one trustworthy
    # time source (UTC internally, monotonic durations, best-effort NTP drift
    # monitor). Constructed early and started first so later durable records are
    # stamped consistently. The drift monitor never blocks startup (R1/Q9).
    clock = ClockService(
        timezone_name=cfg.system.timezone,
        ntp_enabled=cfg.clock.ntp_enabled,
        ntp_servers=cfg.clock.ntp_servers,
        ntp_timeout=cfg.clock.ntp_timeout,
        check_interval=cfg.clock.check_interval,
        drift_warn_seconds=cfg.clock.drift_warn_seconds,
        logger=get_logger("atlas.system.clock"),
    )

    # Shared dependencies available for injection
    health_repo = HealthRepository(db_manager)
    task_repo = TaskRepository(db_manager)
    handlers = HandlerRegistry()
    # Stage 3.2d: kernel-owned execution costs + Resource Manager.  Construct
    # before the LLM service so all model calls share the RM's global LLM lane.
    from atlas.core.execution import ExecutionPlanner, TaskCostModel
    from atlas.core.resources import ResourceManager

    task_costs = TaskCostModel(
        {
            kind: value
            for kind, value in cfg.resources.costs.model_dump().items()
        }
    )
    resource_manager = ResourceManager(
        profile=cfg.resources.profile,
        max_worker_threads=cfg.resources.max_worker_threads,
        max_download_workers=cfg.resources.max_download_workers,
        max_reader_workers=cfg.resources.max_reader_workers,
        max_ocr_workers=cfg.resources.max_ocr_workers,
        max_extract_workers=cfg.resources.max_extract_workers,
        llm_max_concurrency=max(1, int(cfg.llm.max_concurrency or 1)),
        cost_budgets=cfg.resources.budgets.model_dump(),
        llm_cost_units={
            "chat": cfg.resources.costs.llm_plan.units,
            "planner": cfg.resources.costs.llm_plan.units,
            "researcher": cfg.resources.costs.llm_extract.units,
            "summarizer": cfg.resources.costs.llm_summarize.units,
            "embed": cfg.resources.costs.embedding.units,
            "default": cfg.resources.costs.llm_extract.units,
        },
        logger=get_logger("atlas.resources"),
    )
    execution_planner = ExecutionPlanner(
        resource_manager,
        task_costs,
        logger=get_logger("atlas.execution"),
    )
    llm_provider = OllamaProvider(
        host=cfg.llm.host,
        model=cfg.llm.model,
        embedding_model=cfg.llm.embedding_model,
        temperature=cfg.llm.temperature,
        timeout=cfg.llm.timeout,
        keep_alive=cfg.llm.keep_alive,
        think=cfg.llm.think,
    )
    llm_service = LLMService(
        llm_provider,
        model=cfg.llm.model,
        embedding_model=cfg.llm.embedding_model,
        roles={role: spec.model for role, spec in cfg.llm.roles.items()},
        max_concurrency=cfg.llm.max_concurrency,
        resource_manager=resource_manager,
        logger=get_logger("atlas.llm"),
    )
    knowledge_service = KnowledgeService(
        DocumentRepository(db_manager),
        ChunkRepository(db_manager),
        EmbeddingRepository(db_manager),
        llm_service,
        embedding_model=cfg.llm.embedding_model,
        chunk_max_words=cfg.knowledge.chunk_max_words,
        chunk_overlap=cfg.knowledge.chunk_overlap,
        embed_batch=cfg.knowledge.embed_batch,
        rrf_k=cfg.knowledge.rrf_k,
        candidate_multiplier=cfg.knowledge.candidate_multiplier,
        max_context_chars=cfg.agent.max_context_chars,
        retrieval_mode=cfg.knowledge.retrieval_mode,
        persist_diagnostics=cfg.knowledge.persist_retrieval_diagnostics,
        diagnostics=RetrievalDiagnosticsRepository(db_manager),
        logger=get_logger("atlas.knowledge"),
    )
    # Finding store (3B.2) — lifecycle service wired after scheduler exists.
    finding_repo = FindingRepository(db_manager)
    knowledge_service._findings = finding_repo  # noqa: SLF001
    knowledge_service._lifecycle = None  # noqa: SLF001 — set below after scheduler
    # Deferred/resilient embedding path: enqueue an 'embed_document' task.
    handlers.register("embed_document", knowledge_service.embed_document_task)

    # Agent layer (Sprint 3): a RAG agent over the knowledge base, dispatched by
    # the AgentService, with every run persisted for observability/recovery.
    agent_run_repo = AgentRunRepository(db_manager)
    rag_agent = RagAgent(
        knowledge_service,
        llm_service,
        agent_run_repo,
        retrieval_k=cfg.agent.retrieval_k,
        similarity_floor=cfg.agent.similarity_floor,
        max_context_chars=cfg.agent.max_context_chars,
        grounding=cfg.agent.grounding,
        system_preamble=cfg.agent.system_preamble,
        logger=get_logger("atlas.agent.rag"),
    )
    # ReAct assistant (Sprint 8): reasons + acts over the ToolRegistry, and can
    # delegate to other agents exposed as tools (ADR-0051/0052). Holds the shared
    # `tools` registry by reference, so it sees plugin tools registered later.
    react_agent = ReActAgent(
        llm_service,
        tools,
        agent_run_repo,
        max_iterations=cfg.react.max_iterations,
        reflection=cfg.react.reflection,
        max_observation_chars=cfg.react.max_observation_chars,
        temperature=cfg.react.temperature,
        think=cfg.react.think,
        system_preamble=cfg.react.system_preamble,
        logger=get_logger("atlas.agent.react"),
    )
    agent_service = AgentService(
        agents=[rag_agent, react_agent],
        run_repo=agent_run_repo,
        logger=get_logger("atlas.agent"),
    )
    handlers.register("run_agent", agent_service.run_agent_task)

    # Expose other agents as tools so the ReAct assistant can delegate to them
    # (ADR-0052). The assistant is not registered as a tool of itself.
    def _agent_tool(name: str):
        def call(query: str) -> str:
            return agent_service.run(name, query).answer

        return call

    tools.register(
        f"agent.{rag_agent.name}",
        _agent_tool(rag_agent.name),
        description=rag_agent.description,
        params={"query": "the question to ask the knowledge-base RAG agent"},
        plugin="agents",
    )

    # Scheduler service (kept as a variable so the ingestion source can enqueue).
    scheduler_service = SchedulerService(
        task_repo=task_repo,
        handlers=handlers,
        events=events,
        workers=cfg.scheduler.workers,
        poll_interval=cfg.scheduler.poll_interval,
        backoff_base=cfg.scheduler.backoff_base,
        drain_timeout=cfg.scheduler.drain_timeout,
        logger=get_logger("atlas.scheduler"),
    )
    from atlas.knowledge.consolidation import KnowledgeLifecycleService

    knowledge_lifecycle = KnowledgeLifecycleService(
        finding_repo,
        enqueue=scheduler_service.enqueue,
        logger=get_logger("atlas.knowledge.lifecycle"),
    )
    knowledge_service._lifecycle = knowledge_lifecycle  # noqa: SLF001
    handlers.register(
        "review_finding",
        knowledge_lifecycle.review_finding,
    )

    # Memory service (Sprint 6): working/episodic/semantic memory over memory.items.
    # Created after the scheduler so it can enqueue its durable prune task.
    memory_service = MemoryService(
        MemoryRepository(db_manager),
        llm_service,
        embedding_model=cfg.llm.embedding_model,
        recall_k=cfg.memory.recall_k,
        similarity_floor=cfg.memory.similarity_floor,
        working_ttl_seconds=cfg.memory.working_ttl_seconds,
        embed_working=cfg.memory.embed_working,
        prune_interval=cfg.memory.prune_interval,
        enqueue=scheduler_service.enqueue,
        count_pending=task_repo.count_pending_of_type,
        logger=get_logger("atlas.memory"),
    )
    handlers.register("memory_prune", memory_service.prune_task)

    # Backups (Sprint 9): durable, scheduler-driven pg_dump with retention.
    backup_manager = BackupManager(
        cfg.database,
        cfg.paths.backups,
        enabled=cfg.backup.enabled,
        interval_seconds=cfg.backup.interval_seconds,
        retention=cfg.backup.retention,
        pg_dump_path=cfg.backup.pg_dump_path,
        enqueue=scheduler_service.enqueue,
        count_pending=task_repo.count_pending_of_type,
        logger=get_logger("atlas.ops.backup"),
    )
    handlers.register("backup", backup_manager.backup_task)

    # Storage Manager (Phase 0 · ATLAS_OS_ROADMAP §5.8, P8): the one subsystem all
    # durable files flow through — versioned + checksummed put/get, workspace
    # allocation, advisory per-scope quotas, and backup orchestration (wraps the
    # BackupManager above). Hot/warm/cold tiering is deferred (single disk, R2).
    storage_root = cfg.storage.dir or str(cfg.paths.data / "storage")
    storage_manager = StorageManager(
        storage_root,
        StorageRepository(db_manager),
        backup=backup_manager,
        default_quota_bytes=max(0, cfg.storage.default_quota_mb) * 1024 * 1024,
        logger=get_logger("atlas.storage"),
    )

    # Asset Store (Phase 0 · ATLAS_OS_ROADMAP §5.9, P8): raw, versioned *source
    # artifacts* (repos, PDFs, DWG/CAD, MATLAB, images) — the things knowledge is
    # extracted from — stored through the Storage Manager. Assets ≠ Knowledge, so a
    # better reader later re-derives knowledge without re-fetching the bytes.
    asset_store = AssetStore(
        storage_manager,
        AssetRepository(db_manager),
        logger=get_logger("atlas.assets"),
    )

    # Recovery Manager (Phase 0 · §2.8, P1/P4): the cross-cutting *startup* recovery
    # layer. Per-subsystem recovery already exists (the scheduler resets interrupted
    # tasks and the Job Engine re-enqueues unfinished jobs in their own start()); this
    # runs *first* — before work is accepted — and adds what spans subsystems: a
    # durable, re-entrant run record (system.recovery_runs; a crash mid-recovery is
    # marked interrupted and the next boot re-runs cleanly, R1/Q6), storage integrity
    # (checksums), and backup verification. Never blocks boot; emits RecoveryStarted/
    # Completed to the dashboard. CheckpointStore is the resume-point foundation
    # (system.checkpoints) Phase A workers adopt.
    checkpoint_store = CheckpointStore(
        CheckpointRepository(db_manager),
        logger=get_logger("atlas.recovery.checkpoints"),
    )
    recovery_manager = RecoveryManager(
        RecoveryRepository(db_manager),
        storage=storage_manager,
        backup=backup_manager,
        task_repo=task_repo,
        events=events,
        logger=get_logger("atlas.recovery"),
    )

    # Mission Manager (Phase A · §A.1, P5/P7): the Mission layer above Jobs — long-lived,
    # operator-created objectives that own Jobs and (later) Persistent Workers, run off a
    # versioned Configuration, and journal every action for explainability (P9). Archival is
    # non-destructive (B5/B9). Emits Mission* events on the durable bus → dashboard.
    mission_service = MissionService(
        MissionRepository(db_manager),
        events=events,
        logger=get_logger("atlas.missions"),
    )

    # Conversation + Chat orchestrator (Sprint 10): the shared spine (D1) that the
    # async Job Engine (S12) will reuse. ConversationService owns the transcript;
    # the deterministic Planner routes intents; the ToolExecutor runs tool steps;
    # the AssistantService ties session -> plan -> dispatch -> response together.
    conversation_service = ConversationService(
        ConversationRepository(db_manager),
        memory_service,
        max_context_turns=cfg.conversation.max_context_turns,
        working_memory_k=cfg.conversation.working_memory_k,
        logger=get_logger("atlas.conversation"),
    )
    planner = Planner()
    tool_executor = ToolExecutor(tools, logger=get_logger("atlas.execution"))
    assistant_service = AssistantService(
        conversation_service,
        planner,
        tool_executor,
        knowledge=knowledge_service,
        memory=memory_service,
        agent=agent_service,
        llm=llm_service,
        tools=tools,  # shared by ref; plugin tools (web.fetch) register later
        capabilities=capabilities,  # shared by ref; plugins register 'web' later
        interactive_timeout=cfg.llm.interactive_timeout,  # RC/D3.12c
        logger=get_logger("atlas.assistant"),
    )

    # Job Engine (Sprint 12): persistent, concurrent, resumable jobs on the
    # scheduler. Decomposes an objective into steps and advances them one per
    # `advance_job` task (self-re-enqueuing) so jobs interleave (R1) while steps
    # stay sequential (Q1); reuses the AssistantService step dispatch verbatim (D1).
    # Verification Engine + Evidence Graph (Sprint 15, D8/§5a): verify by *claim*,
    # calculate confidence from evidence quality + numeric convergence + contradictions,
    # and enforce a per-job Evidence Budget (stop on convergence, not paper count).
    verification_service = VerificationService(
        VerificationEngine(numeric_tolerance=cfg.research.numeric_tolerance),
        default_budget=EvidenceBudget(
            min_sources=cfg.research.min_sources,
            min_peer_reviewed=cfg.research.min_peer_reviewed,
            min_government=cfg.research.min_government,
            convergence=cfg.research.convergence,
            max_search_iterations=cfg.research.max_search_iterations,
        ),
        logger=get_logger("atlas.verification"),
    )
    # Report Generator (Sprint 17, §5a.5): verified claims → scientific-review report.
    report_service = ReportService(
        verification_service,
        ReportGenerator(llm=llm_service, logger=get_logger("atlas.reports")),
        logger=get_logger("atlas.reports"),
    )
    # Autonomous Research Orchestration (Sprint 21, D8/§5a): the gather→verify→decide
    # loop. Resolves the scholar/search capabilities lazily (they register later as
    # plugins) so a disabled provider degrades to `unavailable` rather than crashing.
    # Acquisition + Reader (Stage 3, Step 3 / §5d–5e, C1): fetch + read the top
    # sources into normalized Documents using the resilient net layer. Registered in
    # the container so the research loop (Step 5) can acquire real full text — not just
    # search snippets — with open-access-first + honest paywall blocking (D3.3).
    from atlas.net import FetchClient
    from atlas.research.acquire import Librarian
    from atlas.research.reader import Reader

    fetch_client = FetchClient(
        user_agent=cfg.net.user_agent,
        timeout=cfg.net.timeout,
        max_bytes=cfg.net.max_bytes,
        per_domain_delay=cfg.net.per_domain_delay,
        max_retries=cfg.net.max_retries,
        backoff_base=cfg.net.backoff_base,
        backoff_cap=cfg.net.backoff_cap,
        jitter=cfg.net.jitter,
        respect_robots=cfg.net.respect_robots,
        cache_ttl=cfg.net.cache_ttl,
    )
    reader = Reader(
        ocr_max_pages=cfg.resources.ocr_max_pages,
        ocr_max_minutes=cfg.resources.ocr_max_minutes,
        ocr_dpi=cfg.resources.ocr_dpi,
    )
    pools = resource_manager.recommend_pool_sizes()
    librarian = Librarian(
        fetch_client,
        reader=reader,
        max_documents=cfg.research.max_documents,
        max_workers=pools.acquire_workers,
        global_max_workers=cfg.resources.max_worker_threads,
        logger=get_logger("atlas.research.acquire"),
    )
    # Claim Extraction (Stage 3, Step 4 / §5f, C2): read Document → structured claims.
    # Hybrid (D3.1): deterministic numeric extraction + a bounded, section-scoped LLM
    # prose pass on the `researcher` role. Registered for the Step-5 loop rebuild.
    from atlas.research.extract import ClaimExtractor

    claim_extractor = ClaimExtractor(
        llm_service,
        logger=get_logger("atlas.research.extract"),
    )
    from atlas.research.synthesis import EvidenceSynthesizer

    # Artifact versioning (P2 · §2.6): stamp the real component/model builds onto every
    # Finding + Experience so a later model swap is a scoped re-derivation, not a
    # rebuild. Versions come from component VERSION constants + configured model names.
    _researcher_role = cfg.llm.roles.get("researcher")
    artifact_versions = build_artifact_versions(
        llm_id=(_researcher_role.model if _researcher_role else cfg.llm.model),
        embedding_id=cfg.llm.embedding_model,
        reader_version=Reader.VERSION,
        extractor_version=ClaimExtractor.VERSION,
        verifier_version=VerificationEngine.VERSION,
        synthesizer_version=EvidenceSynthesizer.VERSION,
    )
    evidence_synthesizer = EvidenceSynthesizer(
        versions=artifact_versions.as_dict(),
        logger=get_logger("atlas.research.synthesis"),
    )

    # Continuous Learning (Sprint 18b + Stage 3B.5): create before research so
    # advice-only recall can be injected into the research loop.
    learning_service = LearningService(
        LearningRepository(db_manager),
        cfg.learning,
        versions=artifact_versions.as_dict(),
        logger=get_logger("atlas.learning"),
    )
    # Soft bias after apply+enable is loaded inside KnowledgeService.retrieve.
    knowledge_service._learning = learning_service  # noqa: SLF001

    research_service = ResearchService(
        verification_service,
        report_service,
        capabilities=capabilities,  # shared by ref; scholar/search plugins register later
        librarian=librarian,        # Stage 3, Step 5 (C4): acquire + read real documents
        extractor=claim_extractor,  # …then extract structured claims (not score URLs)
        resources=resource_manager,
        execution=execution_planner,
        knowledge=knowledge_service,
        synthesizer=evidence_synthesizer,
        learning=learning_service,
        per_query=cfg.research.per_query,
        max_documents=cfg.research.max_documents,
        max_extract_workers=pools.extract_workers,
        max_worker_threads=cfg.resources.max_worker_threads,
        logger=get_logger("atlas.research"),
    )
    tools.register(
        "research.run", research_service.research,
        description="Run an autonomous gather→verify→decide research loop and return a "
        "verified report.",
        params={
            "objective": "the research question or topic",
            "max_iterations": "optional cap on search rounds",
            "resource_profile": "optional: conservative|balanced|maximum|overnight",
        },
        plugin="research",
    )

    # Continuous Learning is constructed earlier (before ResearchService) so
    # research/planner can recall advice without inventing a second ledger.

    job_repo = JobRepository(db_manager)
    job_planner = JobPlanner(
        planner,
        llm_service if cfg.jobs.llm_decompose else None,
        max_steps=cfg.jobs.max_steps,
        research_first=cfg.jobs.research_first,
        timeout=cfg.jobs.planner_timeout,
        num_predict=cfg.jobs.planner_num_predict,
        learning=learning_service,
        logger=get_logger("atlas.jobs.planner"),
    )
    job_service = JobService(
        job_repo,
        job_planner,
        assistant_service,
        enqueue=scheduler_service.enqueue,
        conversation=conversation_service,
        reports=report_service,
        events=events,
        learning=learning_service,
        knowledge=knowledge_service,
        workspace_root=cfg.paths.data,  # §5a/C3: per-job on-disk workspaces
        step_max_retries=cfg.jobs.step_max_retries,
        retry_delay=cfg.jobs.retry_delay,
        logger=get_logger("atlas.jobs"),
    )
    handlers.register("plan_job", job_service.plan_job_task)
    handlers.register("advance_job", job_service.advance_job_task)

    # Ingestion source (Sprint 3): scan documents dir -> knowledge base. Embedding
    # is deferred to the scheduler's 'embed_document' task; scans re-enqueue
    # themselves so periodic ingestion is durable across restarts.
    # Document Reader (Sprint 13): structured extraction across formats
    # (pdf/docx/pptx/xlsx/csv/md/txt/html/json), exposed as the `document` capability.
    document_service = DocumentService(logger=get_logger("atlas.documents"))

    # Code Understanding (Sprint 14, D9/§5b, Tier B): structural parse (Python=ast,
    # others=tree-sitter) → repo map + symbol index + import/call graph + pattern
    # mining, with code-aware chunking into the knowledge base and a `code`-role LLM
    # explanation grounded on the parsed structure.
    code_service = CodeService(
        CodeParser(max_file_bytes=cfg.code.max_file_bytes),
        knowledge=knowledge_service,
        llm=llm_service,
        max_files=cfg.code.max_files,
        logger=get_logger("atlas.code"),
    )
    tools.register(
        "code.parse", code_service.parse,
        description="Parse one code file into symbols/imports/calls.",
        params={"path": "path to a source file"}, plugin="code",
    )
    tools.register(
        "code.repo_map", code_service.repo_map,
        description="Map a repository: languages, deps, frameworks, entry points.",
        params={"root": "path to a repository root"}, plugin="code",
    )
    tools.register(
        "code.symbols", code_service.search_symbols,
        description="Search code symbols (functions/classes/methods) in a repo.",
        params={"query": "name substring", "root": "repository root"}, plugin="code",
    )
    tools.register(
        "code.graph", code_service.graph,
        description="Build a repo's import graph + cross-file call graph.",
        params={"root": "path to a repository root"}, plugin="code",
    )
    tools.register(
        "code.patterns", code_service.patterns,
        description="Mine recurring engineering patterns across a repo.",
        params={"root": "path to a repository root"}, plugin="code",
    )

    # Engineering Intelligence (Sprint 19, D11/§5d): higher-order learners over the
    # Code store — learn repos (L2), connect/search (L3), generalize patterns (L4),
    # recommend (L5). Repository learning is promoted through the S18b ledger via a
    # store sink registered on the learning service ("adds sinks, not schema").
    intelligence_repo = IntelligenceRepository(db_manager)
    intelligence_service = IntelligenceService(
        code_service,
        intelligence_repo,
        learning_service,
        cfg.intelligence,
        logger=get_logger("atlas.intelligence"),
    )
    learning_service.register_sink(STORE_CODE, CodeStoreSink(intelligence_repo))

    # Python Execution Sandbox (Sprint 16, D6 — hybrid): run analysis code in a
    # resource-limited child interpreter (subprocess default; docker swappable) with
    # network disabled by default; computed results can become L5 evidence (§5a.6).
    sandbox_root = cfg.sandbox.dir or str(cfg.paths.data / "sandbox")
    python_service = PythonSandboxService(
        create_backend(cfg.sandbox.backend),
        workdir=sandbox_root,
        timeout=cfg.sandbox.timeout,
        memory_mb=cfg.sandbox.memory_mb,
        cpu_seconds=cfg.sandbox.cpu_seconds,
        max_output_bytes=cfg.sandbox.max_output_bytes,
        max_code_bytes=cfg.sandbox.max_code_bytes,
        network=cfg.sandbox.network,
        logger=get_logger("atlas.sandbox"),
    )
    tools.register(
        "python.run", python_service.run,
        description="Run Python in an isolated, resource-limited sandbox.",
        params={"code": "Python source to execute"}, plugin="python",
    )

    ingestion_source = FilesystemSource(
        knowledge_service,
        documents_dir=cfg.paths.documents,
        extensions=cfg.ingestion.extensions,
        enqueue=scheduler_service.enqueue,
        count_pending=task_repo.count_pending_of_type,
        scan_interval=cfg.ingestion.scan_interval,
        enabled=cfg.ingestion.enabled,
        logger=get_logger("atlas.ingestion"),
    )
    handlers.register("ingest_scan", ingestion_source.scan_task)

    container.register_instance("config", cfg)
    container.register_instance("clock", clock)
    container.register_instance("database_manager", db_manager)
    container.register_instance("events", events)
    container.register_instance("event_repo", event_repo)
    container.register_instance("notifier", notifier)
    container.register_instance("health_repo", health_repo)
    container.register_instance("task_repo", task_repo)
    container.register_instance("task_handlers", handlers)
    container.register_instance("llm", llm_service)
    container.register_instance("knowledge", knowledge_service)
    container.register_instance("agent_run_repo", agent_run_repo)
    container.register_instance("agent", agent_service)
    container.register_instance("memory", memory_service)
    container.register_instance("backup", backup_manager)
    container.register_instance("storage", storage_manager)
    container.register_instance("assets", asset_store)
    container.register_instance("recovery", recovery_manager)
    container.register_instance("checkpoints", checkpoint_store)
    container.register_instance("missions", mission_service)
    container.register_instance("conversation", conversation_service)
    container.register_instance("planner", planner)
    container.register_instance("tool_executor", tool_executor)
    container.register_instance("chat", assistant_service)
    container.register_instance("jobs", job_service)
    container.register_instance("documents", document_service)
    container.register_instance("code", code_service)
    container.register_instance("python", python_service)
    container.register_instance("verification", verification_service)
    container.register_instance("reports", report_service)
    container.register_instance("research", research_service)
    container.register_instance("librarian", librarian)
    container.register_instance("claim_extractor", claim_extractor)
    container.register_instance("resources", resource_manager)
    container.register_instance("execution", execution_planner)
    container.register_instance("learning", learning_service)
    container.register_instance("intelligence", intelligence_service)
    container.register_instance("ingestion", ingestion_source)

    # Advertise capabilities so agents can query the kernel instead of importing
    # modules (ADR-0040). S11: attach typed contracts so the registry can verify a
    # provider implements its protocol and report missing capabilities (R2).
    capabilities.register("clock", clock, kind="kernel")
    capabilities.register("llm", llm_service, contract=caps.LLMCapability, kind="service")
    capabilities.register(
        "knowledge", knowledge_service, contract=caps.KnowledgeCapability, kind="service"
    )
    capabilities.register(
        caps.CAP_RETRIEVAL,
        knowledge_service,
        contract=caps.RetrievalCapability,
        kind="service",
    )
    capabilities.register(
        caps.CAP_SYNTHESIS,
        evidence_synthesizer,
        contract=caps.SynthesisCapability,
        kind="service",
        version=EvidenceSynthesizer.VERSION,
    )
    capabilities.register(
        caps.CAP_KNOWLEDGE_LIFECYCLE,
        knowledge_lifecycle,
        contract=caps.KnowledgeLifecycleCapability,
        kind="service",
    )
    capabilities.register("scheduler", scheduler_service, kind="service")
    capabilities.register(
        "agent", agent_service, contract=caps.ExecutionCapability, kind="service"
    )
    capabilities.register(
        "memory", memory_service, contract=caps.MemoryCapability, kind="service"
    )
    capabilities.register("backup", backup_manager, kind="service")
    capabilities.register(
        "storage", storage_manager, kind="kernel", version=StorageManager.VERSION
    )
    capabilities.register(
        "assets", asset_store, kind="kernel", version=AssetStore.VERSION
    )
    capabilities.register(
        "recovery", recovery_manager, kind="kernel", version=RecoveryManager.VERSION
    )
    capabilities.register(
        "checkpoints", checkpoint_store, kind="kernel", version=CheckpointStore.VERSION
    )
    capabilities.register(
        "missions", mission_service, kind="service", version=MissionService.VERSION
    )
    capabilities.register(
        "notifier", notifier, kind="kernel", version=Notifier.VERSION
    )
    capabilities.register(
        "conversation",
        conversation_service,
        contract=caps.ConversationCapability,
        kind="service",
    )
    capabilities.register("chat", assistant_service, kind="service")
    capabilities.register("jobs", job_service, kind="service")
    capabilities.register(
        "document", document_service, contract=caps.DocumentCapability, kind="service"
    )
    capabilities.register(
        "code", code_service, contract=caps.CodeCapability, kind="service"
    )
    capabilities.register(
        "python", python_service, contract=caps.PythonExecutionCapability, kind="service"
    )
    capabilities.register(
        "verification", verification_service, kind="service",
        version=VerificationEngine.VERSION,
    )
    capabilities.register("reports", report_service, kind="service")
    capabilities.register(
        "research", research_service, contract=caps.ResearchCapability, kind="service"
    )
    capabilities.register("resources", resource_manager, kind="service")
    capabilities.register("execution", execution_planner, kind="service")
    capabilities.register(
        "learning", learning_service, contract=caps.LearningCapability, kind="service"
    )
    capabilities.register(
        "intelligence", intelligence_service,
        contract=caps.IntelligenceCapability, kind="service",
    )
    capabilities.register("ingestion", ingestion_source, kind="service")

    # 6. Core services (registration order = start order)
    registry.register(clock)  # first: time source for everything that follows
    registry.register(DatabaseService(db_manager))
    # Recovery runs right after the DB is up and BEFORE any work-accepting service
    # (scheduler/jobs) starts, so interrupted state is reconciled first (P4).
    registry.register(recovery_manager)
    registry.register(checkpoint_store)
    registry.register(llm_service)
    registry.register(scheduler_service)
    registry.register(agent_service)
    registry.register(memory_service)
    registry.register(backup_manager)
    registry.register(storage_manager)
    registry.register(asset_store)
    registry.register(mission_service)
    registry.register(notifier)
    registry.register(conversation_service)
    registry.register(assistant_service)
    registry.register(job_service)
    registry.register(document_service)
    registry.register(code_service)
    registry.register(python_service)
    registry.register(verification_service)
    registry.register(report_service)
    registry.register(resource_manager)
    registry.register(execution_planner)
    registry.register(research_service)
    registry.register(learning_service)
    registry.register(intelligence_service)
    registry.register(ingestion_source)

    # 7. Application object — holds the shared registries by reference, so it can
    # be constructed here and still see services/plugins registered below.
    app = Application(
        config=cfg,
        logger=logger,
        events=events,
        registry=registry,
        container=container,
        lifecycle=lifecycle,
        capabilities=capabilities,
        tools=tools,
    )

    # 8. Plugins (ADR-0041/0049): load from config, let each self-register its
    # capabilities (ADR-0040) + tools (ADR-0050); the PluginManager owns their
    # lifecycle and reports their health as a single 'plugins' service.
    plugin_manager = PluginManager(logger=get_logger("atlas.plugins"))
    plugin_manager.load(cfg)
    plugin_manager.register_all(app)
    container.register_instance("plugins", plugin_manager)
    capabilities.register("plugins", plugin_manager, kind="kernel")
    registry.register(plugin_manager)

    # 8b. Operations Dashboard (Phase 0 · §5.11, A4): the single-screen operator view
    # (status, counts, host metrics, last backup, capabilities), fed on demand via
    # /v1/ops and live-updated by the SSE event stream. Built after `app` so it can read
    # status/health/capabilities; host metrics are stdlib + best-effort (temp/UPS report
    # "not present" when no sensor). Registered on the container the app already holds.
    from atlas.ops.dashboard import OperationsDashboard
    from atlas.system.host import HostMetrics

    host_metrics = HostMetrics(
        disk_path=cfg.paths.data,
        logger=get_logger("atlas.system.host"),
    )
    ops_dashboard = OperationsDashboard(
        app, host_metrics, clock=clock, logger=get_logger("atlas.ops.dashboard")
    )
    container.register_instance("host_metrics", host_metrics)
    container.register_instance("ops_dashboard", ops_dashboard)
    capabilities.register("ops_dashboard", ops_dashboard, kind="kernel")

    # 9. Health monitor last, so it observes every other service (incl. plugins).
    registry.register(
        HealthMonitor(
            registry=registry,
            health_repo=health_repo,
            events=events,
            interval=cfg.monitoring.health_interval,
            logger=get_logger("atlas.health"),
        )
    )

    return app
