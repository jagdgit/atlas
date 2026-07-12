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
from atlas.repositories.task_repo import TaskRepository
from atlas.scheduler.handlers import HandlerRegistry
from atlas.scheduler.service import SchedulerService
from atlas.services.agent_service import AgentService
from atlas.services.assistant_service import AssistantService
from atlas.services.database_service import DatabaseService
from atlas.services.health import HealthMonitor
from atlas.services.learning_service import LearningService
from atlas.services.memory_service import MemoryService
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
    events = EventDispatcher(get_logger("atlas.events"))
    events.subscribe(WILDCARD, LoggingHandler(get_logger("atlas.events")))

    registry = ServiceRegistry()
    container = ServiceContainer()
    capabilities = CapabilityRegistry()
    tools = ToolRegistry()
    lifecycle = LifecycleManager(registry, logger)

    # Shared dependencies available for injection
    health_repo = HealthRepository(db_manager)
    task_repo = TaskRepository(db_manager)
    handlers = HandlerRegistry()
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
        logger=get_logger("atlas.knowledge"),
    )
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
    research_service = ResearchService(
        verification_service,
        report_service,
        capabilities=capabilities,  # shared by ref; scholar/search plugins register later
        per_query=cfg.research.per_query,
        logger=get_logger("atlas.research"),
    )
    tools.register(
        "research.run", research_service.research,
        description="Run an autonomous gather→verify→decide research loop and return a "
        "verified report.",
        params={
            "objective": "the research question or topic",
            "max_iterations": "optional cap on search rounds",
        },
        plugin="research",
    )

    # Continuous Learning (Sprint 18b, D11/§5d): governed, reversible promotion of
    # completed activities into the five stores; seeds the Experience store.
    learning_service = LearningService(
        LearningRepository(db_manager),
        cfg.learning,
        logger=get_logger("atlas.learning"),
    )

    job_repo = JobRepository(db_manager)
    job_planner = JobPlanner(
        planner,
        llm_service if cfg.jobs.llm_decompose else None,
        max_steps=cfg.jobs.max_steps,
        research_first=cfg.jobs.research_first,
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
        workspace_root=cfg.paths.data,  # §5a/C3: per-job on-disk workspaces
        step_max_retries=cfg.jobs.step_max_retries,
        retry_delay=cfg.jobs.retry_delay,
        logger=get_logger("atlas.jobs"),
    )
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
    container.register_instance("database_manager", db_manager)
    container.register_instance("events", events)
    container.register_instance("health_repo", health_repo)
    container.register_instance("task_repo", task_repo)
    container.register_instance("task_handlers", handlers)
    container.register_instance("llm", llm_service)
    container.register_instance("knowledge", knowledge_service)
    container.register_instance("agent_run_repo", agent_run_repo)
    container.register_instance("agent", agent_service)
    container.register_instance("memory", memory_service)
    container.register_instance("backup", backup_manager)
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
    container.register_instance("learning", learning_service)
    container.register_instance("intelligence", intelligence_service)
    container.register_instance("ingestion", ingestion_source)

    # Advertise capabilities so agents can query the kernel instead of importing
    # modules (ADR-0040). S11: attach typed contracts so the registry can verify a
    # provider implements its protocol and report missing capabilities (R2).
    capabilities.register("llm", llm_service, contract=caps.LLMCapability, kind="service")
    capabilities.register(
        "knowledge", knowledge_service, contract=caps.KnowledgeCapability, kind="service"
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
    capabilities.register("verification", verification_service, kind="service")
    capabilities.register("reports", report_service, kind="service")
    capabilities.register(
        "research", research_service, contract=caps.ResearchCapability, kind="service"
    )
    capabilities.register(
        "learning", learning_service, contract=caps.LearningCapability, kind="service"
    )
    capabilities.register(
        "intelligence", intelligence_service,
        contract=caps.IntelligenceCapability, kind="service",
    )
    capabilities.register("ingestion", ingestion_source, kind="service")

    # 6. Core services (registration order = start order)
    registry.register(DatabaseService(db_manager))
    registry.register(llm_service)
    registry.register(scheduler_service)
    registry.register(agent_service)
    registry.register(memory_service)
    registry.register(backup_manager)
    registry.register(conversation_service)
    registry.register(assistant_service)
    registry.register(job_service)
    registry.register(document_service)
    registry.register(code_service)
    registry.register(python_service)
    registry.register(verification_service)
    registry.register(report_service)
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
