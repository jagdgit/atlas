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

from atlas.agents.rag_agent import RagAgent
from atlas.agents.react_agent import ReActAgent
from atlas.config import AtlasConfig, get_config
from atlas.database.connection import DatabaseManager
from atlas.events.dispatcher import EventDispatcher
from atlas.events.handlers import WILDCARD, LoggingHandler
from atlas.ingestion.filesystem_source import FilesystemSource
from atlas.kernel.application import Application
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.lifecycle import LifecycleManager
from atlas.kernel.registry import ServiceRegistry
from atlas.kernel.service_container import ServiceContainer
from atlas.kernel.tools import ToolRegistry
from atlas.knowledge.service import KnowledgeService
from atlas.llm.ollama_provider import OllamaProvider
from atlas.llm.service import LLMService
from atlas.plugins.manager import PluginManager
from atlas.repositories.agent_run_repo import AgentRunRepository
from atlas.repositories.chunk_repo import ChunkRepository
from atlas.repositories.document_repo import DocumentRepository
from atlas.repositories.embedding_repo import EmbeddingRepository
from atlas.repositories.health_repo import HealthRepository
from atlas.repositories.memory_repo import MemoryRepository
from atlas.repositories.task_repo import TaskRepository
from atlas.scheduler.handlers import HandlerRegistry
from atlas.scheduler.service import SchedulerService
from atlas.services.agent_service import AgentService
from atlas.services.database_service import DatabaseService
from atlas.services.health import HealthMonitor
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

    # Ingestion source (Sprint 3): scan documents dir -> knowledge base. Embedding
    # is deferred to the scheduler's 'embed_document' task; scans re-enqueue
    # themselves so periodic ingestion is durable across restarts.
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
    container.register_instance("ingestion", ingestion_source)

    # Advertise capabilities so agents can query the kernel instead of importing
    # modules (ADR-0040). Plugins will register their own capabilities in Sprint 7.
    capabilities.register("llm", llm_service, kind="service")
    capabilities.register("knowledge", knowledge_service, kind="service")
    capabilities.register("scheduler", scheduler_service, kind="service")
    capabilities.register("agent", agent_service, kind="service")
    capabilities.register("memory", memory_service, kind="service")
    capabilities.register("ingestion", ingestion_source, kind="service")

    # 6. Core services (registration order = start order)
    registry.register(DatabaseService(db_manager))
    registry.register(llm_service)
    registry.register(scheduler_service)
    registry.register(agent_service)
    registry.register(memory_service)
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
