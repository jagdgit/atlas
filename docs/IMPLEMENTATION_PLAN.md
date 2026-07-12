# Atlas — Implementation Plan & Discussion Document

> **Status:** Sprints 1–9 complete — Operations live (systemd/Docker, Prometheus + JSON metrics, scheduled pg_dump backups); next is Web UI (backlog)  
> **Last updated:** 2026-07-11  
> **Purpose:** Capture architecture decisions, open questions, and a step-by-step implementation roadmap before writing production code.

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [Current State Assessment](#2-current-state-assessment)
3. [Core Principles](#3-core-principles)
4. [Target Architecture](#4-target-architecture)
5. [Directory Structure](#5-directory-structure)
6. [Technology Stack](#6-technology-stack)
7. [Database Design](#7-database-design)
8. [Atlas Kernel (Microkernel)](#8-atlas-kernel-microkernel)
9. [Event-Driven Architecture](#9-event-driven-architecture)
10. [Resilience & Recovery](#10-resilience--recovery)
11. [Sprint 1 — Foundation (Detailed)](#11-sprint-1--foundation-detailed)
12. [Future Sprints (Preview)](#12-future-sprints-preview)
13. [Open Questions for Discussion](#13-open-questions-for-discussion)
14. [Decision Log](#14-decision-log)
15. [Next Steps](#15-next-steps)
16. [Architecture Maturity Scorecard](#16-architecture-maturity-scorecard)
17. [Sprint 3 — Agent Layer & RAG (Detailed Plan)](#17-sprint-3--agent-layer--rag-detailed-plan)
18. [Cross-Cutting Foundations & Revised Roadmap](#18-cross-cutting-foundations--revised-roadmap)
19. [Sprint 5 — REST API + CLI + Auth (Detailed Plan)](#19-sprint-5--rest-api--cli--auth-detailed-plan)
20. [Sprint 6 — Memory System (Detailed Plan)](#20-sprint-6--memory-system-detailed-plan)
21. [Sprint 7 — Plugins & Tools (Detailed Plan)](#21-sprint-7--plugins--tools-detailed-plan)
22. [Sprint 8 — Multi-Agent (Detailed Plan)](#22-sprint-8--multi-agent-detailed-plan)
23. [Sprint 9 — Operations (Detailed Plan)](#23-sprint-9--operations-detailed-plan)

---

## 1. Vision & Goals

### What Atlas Is

Atlas is a **personal, self-hosted AI Operating System** that runs on your own computer and works for you over the long term. It is designed as a **multi-year platform**, not a one-off script.

> **Identity (ADR-0022):** Atlas is not an "AI agent framework." It is an
> **AI Operating System with a microkernel architecture**. This framing keeps the
> kernel small and stable while everything else evolves independently.

### The Four Layers

```
┌───────────────────────────────────────────────────────────┐
│  AGENTS        Orchestrators that compose services &        │
│                plugins to accomplish goals                  │
├───────────────────────────────────────────────────────────┤
│  PLUGINS       Browser, filesystem, databases, GitHub,      │
│                email, shell, SCADA, external APIs           │
├───────────────────────────────────────────────────────────┤
│  SERVICES      Memory, knowledge, scheduling, LLM access,   │
│                embeddings, OCR, chunking, search, ranking   │
├───────────────────────────────────────────────────────────┤
│  KERNEL        Lifecycle, configuration, dependency         │
│  (microkernel) injection, events, plugin loading. Nothing   │
│                else. Small and stable.                      │
└───────────────────────────────────────────────────────────┘
```

- **Kernel** – lifecycle, configuration, dependency injection, events, plugin loading.
- **System services** – memory, knowledge, scheduling, LLM access, embeddings.
- **Plugins** – browser, filesystem, databases, external APIs (self-register with the kernel).
- **Agents** – orchestrators that compose services and plugins to accomplish goals.

Agents should never know *how* work is done — only *what* they want.

### Primary Goals

| Goal | Description |
|------|-------------|
| **Personal autonomy** | Runs locally with Ollama; you own the data and the stack |
| **Knowledge-centric** | Knowledge → Memory → Reasoning → Model (not model-first) |
| **Resilience** | Survives power and internet outages; resumes work from the last checkpoint |
| **Clean architecture** | Microkernel + Services + Plugins + Agents; agents never touch infrastructure directly |
| **Long-term maintainability** | Versioned config, migrations, structured logging, reproducible environments |

### What Atlas Is Not (Sprint 1)

Sprint 1 deliberately excludes:

- AI chat interfaces
- Browser automation
- Document ingestion pipelines
- Embedding generation
- Agent logic

Sprint 1 builds the **operating system** that everything else will run on.

### Reference Material

- YouTube tutorial (reference only): [Build Your Own AI Agent](https://www.youtube.com/watch?v=bTMPwUgLZf0)
- Local reference copy: `/d/my_agent/ref/` (not part of this repo)

---

## 2. Current State Assessment

### Already in Place ✅

| Component | Status | Notes |
|-----------|--------|-------|
| Git repository | ✅ | Remote on GitHub; `main` branch |
| Dedicated server | ✅ | Linux environment |
| Data separation | ✅ Partial | `/data/atlas_data/` exists with proper subdirs |
| PostgreSQL | ✅ | **18.4** (exceeds original PG 17 target) |
| pgvector extension | ✅ | Installed in `atlas` database |
| Database `atlas` | ✅ | Role `atlas` created |
| Schemas | ✅ | `system`, `knowledge`, `memory`, `scheduler`, `audit` |
| Ollama | ✅ Installed | v0.21.0 — not currently running |
| Python | ✅ | 3.12.3 |
| Package skeleton | ✅ Partial | Empty `atlas/` package with module stubs |
| `config/defaults.yaml` | ✅ | Initial config structure exists |

### Needs Work ⚠️

| Item | Current State | Target State |
|------|---------------|--------------|
| **Repo cleanliness** | Data dirs still inside `/data/atlas` | Code-only repo; all runtime data under `/data/atlas_data` |
| **Dependency manager** | Empty `pyproject.toml`, empty `requirements.txt` | `uv` with lock file |
| **Application code** | Only empty `__init__.py` stubs | Sprint 1 modules |
| **Database migrations** | Manual SQL executed; no migration runner | Versioned SQL migrations + Python runner |
| **Foundation tables** | Schemas exist; no business tables yet | `system.*`, `audit.*`, `scheduler.*` tables |
| **Secrets management** | DB password in `defaults.yaml` | Environment variable overrides |
| **Documentation** | Empty `README.md` | Project docs as we build |
| **`.gitignore`** | Minimal | Comprehensive ignore rules |
| **`public` schema** | Still owned by `pg_database_owner` | Effectively unused; Atlas objects only in named schemas |

### Environment Snapshot

```
PostgreSQL : 18.4
Ollama     : 0.21.0 (client; service not running)
Python     : 3.12.3
uv         : not yet installed
```

---

## 3. Core Principles

These principles should guide every implementation decision.

### 3.1 Knowledge-Centric, Not Model-Centric

```
Knowledge → Memory → Reasoning → Model
```

Most AI projects invert this stack. Atlas puts durable knowledge first so it ages well as models improve.

### 3.2 Configuration-Driven → Service-Oriented → Database-Backed

The database is **one service among many**, not the center of the application.

```
Configuration Driven
        ↓
Service Oriented
        ↓
Database Backed
```

Tomorrow we may add Redis, Neo4j, Milvus — each should look identical to the application via the service registry.

### 3.3 Kernel Abstraction & Strict Layering

Agents never touch PostgreSQL, Ollama, the browser, or the filesystem directly. They always go through **Kernel APIs**.

```
Agent
  ↓
Kernel APIs
  ↓
Providers (Ollama / vLLM / llama.cpp, embedding backends, ...)
  ↓
Infrastructure (PostgreSQL, filesystem, network)
```

If Ollama is replaced with vLLM or llama.cpp, **no agent code changes** — the provider layer absorbs it.

**Data access follows the repository pattern** (ADR-0027). Agents never issue SQL or touch an ORM:

```
Agent
  ↓
Memory API   /   Knowledge API
  ↓
Repositories        ← the ONLY layer that knows SQL
  ↓
PostgreSQL
```

#### Anti-pattern to avoid

```
❌  Agent → Ollama → PostgreSQL → filesystem → browser
❌  Agent → SQLAlchemy / raw SQL
```

```
✅  Agent → Kernel APIs → Providers → Infrastructure
✅  Agent → Memory/Knowledge API → Repositories → PostgreSQL
```

Agents should never know *how* work is done — only *what* they want.

### 3.4 Event-Driven Internal Communication

Services communicate through events, not direct method calls:

```
DocumentImported → EventBus → EmbeddingService → EmbeddingCompleted → KnowledgeIndexer → SearchIndexUpdated
```

Benefits: crash recovery, checkpointing, observability, loose coupling.

### 3.5 PostgreSQL as Operating System

PostgreSQL is not merely storage — it is Atlas' **brain**:

```
                 Atlas Brain
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
 Long-term      Working         Operational
  Memory         Memory            State
```

### 3.6 UUIDs Everywhere

No integer auto-increment IDs. Every entity (document, chunk, task, agent run) gets a UUID from day one.

### 3.7 Microkernel: Small and Stable

Like a microkernel OS, the Atlas kernel does the minimum and nothing more:

- startup / shutdown (lifecycle)
- configuration
- dependency injection
- plugin loading
- event bus
- scheduler startup

Everything else — memory, knowledge, embeddings, browsers, databases as *capabilities* — lives **outside** the kernel as services or plugins. This keeps the kernel stable for years while the ecosystem around it changes freely. Adding a new agent or plugin in five years must not require changing the core.

---

## 4. Target Architecture

### High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        python run.py                        │
│                     (Bootstrap / Entry)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      Atlas Kernel                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │  Config  │ │  Logger  │ │ EventBus │ │ Service       │  │
│  │  Manager │ │  Manager │ │          │ │ Registry      │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Database │ │Scheduler │ │  Memory  │ │ Health        │  │
│  │ Manager  │ │          │ │  Manager │ │ Monitor       │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │PostgreSQL│    │  Ollama  │    │  File    │
    │  (Brain) │    │  (LLM)   │    │  System  │
    └──────────┘    └──────────┘    └──────────┘
                           │
                           ▼
                    ┌──────────┐
                    │  Agents  │  (future sprints)
                    └──────────┘
```

### Bootstrap Sequence

When `python run.py` starts:

```
1. Load Config
2. Initialize Logger
3. Initialize PostgreSQL (connection pool)
4. Run pending migrations
5. Initialize State Manager
6. Initialize Event Bus
7. Initialize Scheduler
8. Initialize Ollama client
9. Health Check (all services)
10. Start Services
11. Ready
```

This mirrors how PostgreSQL itself starts — deterministic, ordered, observable.

### Dependency Order (Module Build Sequence)

```
Configuration
     ↓
Logger
     ↓
Database
     ↓
Bootstrap / Kernel
     ↓
Scheduler
     ↓
Knowledge
     ↓
Agents
```

Everything depends on Configuration. Nothing depends on Agents.

---

## 5. Directory Structure

### Target: `/data/atlas` (Repository — Code Only)

The package is organized by the four layers (kernel → services → plugins → agents),
plus supporting layers (repositories, providers, events).

```
atlas/
├── atlas/                    # Python package  (as-built through Sprint 9)
│   ├── config/               # Configuration (loaded once, injected everywhere) ✅
│   │   └── manager.py        # AtlasConfig + all *Config models (env overrides, secrets)
│   │
│   ├── kernel/               # THE MICROKERNEL — small & stable ✅
│   │   ├── application.py    # Atlas application object (the running system)
│   │   ├── bootstrap.py      # Ordered startup: builds & wires every service/plugin/agent
│   │   ├── lifecycle.py      # start / stop / shutdown hooks, signal handling
│   │   ├── registry.py       # Service registry (register / resolve)
│   │   ├── capabilities.py   # Capability Registry (ADR-0040)
│   │   ├── tools.py          # ToolRegistry (ADR-0050) — named invokable actions
│   │   └── service_container.py  # Dependency injection container
│   │
│   ├── models/               # DOMAIN MODELS (ADR-0036) — typed, not raw dicts ✅
│   │   ├── base.py           # Model base (from_row / from_rows / to_dict)
│   │   ├── document.py       # Document, Chunk, Embedding
│   │   ├── agent_run.py      # AgentRecord, AgentRun, AgentStep
│   │   ├── task.py  health.py  memory.py
│   │
│   ├── exceptions/           # TYPED EXCEPTIONS (ADR-0037) ✅
│   │   ├── base.py           # AtlasError root
│   │   ├── config.py  database.py  llm.py  knowledge.py  agent.py
│   │   └── plugin.py         # PluginError + ToolError / ToolNotFoundError
│   │
│   ├── interfaces/           # ABSTRACT PROTOCOLS (ADR-0038) ✅
│   │   ├── llm.py            # LLMProvider + EmbeddingProvider
│   │   ├── memory.py         # MemoryProvider
│   │   └── storage.py        # repository/storage abstractions
│   │
│   ├── telemetry/            # OBSERVABILITY (ADR-0039) ✅
│   │   ├── metrics.py        # counters / gauges / histograms + snapshot()
│   │   ├── prometheus.py     # render_prometheus(snapshot) (ADR-0054) — Sprint 9
│   │   ├── tracing.py        # spans across the pipeline
│   │   └── timers.py         # @timed decorator / timer() context manager
│   │
│   ├── events/               # Event system (in-process) ✅
│   │   ├── event.py  dispatcher.py  handlers.py  subscriptions.py
│   │
│   ├── services/             # SYSTEM SERVICES (lifecycle: start/stop/health) ✅
│   │   ├── base.py           # Service protocol + HealthStatus
│   │   ├── health.py         # HealthMonitor
│   │   ├── database_service.py  # DatabaseManager wrapper (pool + health)
│   │   ├── agent_service.py  # agent catalog + run(); persists agent records
│   │   └── memory_service.py # MemoryService (MemoryProvider) + prune task
│   │
│   ├── llm/                  # LLM access + provider (providers/ folded in here) ✅
│   │   ├── service.py        # LLMService (generate / chat / embed, timed)
│   │   ├── provider.py       # provider protocol
│   │   └── ollama_provider.py  # OllamaProvider (+ OllamaError : LLMError)
│   │
│   ├── knowledge/            # RAG knowledge layer ✅
│   │   ├── service.py        # KnowledgeService (ingest / search)
│   │   └── chunking.py       # chunker
│   │
│   ├── ingestion/            # Document ingestion ✅
│   │   ├── filesystem_source.py  # scheduled folder scan (self-re-enqueue)
│   │   └── extractors.py     # text/html/pdf → text (+ shared html_to_text)
│   │
│   ├── repositories/         # The ONLY layer that knows SQL ✅
│   │   ├── base.py  settings_repo.py  task_repo.py  event_repo.py
│   │   ├── document_repo.py  chunk_repo.py  embedding_repo.py
│   │   ├── agent_run_repo.py  health_repo.py  memory_repo.py
│   │
│   ├── plugins/              # PLUGINS — external integrations (ADR-0041/0049) ✅
│   │   ├── base.py           # Plugin protocol + BasePlugin
│   │   ├── manager.py        # PluginManager (config-driven load + lifecycle)
│   │   ├── filesystem_plugin.py  # fs.list / fs.read (sandboxed) — Sprint 7
│   │   ├── web_plugin.py     # web.fetch (via net layer)         — Sprint 7 / S13a
│   │   ├── search_plugin.py  # web.search (SearchCapability, D5)  — Stage 2 S13b
│   │   ├── downloader_plugin.py  # web.download (net layer)       — Stage 2 S13b
│   │   ├── scholar_plugin.py # scholar.search (arXiv/S2)          — Stage 2 S18a
│   │   ├── youtube_plugin.py # youtube.transcript                — Stage 2 S18a
│   │   └── git_plugin.py     # git.status/log/diff/… (read-only)  — Stage 2 S20a
│   │
│   ├── agents/               # AGENTS — orchestrate services + tools ✅
│   │   ├── base.py           # AgentResult / Citation
│   │   ├── rag_agent.py      # RagAgent (retrieval + cited answer)
│   │   └── react_agent.py    # ReActAgent "assistant" (ADR-0051/0052) — Sprint 8
│   │
│   ├── capabilities/         # TYPED CAPABILITY CONTRACTS (Stage 2 S11) ✅
│   │   └── contracts.py      # runtime_checkable Protocols + ids + CAPABILITY_CATALOG
│   │
│   ├── conversation/         # Conversation sessions + context (Stage 2 S10) ✅
│   │   └── service.py        # ConversationService (session/history/context)
│   │
│   ├── planner/              # Deterministic intent router (Stage 2 S10) ✅
│   │   └── planner.py        # Planner v0 (Intent/Plan/PlanStep, canonical cap ids)
│   │
│   ├── execution/            # Tool execution (Stage 2 S10) ✅
│   │   └── executor.py       # ToolExecutor + ToolResult (validate/retry/structured)
│   │
│   ├── jobs/                 # JOB ENGINE (Stage 2 S12) ✅
│   │   ├── planner.py        # JobPlanner (deterministic + planner-role LLM decomposition)
│   │   └── service.py        # JobService (advance_job loop, blocked/resume/recovery)
│   │
│   ├── documents/            # DOCUMENT READER (Stage 2 S13a) ✅
│   │   └── service.py        # DocumentService (document cap; 9 formats, outcome-classified)
│   │
│   ├── net/                  # RESILIENT NET LAYER (Stage 2 S13a, D10/§5c) ✅
│   │   └── client.py         # FetchClient (throttle/robots/backoff/cache; ok/blocked/skipped)
│   │
│   ├── search/               # WEB + SCHOLARLY SEARCH (Stage 2 S13b/S18a) ✅
│   │   ├── providers.py      # SearchProvider protocol + DuckDuckGoProvider (over net layer)
│   │   └── scholarly.py      # ScholarlyProvider + Arxiv/SemanticScholar (graded L3/L4 → Evidence Source)
│   │
│   ├── transcripts/          # VIDEO TRANSCRIPTS (Stage 2 S18a) ✅
│   │   └── youtube.py        # YouTubeTranscriptProvider (watch-page + timedtext scrape; L1)
│   │
│   ├── code/                 # CODE UNDERSTANDING (Stage 2 S14, D9 Tier B) ✅
│   │   ├── models.py         # Symbol/ImportRef/CallRef/FileParse/RepoMap/CodeGraph/Pattern
│   │   ├── languages.py      # extension→language map + v1 grammar set
│   │   ├── pyast.py          # Python parser (stdlib ast): symbols/imports/calls
│   │   ├── treesitter.py     # multi-language parser (tree-sitter): symbols/imports
│   │   ├── parser.py         # CodeParser (dispatch + honest outcomes)
│   │   ├── repomap.py        # repo map: manifests→deps/frameworks/entry points
│   │   ├── graph.py          # import + cross-file call graph (Python-first)
│   │   ├── patterns.py       # pattern mining (§5b.1 layer 6, feeds S19)
│   │   └── service.py        # CodeService (code cap; parse/map/index/graph/explain)
│   │
│   ├── evidence/             # EVIDENCE GRAPH (Stage 2 S15, D8/§5a) ✅
│   │   └── models.py         # Source/EvidenceItem/ClaimValue/Claim/EvidenceGraph (serialisable)
│   │
│   ├── verification/         # VERIFICATION ENGINE (Stage 2 S15, D8/§5a) ✅
│   │   ├── engine.py         # EvidenceBudget + convergence + calculated confidence + decide()
│   │   └── service.py        # VerificationService (verification cap; verify graph + budget)
│   │
│   ├── sandbox/              # PYTHON EXECUTION SANDBOX (Stage 2 S16, D6 hybrid) ✅
│   │   ├── models.py         # ExecutionResult (ok/error/timeout/blocked, result, artifacts)
│   │   ├── backends.py       # SandboxBackend + SubprocessBackend (rlimit/timeout/net-block) + DockerBackend
│   │   └── service.py        # PythonSandboxService (python cap; run/run_file)
│   │
│   ├── reports/              # REPORT GENERATOR (Stage 2 S17, §5a.5) ✅
│   │   ├── generator.py      # ReportGenerator (nine scientific-review sections, derived confidence, Markdown)
│   │   └── service.py        # ReportService (reports cap; verify→render + direct render)
│   │
│   ├── (learning)            # LEARNING PIPELINE (Stage 2 S18b, D11/§5d) ✅ — see services/learning_service.py
│   │   #   models/learning.py (LearningEvent/Experience + LearnedRepository/EngineeringPattern),
│   │   #   repositories/learning_repo.py + repositories/intelligence_repo.py,
│   │   #   services/learning_service.py (learning cap: observe/apply/revert/recall; sink registry — governed, reversible)
│   │
│   ├── intelligence/         # ENGINEERING INTELLIGENCE (Stage 2 S19, D11/§5d) ✅
│   │   └── service.py        # IntelligenceService (intelligence cap) + CodeStoreSink:
│   │                         #   learn_repository(L2)/search+connections(L3)/generalize(L4)/recommend+profile(L5)
│   │
│   ├── vcs/                  # VERSION CONTROL (Stage 2 S20a) ✅
│   │   └── git.py            # GitClient + CommandRunner/SubprocessRunner (read-only,
│   │                         #   network-free; status/log/diff/show/branches/file_history; honest outcomes)
│   │
│   ├── ops/                  # OPERATIONS (Sprint 9) ✅
│   │   └── backup.py         # BackupManager (pg_dump + retention, ADR-0055)
│   │
│   ├── api/                  # REST API (FastAPI, Sprint 5) ✅
│   │   ├── app.py            # create_app (lifespan, error handlers, CORS)
│   │   ├── server.py         # uvicorn serve()
│   │   ├── routes.py         # public /health /metrics + authed /v1/*
│   │   ├── auth.py           # require_api_key (Bearer, fail-closed)
│   │   └── schemas.py        # Pydantic request/response models
│   │
│   ├── cli/                  # `atlas` CLI (argparse, Sprint 5) ✅
│   │   └── main.py           # serve/status/chat/agents/ask/search/ingest/remember/recall/
│   │                         #   forget/plugins/tools/capabilities/jobs/job/formats/
│   │                         #   websearch/download/scholar/youtube/code/python/git/report/
│   │                         #   verify/learn/intel/tool/backup
│   │
│   ├── database/             # Connection manager + migration runner ✅
│   │   ├── connection.py  migrations.py  cli.py
│   │
│   ├── scheduler/            # Durable task workers (scheduler.* tables) ✅
│   │   ├── service.py  handlers.py
│   │
│   ├── utils/
│   │   └── logging.py        # Logger manager (rotating file logs) ✅
│   │
│   ├── core/                 # legacy stub — empty (kernel/ superseded it, ADR-0023)
│   └── memory/               # legacy stub — empty (see services/interfaces/repositories)
│
├── config/
│   └── defaults.yaml         # local.yaml optional + gitignored (not present)
├── database/
│   ├── migrations/           # 0001–0010 applied (0010 = job engine)
│   └── README.md
├── deploy/                   # DEPLOY ARTIFACTS (Sprint 9, ADR-0053) ✅
│   ├── systemd/atlas.service
│   ├── atlas.env.example
│   └── docker/               # Dockerfile + docker-compose.yml
├── scripts/
│   └── restore.sh            # pg_restore helper (ADR-0055)
├── docs/
│   └── IMPLEMENTATION_PLAN.md
├── tests/                    # 28 test modules, 275 tests
├── run.py
├── pyproject.toml   uv.lock   requirements.txt
├── .env / .env.example   .dockerignore   .gitignore
└── README.md
```

> **Note:** This tree is **as-built through Sprint 9** (not the original Sprint-1
> sketch). A few things diverged from the early plan, intentionally: `atlas/core/`
> and `atlas/memory/` are now-empty legacy stubs (the kernel and the
> memory service/interface/repository trio replaced them); the planned
> `providers/` layer was folded into `atlas/llm/`; and the many speculative
> `services/*_service.py` / `plugins/<name>/` entries were consolidated into the
> modules shown above. New layers `api/`, `cli/`, and `ops/` were added in
> Sprints 5 and 9.

### Target: `/data/atlas_data` (Runtime Data — Not in Git)

```
atlas_data/
├── backups/
├── cache/
├── checkpoints/        # Critical for outage recovery
├── documents/
├── embeddings/
├── knowledge/
├── logs/
├── models/
├── queues/
├── state/              # Runtime state for resume-after-crash
└── temp/
```

### Cleanup Task (Before Sprint 1.1)

Remove duplicate data directories from `/data/atlas`:

- `backups/`, `cache/`, `documents/`, `knowledge/`, `logs/`, `models/`, `state/`
- Decide fate of `experiments/` — move to atlas_data or delete

---

## 6. Technology Stack

### Agreed Decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12+ | Already installed; rich AI ecosystem |
| Dependency manager | **uv** | Fast, reproducible lock files, modern tooling |
| Database | PostgreSQL 18.4 | Latest major release; schemas, extensions, reliability |
| Vector search | pgvector | Installed day one to avoid future migration |
| LLM runtime | Ollama 0.21.0 | Local inference; model-agnostic via kernel |
| Migrations | Plain SQL + custom Python runner | Full PG feature support; no ORM lock-in |
| Config format | YAML → typed Python object | Single loader; nobody reads YAML elsewhere |
| IDs | UUID v4 (via pgcrypto) | Sync-friendly; no integer collisions |

### Development Commands (Target)

```bash
uv sync                  # Install dependencies
uv run pytest            # Run tests
uv run python run.py     # Start Atlas
uv run atlas migrate     # Run database migrations (future CLI)
```

### Python Dependencies (Proposed — To Discuss)

| Package | Purpose | Sprint |
|---------|---------|--------|
| `pyyaml` | Config loading | 1.1 |
| `pydantic` | Config validation & typed objects | 1.1 |
| `psycopg[binary,pool]` | PostgreSQL driver + pooling | 1.4 |
| `python-dotenv` | `.env` file support for secrets | 1.1 |

> **Discussion:** Do we want `pydantic` for config validation, or a lighter custom validator? Recommendation: **use pydantic**.

---

## 7. Database Design

### 7.1 Schema Domains

```
atlas (database)
├── system        ← Sprint 1 (foundation)
├── audit         ← Sprint 1 (foundation)
├── scheduler     ← Sprint 1 (foundation)
├── memory        ← Sprint 2
├── knowledge     ← Sprint 2
├── ingestion     ← Sprint 3
├── agents        ← Sprint 3
├── llm           ← Sprint 2
├── browser       ← Sprint 4+
├── security      ← Sprint 4+
└── analytics     ← Future
```

Phase 1 (already created): `system`, `knowledge`, `memory`, `scheduler`, `audit`

> **Future schema separation (ADR-0028):** As Atlas grows, agent state should get
> its own **`agent`** schema (agent definitions, runs, state) rather than living
> in `system`. Target long-term schema set: `system`, `knowledge`, `memory`,
> `scheduler`, `audit`, `agent` (+ `ingestion`, `llm`, `browser`, `security`,
> `analytics` as needed). No rush — created when the agent layer lands.

### 7.2 Extensions

| Extension | Status | Purpose |
|-----------|--------|---------|
| `pgcrypto` | To install | UUID generation |
| `vector` (pgvector) | ✅ Installed | Embeddings (future) |
| `pg_trgm` | Future | Fuzzy text search |
| `unaccent` | Future | Natural language search |
| `btree_gin` | Future | Hybrid indexes |

### 7.3 Foundation Tables (Sprint 1.4)

#### `system` schema

| Table | Purpose |
|-------|---------|
| `system.settings` | Key-value system configuration |
| `system.migrations` | Migration history tracking |
| `system.services` | Registered service status |
| `system.health` | Last health check results |

#### `audit` schema

| Table | Purpose |
|-------|---------|
| `audit.events` | Domain events (Event Bus persistence) |
| `audit.logs` | Structured application log entries |

#### `scheduler` schema

| Table | Purpose |
|-------|---------|
| `scheduler.tasks` | Task definitions |
| `scheduler.task_runs` | Individual execution records with state |

### 7.4 Task Model (Linux-Inspired)

```
Task → UUID → State → Scheduler → Result
```

Task states: `pending → claimed → running → completed | failed | cancelled`

### 7.5 Migration Strategy

```
database/migrations/
    0001_extensions_and_schemas.sql
    0002_system_foundation.sql
    0003_audit_foundation.sql
    0004_scheduler_foundation.sql
```

Migration runner: read applied from `system.migrations`, apply pending in order, record checksum, fail fast.

> **Discussion:** Migration 0001 should be idempotent (`IF NOT EXISTS`) since schemas already exist manually.

### 7.6 `public` Schema Policy

Recommend **both**: revoke CREATE on `public` from `atlas` role + set `search_path = system, knowledge, memory, scheduler, audit`.

---

## 8. Atlas Kernel (Microkernel)

### 8.1 Kernel Package Layout (ADR-0023)

The kernel evolves from the current `core/` stub into a dedicated `atlas/kernel/` package:

```
atlas/kernel/
    application.py        # The running Atlas application object
    bootstrap.py          # Ordered startup sequence
    lifecycle.py          # start / stop / shutdown, signal handling
    registry.py           # Service registry (register / resolve)
    service_container.py  # Dependency injection container
```

### 8.2 Kernel Responsibilities — and ONLY these

The microkernel is responsible for exactly:

- **startup / shutdown** (lifecycle)
- **configuration**
- **dependency injection** (service container)
- **plugin loading**
- **event bus**
- **scheduler startup**

Nothing else. It does **not** know about documents, embeddings, browsers, or how
the LLM works. Those are services and plugins that the kernel merely wires together.

### 8.3 Kernel-Managed Components

| Component | Responsibility | Layer | Status |
|-----------|---------------|-------|--------|
| Config Manager | Load, validate, expose typed config | kernel | ✅ done |
| Service Container | Dependency injection | kernel | Sprint 1.5 |
| Service Registry | Register / resolve services | kernel | Sprint 1.5 |
| Event Dispatcher | Publish / subscribe (in-process) | kernel/events | Sprint 1.5 |
| Lifecycle | start / stop / shutdown hooks | kernel | Sprint 1.5 |
| Plugin Loader | Discover + register plugins | kernel | Sprint 3+ |
| Logger Manager | Structured logging | utils | next |
| Database Manager | Connection pool, health check | infra | ✅ done |
| Scheduler | Task queue + workers | service | 2.x |
| Health Monitor | Periodic service health checks | service | Sprint 1.5 |

### 8.4 Usage Pattern

```python
# Agents never do this:
# conn = psycopg.connect(...)
# response = ollama.generate(...)

# Agents always do this — through Kernel APIs:
knowledge = kernel.knowledge.search(query="...")
llm       = kernel.llm.generate(prompt="...")
task      = kernel.scheduler.enqueue("embed_document", document_id=doc_id)
result    = kernel.plugins.browser.search("...")
```

### 8.5 Service Interface

```python
class Service(Protocol):
    name: str
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health_check(self) -> HealthStatus: ...
```

> **Decision (ADR-0002 area):** Start **sync**, design interfaces so an async
> implementation can be swapped in later without changing callers.

### 8.6 System Services Taxonomy (ADR-0026)

Services are *capabilities*, distinct from infrastructure. Planned services:

| Service | Purpose | Sprint |
|---------|---------|--------|
| `LLMService` | Text generation via a provider (Ollama today) | 2 |
| `EmbeddingService` | Produce embeddings | 2 |
| `MemoryService` | Working + long-term memory access | 2 |
| `KnowledgeService` | Search / retrieval entrypoint | 2 |
| `ChunkingService` | Split documents into chunks | 3 |
| `OCRService` | Extract text from images/PDFs | 3 |
| `DocumentService` | Document lifecycle | 3 |
| `SearchService` | Hybrid search over knowledge | 3 |
| `RankingService` | Re-rank retrieval results | 4 |

Each service depends only on the kernel, repositories, and providers — never on agents or plugins.

### 8.7 Plugin System (ADR-0024)

Plugins are external capabilities (browser, filesystem, GitHub, email, shell,
SCADA, cloud APIs). They live under `atlas/plugins/` and **self-register with the
kernel** at load time rather than being hard-wired into agents.

```python
# plugins/base.py (shape)
class Plugin(Protocol):
    name: str
    version: str
    def register(self, kernel: "Kernel") -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health_check(self) -> HealthStatus: ...
```

Why a plugin layer: adding a new integration (e.g. Solar SCADA, Azure, Docker) in
five years must not require touching the kernel or existing agents — the plugin
registers itself and becomes available via `kernel.plugins.<name>`.

### 8.8 Repositories (ADR-0027)

The **only** layer permitted to contain SQL. Services and APIs call repositories;
repositories use the `DatabaseManager`. This keeps SQL out of agents and services
and makes the storage engine swappable.

```
Service / API  →  Repository  →  DatabaseManager  →  PostgreSQL
```

---

## 9. Event-Driven Architecture

### 9.1 Why Events from Day One

Power and internet outages make event-driven recovery natural:

1. Event occurs → persisted to `audit.events`
2. Crash happens
3. On restart, scheduler scans pending/failed tasks
4. Work resumes from last checkpoint

### 9.2 Event Flow Example (Future)

```
DocumentImported → audit.events → EmbeddingService → EmbeddingCompleted → KnowledgeIndexer → SearchIndexUpdated
```

### 9.3 Events Package Layout (ADR-0025)

The event system lives in its own package from day one, so nothing has to move later:

```
atlas/events/
    event.py          # Event base type / envelope (type, payload, source, id, ts)
    dispatcher.py     # Publish / dispatch — the in-process "event bus"
    handlers.py       # Handler base class + built-in handlers
    subscriptions.py  # Subscription registry: event_type → [handlers]
```

### 9.4 Event Bus Phasing

- **Sprint 1.5 (in-process only — ADR-0012):** `dispatcher.publish()` calls
  subscribed handlers synchronously in-process. No DB persistence yet.
- **Later (only when distributed processing is actually needed):** optional
  DB-backed persistence via `audit.events` for replay/recovery. The package
  layout above already anticipates this, so it is an additive change.

### 9.5 Event Schema (for the future DB-backed phase)

```sql
audit.events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    payload      JSONB NOT NULL,
    source       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'pending'
)
```

---

## 10. Resilience & Recovery

This directly addresses your concern about power and internet outages.

### 10.1 Requirements

| Scenario | Expected Behavior |
|----------|-------------------|
| Power loss mid-task | Task marked failed/interrupted; retried on restart |
| Internet outage | Local LLM (Ollama) continues; network tasks queued |
| Internet returns | Queued tasks resume automatically |
| Process crash | Bootstrap detects incomplete state; scheduler recovers |
| Database restart | Connection pool reconnects; health check validates |
| Full system reboot | Bootstrap → migrations → health → resume |

### 10.2 Recovery Layers

```
1. Checkpoint files  (/data/atlas_data/checkpoints/)
2. Task state in DB  (scheduler.tasks/runs)
3. Event log         (audit.events)
4. Config persistence (system.settings)
5. File state dir    (/data/atlas_data/state)
```

### 10.3 Scheduler Recovery Flow

```
System starts → Bootstrap → DB connected → Scan interrupted tasks
→ Mark as failed/retry → Resume processing
```

### 10.4 Systemd Integration (Future)

Defer to Sprint 2 — get bootstrap solid first, then wrap in systemd for auto-start after reboot.

---

## 11. Sprint 1 — Foundation (Detailed)

```
Sprint 1.0  Project Setup (uv, cleanup, gitignore)
Sprint 1.1  Configuration Manager
Sprint 1.2  Logging
Sprint 1.3  Atlas Kernel + Event Bus + Service Registry
Sprint 1.4  Database Foundation (migrations, connection manager)
```

---

### Sprint 1.0 — Project Setup

| Task | Details |
|------|---------|
| Install `uv` | System-wide or via pipx |
| Initialize `pyproject.toml` | Project metadata, dependencies, scripts |
| Comprehensive `.gitignore` | Python, data, secrets, IDE files |
| Remove duplicate data dirs | Clean `/data/atlas` to code-only |
| Move secrets out of YAML | DB password → env var / `.env` file |
| Create `run.py` stub | Entry point |
| Create `VERSION` file | `0.1.0` |
| Verify `uv sync` works | Install deps, create venv |

**Deliverable:** `uv sync && uv run python run.py` prints a startup message.

---

### Sprint 1.1 — Configuration Manager

**File:** `atlas/config/manager.py` → `AtlasConfig`

```
defaults.yaml → Loader → Validator → AtlasConfig → every module
```

- Load `config/defaults.yaml`
- Environment variable overrides (`ATLAS_DB_HOST`, etc.)
- Validate all fields with pydantic
- Typed access: `config.system.name`, `config.database.host`
- Singleton: `from atlas.config import config`
- Optional `config/local.yaml` (gitignored)

---

### Sprint 1.2 — Logging

**File:** `atlas/utils/logging.py` → `LoggerManager`

- Console + rotating file output (10MB × 5 files)
- Level from config
- `from atlas.utils.logging import get_logger`

---

### Sprint 1.3 — Atlas Kernel

**Files:** `kernel.py`, `bootstrap.py`, `events.py`, `registry.py`, `health.py`

- Ordered bootstrap sequence
- Service Registry with lifecycle
- In-process Event Bus
- Graceful shutdown (SIGINT/SIGTERM)
- `run.py` invokes bootstrap

---

### Sprint 1.4 — Database Foundation

- Migration runner + SQL files
- Connection pool via psycopg
- Foundation tables (system, audit, scheduler)
- pgcrypto extension
- `search_path` + revoke CREATE on `public`

---

### Sprint 1 Completion Criteria

```bash
uv sync
uv run python run.py
```

Expected output:

```
[INFO] Atlas v0.1.0 starting...
[INFO] Config loaded (system: Atlas, db: localhost:5432/atlas)
[INFO] Logger initialized
[INFO] Running database migrations... (4 applied, 0 pending)
[INFO] Database connected (pool: 5 connections)
[INFO] Event bus initialized
[INFO] Health check: ALL OK
[INFO] Atlas is ready.
```

---

## 12. Future Sprints (Preview)

> **Revised order (ADR-0044, 2026-07-11).** Interface first: once Atlas has an
> official API/CLI, everything after it becomes easier to build, test, and use.
> Cross-cutting foundations (models, exceptions, interfaces, telemetry, capability
> registry — see §18) are introduced **incrementally alongside** these sprints,
> before the codebase reaches ~20–30k lines.

| Sprint | Focus | Key Deliverables | Status |
|--------|-------|-----------------|--------|
| **Sprint 1** | Foundation | config, logging, database, kernel, events, bootstrap | ✅ done |
| **Sprint 2** | Knowledge Foundation | document/chunk/embedding tables, scheduler workers, Ollama | ✅ done |
| **Sprint 3** | Agent Layer & RAG | agent schema, RAG agent, ingestion source (text/md/pdf/html) | ✅ done |
| **Sprint 4** | Foundations Hardening | `models/`, `exceptions/`, provider interfaces, `telemetry/`, capability registry (§18) | ✅ done |
| **Sprint 5** | REST API + CLI + Auth | official interface to Atlas; authentication; the RAG agent over HTTP/CLI | ✅ done |
| **Sprint 6** | Memory System | working/episodic/semantic memory (`memory.items`, single-table + partial HNSW) | ✅ done |
| **Sprint 7** | Plugins | config-loaded plugins + ToolRegistry; filesystem + web (github/db/email deferred) | ✅ done |
| **Sprint 8** | Multi-Agent | ReAct assistant + reflection over the ToolRegistry; agents-as-tools delegation | ✅ done |
| **Sprint 9** | Operations | systemd unit + Docker/compose; Prometheus + JSON metrics; scheduled pg_dump backups + restore | ✅ done |
| **Stage 2 →** | Research, Execution & Continuous Learning System | Stage 1 (the OS) is complete; Stage 2 evolves Atlas into a research/execution assistant **and a Continuous Engineering Intelligence System** that learns cumulatively (D11). **See `docs/STAGE_2_PLAN.md`** for the S10–S20 arc, decisions, and progress. | 🟢 building |
| **Sprint 10** | Conversation & Planner Spine | LLM **roles** + single lane (D7/R4); `conversation` schema (migration 0009); deterministic Planner; ToolExecutor; `AssistantService` + `POST /v1/chat` + `atlas chat`; capability-gap pre-flight (R2). Chat Mode 5-test acceptance passing. Web UI re-slotted later in the Stage 2 arc. | ✅ done |
| **Sprint 11** | Capability Contracts | typed `runtime_checkable` contracts + capability catalog (`atlas/capabilities/`); registry `contract`/`verify`/`missing`; services + plugins declare contracts; planner uses canonical ids; registry-driven, catalog-enriched gap pre-flight (R2); `GET /v1/capabilities` + `atlas capabilities`. 285 tests. | ✅ done |
| **Sprint 12** | Job Engine | migration 0010 (`job.jobs` + `job.steps`); `Job`/`JobStep` models + `JobRepository`; `JobPlanner` (deterministic + planner-role LLM decomposition, D2c); `JobService` — self-re-enqueuing `advance_job` task → concurrent jobs (R1), sequential steps (Q1), non-blocking `blocked`/`skipped` + cascade (R3), resume/cancel, reboot recovery (Q10); reuses chat dispatch via `AssistantService.run_step`; `/v1/jobs*` + `atlas jobs`/`atlas job`. 312 tests. | ✅ done |
| **Sprint 13a** | Document Reader + Net | extractors expanded to pdf/docx/pptx/xlsx/csv/md/txt/html/json; `atlas/documents/DocumentService` (`document` capability, outcome-classified); `atlas/net/FetchClient` (throttle + robots + backoff/retry + cache, outcomes ok/blocked/skipped/error, D10/§5c); `WebPlugin` rewired; `net.*` config; `GET /v1/documents/formats` + `atlas formats`. 343 tests. | ✅ done |
| **Sprint 13b** | Web Search + Downloader | `atlas/search/` (`SearchProvider` + `DuckDuckGoProvider`, D5) + `SearchPlugin` (`search` cap, `web.search`, ordered provider fallback); `DownloaderPlugin` (`downloader`, `web.download`, sandboxed dir); planner `web_search` intent + `AssistantService._do_web_search` + `JobPlanner` support; `POST /v1/search` + `atlas websearch`/`download`; `plugins.search`/`plugins.downloader` config. 370 tests. | ✅ done |
| **Sprint 14** | Code Understanding (Tier B) | `atlas/code/`: Python `ast` parser (symbols/imports/calls) + tree-sitter multi-language parser; repo map (deps/frameworks/entry points); symbol index; import + cross-file call graph (Python-first); pattern mining; `CodeService` (`code` capability) with code-aware RAG ingest + `code`-role grounded `explain`; concrete `CodeCapability` contract; `POST /v1/code/*` + `atlas code …`; `code.*` config; deps `tree-sitter`+`tree-sitter-language-pack`. 421 tests. | ✅ done |
| **Sprint 15** | Verification + Evidence Graph | `atlas/evidence/` (serialisable Claim/Source/EvidenceItem/EvidenceGraph, re-verifiable) + `atlas/verification/` (Evidence Levels L1–L5, `convergence()`, calculated confidence + reasoning trace, Evidence Budget + `decide()`); `VerificationService` (`verification` capability); `research.*` config; `POST /v1/verify` + `atlas verify` (D8/§5a). 444 tests. | ✅ done |
| **Sprint 16** | Python Execution Sandbox | `atlas/sandbox/`: `SandboxBackend` (D6 hybrid) — `SubprocessBackend` (rlimit CPU/mem/file + timeout→killpg + scratch dir + stripped env + net block) default, `DockerBackend` swappable; `ExecutionResult` (ok/error/timeout/blocked, result.json, artifacts); `PythonSandboxService` (`python` capability); `run_python` planner intent + dispatch; `PythonExecutionCapability`; `sandbox.*` config; `POST /v1/python/run` + `atlas python`. 478 tests. | ✅ done |
| **Sprint 17** | Non-blocking HITL & Report Generator | `atlas/reports/`: `ReportGenerator` (§5a.5 nine-section scientific-review report from verified claims; derived overall confidence; conflicting-views/next-research; optional summarizer-LLM polish; Markdown) + `ReportService` (`reports` capability: verify→render). `JobService` attaches a report on finalize + `list_blocked()` HITL queue + `job.step_blocked`/`job.finalized` notifications (R3). `POST /v1/report` + `GET /v1/jobs/blocked`; `atlas report` + `atlas jobs --blocked`. 497 tests. | ✅ done |
| **Sprint 18a** | Deeper Research Sources | `atlas/search/scholarly.py` (`ScholarlyProvider` → graded `Paper`/`Source`; `ArxivProvider` L3 + `SemanticScholarProvider` L4) + `ScholarPlugin` (`scholar` cap, `scholar.search`, provider fallback); `atlas/transcripts/` (`YouTubeTranscriptProvider` L1) + `YouTubePlugin` (`transcript` cap, `youtube.transcript`); planner `scholar_search`/`youtube_transcript` intents + `AssistantService` handlers + `JobPlanner`; `ScholarCapability`/`TranscriptCapability`; `plugins.scholar`/`plugins.youtube` config; `POST /v1/scholar` + `/v1/youtube/transcript`; `atlas scholar`/`youtube`. 532 tests. | ✅ done |
| **Sprint 18b** | Learning Pipeline | migration 0011 `learning` schema (`events` ledger + `experiences` store); `models/learning.py` (`LearningEvent`/`Experience`) + `LearningRepository`; `LearningService` (`learning` cap: `observe_job`/`apply`/`revert`/`remember_experience`/`recall`/`explain`; governed **proposed→applied→reverted**, never-silent, reversible; Experience store problem→…→lessons); concrete `LearningCapability`; `JobService` observes on finalize; `LearningConfig` + `learning:` defaults; `/v1/learning/*` + `atlas learn`. 555 tests. | ✅ done |
| **Sprint 19** | Engineering Intelligence | migration 0012 Code store (`learning.repositories` + `learning.patterns`); `LearnedRepository`/`EngineeringPattern` + `IntelligenceRepository`; **`LearningService` store-sink registry** (`register_sink`/`propose`) + `CodeStoreSink` (governed promotion into non-Experience stores); `IntelligenceService` (`intelligence` cap): L2 `learn_repository`, L3 `search`+`connections`, L4 `generalize`, L5 `recommend`+`profile`; `IntelligenceCapability` (`CAP_INTELLIGENCE`); `intelligence.*` config; `/v1/intelligence/*` + `atlas intel`. 573 tests. | ✅ done |
| **Sprint 20a** | Git (read-only) | `atlas/vcs/git.py` `GitClient` + injectable `CommandRunner`/`SubprocessRunner` (read-only, timeout-bounded, honest outcomes, pure parsers); `GitPlugin` (`git` cap: `status`/`log`/`diff`/`show`/`branches`/`file_history`); `GitCapability` (`CAP_GIT`); `plugins.git.*` config; planner `git_status` intent + `_do_git` + `JobPlanner`; `POST /v1/git` + `atlas git`. 598 tests. | ✅ done |

> **Note.** The old table had Memory→Agents→API→Browser→Ops. The new order (API →
> Memory → Plugins → Multi-agent → Ops) reflects ADR-0044. Sprint 4 is a dedicated
> "foundations hardening" pass so the cross-cutting concerns land before feature
> sprints build on raw dicts / generic exceptions / untyped providers.
>
> **Stage 2 (from Sprint 10 on)** is tracked in `docs/STAGE_2_PLAN.md`, which owns the
> living roadmap, decisions (D1–D10), and requirements (R1–R4). The old "Sprint 10 =
> Web UI" is re-slotted into that arc; Sprint 10 is now the Conversation & Planner
> Spine (the Chat-Mode vertical slice).

---

## 13. Open Questions for Discussion

Please review and share your preferences before we start coding.

### Architecture

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| A1 | Config validation library? | pydantic / custom / dataclasses | **pydantic** |
| A2 | Sync or async for Sprint 1? | sync / async / sync-with-async-ready | **sync-with-async-ready** |
| A3 | Event Bus Phase 1 scope? | in-process only / in-process + DB | **in-process only** (no DB persistence until needed) |
| A4 | Enforce `public` schema unused? | revoke CREATE / search_path / both | **both** |
| A5 | `config/local.yaml` for overrides? | yes / no | **yes** (gitignored) |

### Security

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| S1 | Where to store DB password? | env var / `.env` file / secret manager | **`.env` file** (gitignored) |
| S2 | Secrets in `defaults.yaml`? | never / dev placeholders | **never** |
| S3 | Audit log retention? | 30 / 90 / unlimited days | **discuss — start 90** |

### Operations

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| O1 | Systemd in Sprint 1? | yes / no | **no — Sprint 2** |
| O2 | Auto-start Ollama? | yes / no / check-only | **check-only** |
| O3 | Log rotation size? | 5MB / 10MB / 50MB | **10MB × 5** |
| O4 | Checkpoint interval? | 30 / 60 / 120 sec | **60** (in defaults.yaml) |

### Database

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| D1 | Migration 0001 idempotent? | yes / no | **yes** |
| D2 | Task retry policy? | fixed / exponential / manual | **3 retries, exponential backoff** |
| D3 | Connection pool size? | 5 / 10 / configurable | **configurable, default 5** |

### Project

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| P1 | `/data/atlas/experiments/`? | move / delete / keep | **delete** ✅ |
| P2 | Separate `atlas/services/` from domain modules? | yes / merge | **yes** |
| P3 | Testing framework? | pytest / unittest | **pytest** |
| P4 | Type checking in Sprint 1? | mypy / pyright / none | **none — add Sprint 2** |

---

## 14. Decision Log

| ID | Date | Decision | Status |
|----|------|----------|--------|
| ADR-0001 | 2026-07-06 | PostgreSQL as Atlas' operating system | ✅ Accepted |
| ADR-0002 | 2026-07-06 | UUIDs for all entity IDs | ✅ Accepted |
| ADR-0003 | 2026-07-06 | Schema-separated database domains | ✅ Accepted |
| ADR-0004 | 2026-07-06 | Hybrid SQL migration strategy | ✅ Accepted |
| ADR-0005 | 2026-07-06 | uv for dependency management | ✅ Accepted |
| ADR-0006 | 2026-07-06 | Atlas Kernel abstraction layer | ✅ Accepted |
| ADR-0007 | 2026-07-06 | Event-driven internal architecture | ✅ Accepted |
| ADR-0008 | 2026-07-06 | Knowledge-centric design | ✅ Accepted |
| ADR-0009 | 2026-07-06 | Code/data separation | ✅ Accepted |
| ADR-0010 | 2026-07-08 | PostgreSQL 18.4 | ✅ Accepted |
| ADR-0011 | 2026-07-11 | Pydantic v2 for config validation | ✅ Accepted |
| ADR-0012 | 2026-07-11 | In-process Event Bus only (Sprint 1) | ✅ Accepted |
| ADR-0013 | 2026-07-11 | Secrets in `.env` file (gitignored); never in YAML | ✅ Accepted |
| ADR-0014 | 2026-07-11 | Revoke CREATE on `public` + strict `search_path` | ✅ Accepted |
| ADR-0015 | 2026-07-11 | Systemd deferred to Sprint 2 | ✅ Accepted |
| ADR-0016 | 2026-07-11 | Audit log retention: 90 days | ✅ Accepted |
| ADR-0017 | 2026-07-11 | Task retry: 3 attempts, exponential backoff | ✅ Accepted |
| ADR-0018 | 2026-07-11 | Connection pool: configurable, default 5 | ✅ Accepted |
| ADR-0019 | 2026-07-11 | Delete `/data/atlas/experiments/` | ✅ Accepted |
| ADR-0020 | 2026-07-11 | pytest for testing; no type checking in Sprint 1 | ✅ Accepted |
| ADR-0021 | 2026-07-11 | **Database-first implementation order** | ✅ Accepted |
| ADR-0022 | 2026-07-11 | Atlas is an **AI Operating System (microkernel)**, not an "agent framework" | ✅ Accepted |
| ADR-0023 | 2026-07-11 | `atlas/kernel/` package (application, bootstrap, lifecycle, registry, service_container); evolves from `core/` | ✅ Accepted |
| ADR-0024 | 2026-07-11 | `atlas/plugins/` layer; plugins self-register with the kernel | ✅ Accepted |
| ADR-0025 | 2026-07-11 | `atlas/events/` package (event, dispatcher, handlers, subscriptions) from day one | ✅ Accepted |
| ADR-0026 | 2026-07-11 | Domain `services/` taxonomy (Memory, Knowledge, Embedding, OCR, Chunking, Document, Search, Ranking) | ✅ Accepted |
| ADR-0027 | 2026-07-11 | Repository pattern; agents/services never issue SQL or use an ORM | ✅ Accepted |
| ADR-0028 | 2026-07-11 | `agent` schema for agent state (separate from `system`) — realized in migration `0007` | ✅ Accepted |
| ADR-0029 | 2026-07-11 | `agent` schema lands in Sprint 3 (migration `0007`): `agent.agents`, `agent.runs`, `agent.steps` | ✅ Accepted |
| ADR-0030 | 2026-07-11 | `Agent` protocol + `AgentService` registry; agents orchestrate via kernel APIs only (no direct SQL/provider access) | ✅ Accepted |
| ADR-0031 | 2026-07-11 | First agent is a **RAG QA agent** (`knowledge.search` → context assembly → `llm.chat`) with inline citations | ✅ Accepted |
| ADR-0032 | 2026-07-11 | Every agent run is persisted (`agent.runs` + per-step rows) for observability and crash recovery | ✅ Accepted |
| ADR-0033 | 2026-07-11 | Filesystem **ingestion source** (`atlas/ingestion/`): scan `paths.documents`, dedup by checksum, enqueue `embed_document` tasks. Extracts **text, markdown, PDF (`pypdf`), and HTML (`beautifulsoup4`)**; scanned/image-only PDFs deferred to a future `OCRService` | ✅ Accepted |
| ADR-0034 | 2026-07-11 | Agent invocation exposed both inline (`AgentService.run`) and deferred (`run_agent` scheduler handler) | ✅ Accepted |
| ADR-0035 | 2026-07-11 | RAG grounding is **strict by default but configurable** (`agent.grounding = "strict" \| "blended"`), so the model's own knowledge can be enabled later without code changes | ✅ Accepted |
| ADR-0036 | 2026-07-11 | **Domain models** package `atlas/models/`: typed models (Document, Chunk, Embedding, Task, AgentRun, Health, Memory) replace raw dicts crossing module boundaries; repositories map rows ↔ models | ✅ Accepted |
| ADR-0037 | 2026-07-11 | **Typed exceptions** package `atlas/exceptions/` (`AtlasError` root + per-domain: database, llm, knowledge, agent, plugin); no generic exceptions across boundaries | ✅ Accepted |
| ADR-0038 | 2026-07-11 | **Provider interfaces** `atlas/interfaces/`: services depend on abstract protocols (`LLMProvider` ✅, `EmbeddingProvider`, `MemoryProvider`, storage), never concrete implementations | ✅ Accepted |
| ADR-0039 | 2026-07-11 | **Telemetry** package `atlas/telemetry/` (metrics, tracing, timers) introduced early; pipeline steps timed automatically | ✅ Accepted |
| ADR-0040 | 2026-07-11 | **Capability Registry** in the kernel: agents query capabilities ("do I have Browser?") instead of importing modules; plugins/services register capabilities | ✅ Accepted |
| ADR-0041 | 2026-07-11 | **Everything external is a plugin** (filesystem, browser, postgres, github, shell, weather, email, scada); even Ollama may become an `llm` plugin eventually | ✅ Accepted |
| ADR-0042 | 2026-07-11 | **Document versioning** (supersede, don't delete): a changed file adds a new version; latest is active, old versions retained for audit/history. Replaces the delete-old-doc idea | ✅ Accepted |
| ADR-0043 | 2026-07-11 | **Kernel is not a god object**: strict boundaries — kernel (lifecycle/DI/registry), services (business logic), repositories (persistence), plugins (integrations), agents (orchestration) | ✅ Accepted |
| ADR-0044 | 2026-07-11 | **Revised sprint order**: 4 Foundations → 5 API/CLI/Auth → 6 Memory → 7 Plugins → 8 Multi-agent → 9 Ops (interface-first) | ✅ Accepted |
| ADR-0045 | 2026-07-11 | **FastAPI + uvicorn** for the REST API: Pydantic v2-native, auto OpenAPI docs, sync endpoints run in a threadpool so sync services work unchanged (ADR-0002) | ✅ Accepted |
| ADR-0046 | 2026-07-11 | **Static API-key auth** via `Authorization: Bearer`; keys from `ATLAS_API_KEYS` env (ADR-0013), constant-time compare, **fail closed** when no keys set; DB-backed keys deferred | ✅ Accepted |
| ADR-0047 | 2026-07-11 | **Unified `atlas` CLI** on stdlib argparse (no new deps); one-shot commands call kernel services in-process via the DI container; `atlas serve` runs the API | ✅ Accepted |
| ADR-0048 | 2026-07-11 | **Memory = single `memory.items` table** with a `kind` discriminator (working/episodic/semantic) + inline nullable `embedding`, engineered for scale: **partial HNSW** index (`WHERE embedding IS NOT NULL`) so non-embedded/working rows never bloat the vector index; `occurred_at` event-time dimension (distinct from `created_at`) indexed for time-ordered recall and ready for future RANGE-by-date partitioning; `expires_at` TTL for working memory (recall filters expired; durable `memory_prune` scheduler task reclaims). Repo-isolated (ADR-0027) so physical layout can evolve to partitioning with zero service/agent changes | ✅ Accepted |
| ADR-0049 | 2026-07-11 | **Plugins load from an explicit config list** (`plugins.enabled` = dotted module paths; each exposes `build(config) -> Plugin`). Fail-closed (no disk auto-discovery, no entry-point scanning); a `PluginManager` (a kernel Service) owns plugin lifecycle/health and captures per-plugin errors so one bad plugin never blocks boot. Entry points can be layered on later if third-party distribution is needed | ✅ Accepted |
| ADR-0050 | 2026-07-11 | **ToolRegistry** in the kernel: plugins register named, invokable actions (name + callable + description + param hints) alongside capabilities (ADR-0040). Tools are the fine-grained catalog agents select from in Sprint 8; exposed via `GET /v1/tools` + `POST /v1/tools/{name}/invoke` and `atlas tools`/`atlas tool` | ✅ Accepted |
| ADR-0051 | 2026-07-11 | **ReAct agent with prompt-based JSON tool-calling**: the `assistant` agent loops reason→act→observe over the ToolRegistry, emitting one JSON object per turn (`{"tool","args"}` / `{"final"}`). Model-agnostic (no native tool-calling dependency), hermetically testable, bounded by a max-iterations cap, with an optional reflection pass. Ollama chain-of-thought is **off** for this agent (the JSON `thought` field replaces it) for speed/reliability; native tool-calling can be added later behind the same interface | ✅ Accepted |
| ADR-0052 | 2026-07-11 | **Agents-as-tools**: existing agents are registered into the ToolRegistry (e.g. `agent.rag`) so the ReAct assistant delegates to them through the same interface it uses for plugin tools. Multi-agent delegation with no separate coordination framework; new agents become available to the orchestrator automatically | ✅ Accepted |
| ADR-0053 | 2026-07-11 | **systemd-first deployment + optional Docker**: one hardened `atlas.service` runs `atlas serve`, whose lifespan boots the full kernel (scheduler/health/ingestion/memory-prune/backup) against host Postgres + Ollama — a single unit avoids two competing schedulers. A Dockerfile + compose (app + pgvector; Ollama via `host.docker.internal`) ship for portability | ✅ Accepted |
| ADR-0054 | 2026-07-11 | **Prometheus `/metrics` (public text) + JSON `/v1/metrics` (authed)**: render the existing in-process telemetry `snapshot()` (ADR-0039) as Prometheus exposition without a client library; public scrape endpoint matches the `/health` convention, JSON endpoint stays behind auth. Gated by `api.metrics_enabled` | ✅ Accepted |
| ADR-0055 | 2026-07-11 | **Scheduler-driven `pg_dump` backups**: a durable `backup` task self-re-enqueues (same pattern as ingestion/memory-prune), writes custom-format dumps to `paths.backups`, prunes to `backup.retention`; on-demand `atlas backup` + `scripts/restore.sh` (`pg_restore --clean --if-exists`). DB password via `PGPASSWORD` env, never argv. Backups survive restarts with no external cron | ✅ Accepted |
| ADR-0056 | 2026-07-11 | **LLM selection by role + a single inference lane** (Stage 2 D7/R4): callers ask `LLMService.for_role("planner"/"researcher"/…)`, never a model name; roles→models live in `llm.roles` (config-only swaps). All generate/chat/embed calls pass one semaphore (`llm.max_concurrency`, default 1) because CPU-only inference must not run two models at once. Legacy `llm.model`/`embedding_model` seed the `chat`/`embed` roles (back-compat) | ✅ Accepted |
| ADR-0057 | 2026-07-11 | **Conversation is first-class, separate from memory** (Stage 2 D3): new `conversation` schema (migration 0009: `sessions` + ordered `messages`, server-assigned ordinals) holds the transcript; remembered facts stay in `memory.items` scoped to the session id. Transcript = *what was said*; memory = *what to keep* — kept apart so recall isn't polluted by chat logs | ✅ Accepted |
| ADR-0058 | 2026-07-11 | **Mode-agnostic Planner + ToolExecutor spine** (Stage 2 D1/D2/R2): a deterministic rule-based Planner routes a message to an intent + args (LLM composes answers, never routes; unmatched → ReAct fallback); a ToolExecutor validates args against the callable signature, retries transient failures, and returns a structured `ToolResult` (never raises). `AssistantService` ties session→plan→dispatch→response and runs a **capability-gap pre-flight** (honest "I can't do X"). The same objects will drive async job steps in S12 | ✅ Accepted |
| ADR-0059 | 2026-07-11 | **Typed capability contracts** (Stage 2 S11): `atlas/capabilities/` defines `runtime_checkable` Protocols + canonical capability ids + a `CAPABILITY_CATALOG` (summary/unlocks/since for known-but-unbuilt capabilities). The `CapabilityRegistry` gains an optional `contract` per registration plus `verify()` (isinstance against the Protocol), `contract_of()`, and `missing()`. Services/plugins declare their contract; the planner tags steps with canonical ids; the R2 gap pre-flight is registry-driven and catalog-enriched. Registration stays back-compatible (contract optional). Surfaced via `GET /v1/capabilities` + `atlas capabilities` | ✅ Accepted |
| ADR-0065 | 2026-07-11 | **Python execution sandbox — hybrid backend** (Stage 2 S16, D6). Atlas runs analysis code in an isolated, resource-limited sandbox whose computed results can become **L5 evidence** (§5a.6). New `atlas/sandbox/` targets a small `SandboxBackend` interface (the D6 *hybrid* swap point): the default **`SubprocessBackend`** runs `python -I -B` in a child process with a POSIX `preexec_fn` applying **rlimits** (`RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, no core dump), a **hard wall-clock timeout** that kills the whole **process group** (`start_new_session` + `killpg`), a scratch working dir, a stripped env, and — unless explicitly enabled — an in-interpreter **network block** (neutralises `socket.socket`/`create_connection`); a **`DockerBackend`** is a selectable placeholder that honestly reports itself unavailable (every run `blocked`, R2) so stronger isolation drops in later via `sandbox.backend: docker` without touching callers. Every run returns a serialisable `ExecutionResult` — `outcome` (`ok`/`error`/`timeout`/`blocked`), truncated stdout/stderr, returncode, duration, an optional structured `result` (parsed from a `result.json` the code writes), and produced `artifacts` — and **never raises** into the caller (R2/R3). `PythonSandboxService` = the `python` capability (`run`/`run_file`, per-run uuid workdir under `paths.data/sandbox`). Planner gains a `run_python` intent (fenced code / "run python …") + `AssistantService._do_run_python` (honest output/error/timeout/blocked); `JobPlanner` accepts it. Concrete `PythonExecutionCapability` contract (`CAP_PYTHON`). Decision: **network off by default** (opt-in per run); subprocess = soft isolation for trusted-ish code, Docker = the hostile-code path. Surfaced via `POST /v1/python/run` + `atlas python`; `sandbox.*` config | ✅ Accepted |
| ADR-0067 | 2026-07-11 | **Deeper Research Sources — scholarly search + video transcripts** (Stage 2 S18a). Atlas's evidence gathering reaches past general web links to **academic literature** and **spoken-word** sources, each **pre-graded on the Evidence Level scale (§5a.2)** so it feeds the S15 Verification Engine + S17 reports directly. `atlas/search/scholarly.py` adds a `ScholarlyProvider` protocol (mirrors D5 web search) returning `Paper` records (title/authors/year/venue/abstract/DOI/citations) with an `as_source()` in the Evidence-Graph `Source` shape: **`ArxivProvider`** (arXiv Atom API, keyless; preprints ⇒ **L3**) and **`SemanticScholarProvider`** (Semantic Scholar Graph API, keyless/rate-limited + optional key; published venues ⇒ **L4** peer-reviewed), both fetching through the resilient net layer (ADR-0061) and **translating outcomes, never raising** (R2/R3). `ScholarPlugin` = the `scholar` capability (`scholar.search`) with **provider fallback** (first `ok`-with-papers wins); output carries both `results` (papers) and graded `sources`. `atlas/transcripts/` adds `YouTubeTranscriptProvider` — two polite fetches (watch page → scrape `captionTracks` → timedtext XML → decode cues) yielding a `TranscriptResult` (text + timed segments) as **L1** evidence, every failure a structured outcome (`error`/`skipped`/`blocked`) — exposed by `YouTubePlugin` as the `transcript` capability (`youtube.transcript`). Planner gains `scholar_search` (routed ahead of generic web search on arXiv/Scholar mentions or "papers/studies on …") and `youtube_transcript` (routed ahead of web fetch on a YouTube URL, or an explicit transcript request), with `AssistantService._do_scholar_search`/`_do_youtube` and `JobPlanner` support. Concrete `ScholarCapability`/`TranscriptCapability` (catalog `CAP_SCHOLAR`/`CAP_TRANSCRIPT`). Config `plugins.scholar` (providers/levels/optional key) + `plugins.youtube` (languages); both plugins enabled by default. Surfaced via `POST /v1/scholar` + `POST /v1/youtube/transcript`; `atlas scholar`/`youtube`. Split from the Learning Pipeline (S18b) following the S13a/S13b precedent | ✅ Accepted |
| ADR-0070 | 2026-07-12 | **Git — read-only local version control as the first Tier-2 tool** (Stage 2 S20a). S20 ("Tier 2/3 tools, as needed") is **split**: S20a ships **Git**, the highest-value tool for a coding assistant and the one that is fully deterministic and hermetically testable; browser automation, OCR, DB and Email/LinkedIn are deferred to **S20b** (Browser deliberately late per the build order). New `atlas/vcs/git.py`: **`GitClient`** shells out to `git` through an injectable **`CommandRunner`** (default **`SubprocessRunner`** with a hard per-invocation timeout; a `FileNotFoundError` maps to an `unavailable` sentinel, a timeout to a bounded `error`). It is **read-only by construction** — only inspection subcommands are ever assembled (`status`/`log`/`diff`/`show`/`branch`/`rev-parse`); there is **no** code path that fetches, pulls, pushes, commits, or mutates a repo, and it never touches the network. Every method returns a plain dict with an `outcome` of `ok` | `not_a_repo` | `unavailable` | `error` and **never raises** into the caller (R2/R3); parsing is done by pure functions (porcelain `-b` status, unit-separated `--pretty` log, `--stat` file counts). **`GitPlugin`** = the `git` capability with six tools — `git.status` (branch/ahead-behind/working changes/clean), `git.log`, `git.diff` (`--stat` + files-changed), `git.show`, `git.branches` (list + current), `git.file_history` (commits touching a path, passed after a `--` pathspec). Concrete **`GitCapability`** contract (catalog `CAP_GIT`, since S20). Planner gains a deterministic **`git_status`** intent (routes "git status/log/diff/branches", "recent commits", "uncommitted changes"; extracts the repo path or defaults to `.`) with `AssistantService._do_git` (deterministic rendering; honest `git` capability-gap and `unavailable`→blocked handling) and `JobPlanner` support. Config `plugins.git.*` (`git_binary`/`timeout`/`max_log`); `atlas.plugins.git_plugin` added to the enabled list (self-registers — no bootstrap change). Surfaced via `POST /v1/git` (`{action, repo, ref?, path?, max_count?}`) + `atlas git status|log|diff|show|branches|file_history <repo>`. The runner seam keeps tests hermetic (canned output) while one integration test drives the real binary against a temp repo | ✅ Accepted |
| ADR-0069 | 2026-07-12 | **Engineering Intelligence — the Code store + Learning Levels via store sinks** (Stage 2 S19, D11/§5d). Atlas climbs the Learning-Level ladder (§5d.6) over a new **Code store**, realising the S18b promise "add sinks, not schema" literally. **`LearningService` gains a store-sink registry**: `register_sink(store, sink)` attaches a materialiser (`apply(payload) -> ref_id` + `revert(ref_id)`), and `apply`/`revert` route non-Experience stores through their sink — so promotion into *any* store stays governed, explainable and reversible through the *one* `learning.events` ledger; a public `propose(..., apply=True)` lets higher-order learners record a governed event and (for an explicit act) promote it at once. Migration **0012** adds `learning.repositories` (L2 — a repo distilled to languages/frameworks/entry-points/dependencies/graph-size/**per-repo patterns**; a unique-active-root index makes re-learning idempotent by retiring the prior row) and `learning.patterns` (L4 — patterns **generalized across** repositories, prevalence-scored; a recomputable materialised view). New `LearnedRepository`/`EngineeringPattern` models + `IntelligenceRepository`. **`IntelligenceService`** = the `intelligence` capability over `CodeCapability` (S14) artifacts: **L2 Understand** `learn_repository(root)` (parse via `repo_map`+`patterns`+`search_symbols` → structure payload → promote through `CodeStoreSink`; explicit ⇒ applied but reversible; parse failures are an `error` outcome, never an exception, R2/R3); **L3 Connect** `search(query)` (cross-project retrieval) + `connections()` (repos sharing frameworks/languages); **L4 Generalize** `generalize()` (prevalence of each pattern/framework/language across learned repos, keeping those ≥ `generalize_min_prevalence` — "you *always* use X"; persisted via `replace_patterns`); **L5 Recommend** `recommend(context)` (proactive advice, auto-generalizing if needed) + `profile()` (the engineer profile). Concrete **`IntelligenceCapability`** contract (`CAP_INTELLIGENCE`). Config `intelligence.*` (`enabled`/`default_policy=project`/`generalize_min_repos`/`generalize_min_prevalence`/`recommend_top_k`); wired in bootstrap (container/capabilities/lifecycle) with the code sink registered on the learning service. Surfaced via `POST /v1/intelligence/repositories`, `GET .../repositories[/{id}]`/`.../search`/`.../connections`/`.../patterns`/`.../profile`, `POST .../generalize`/`.../recommend`; `atlas intel learn|repos|search|connections|generalize|patterns|recommend|profile`. **Design:** the governed/reversible unit is the repository (**L2**); L3–L5 are recomputed inferences over that governed data, not separately-governed truths | ✅ Accepted |
| ADR-0068 | 2026-07-12 | **Learning Pipeline — Continuous Learning as a governed ledger** (Stage 2 S18b, D11/§5d). Atlas becomes cumulative without ever *silently* learning. Migration **0011** adds a `learning` schema with two tables: **`learning.events`** — the governed, explainable, **reversible** ledger where every learning action is a row carrying *what* (`summary`), *why* (`reason`), *from where* (`origin`), a governance **`policy`** (temporary/project/personal/verified, §5d.5), a **Learning Level** (`level` 1–5, §5d.6), a lifecycle **`status`** (`proposed → applied → reverted`, CHECK-constrained), and a `ref_id` pointing at the created store record — and **`learning.experiences`** — the **Experience store** (§5d.2, the "missing fifth store"): problem → diagnosis → actions → mistakes → solution → lessons, with `status='reverted'` hiding an entry without deleting the audit trail. `models/learning.py` = `LearningEvent`/`Experience` (frozen, `as_dict`) + source/store/policy/level constants; `repositories/learning_repo.py` = the only SQL layer (event + experience CRUD, lexical `search_experiences`, counts). **`LearningService`** = the concrete `learning` capability: `observe_job(detail)` distils a finished job into an Experience *candidate* and records a **proposed** event (default `auto_apply=false` ⇒ propose-only — the enforcement of "never silently learns"; best-effort, never raises into/ fails a job); `apply(event_id, policy?, level?)` promotes a proposal into its store (creates the Experience) + stamps the event `applied`; `revert(event_id)` flips it `reverted` and deactivates the record (reversible); `remember_experience(...)` is the explicit manual path (applied at once); `recall(query)` does lexical recall; `explain(event_id)` renders what/why/from-where + status. Concrete **`LearningCapability`** contract replaces the S18 catalog placeholder (`CAP_LEARNING`). `JobService._finalize` calls `observe_job` after the report is attached (guarded). `LearningConfig` (`enabled/observe_jobs/auto_apply/default_policy/default_level/recall_k`; conservative defaults) + `learning:` YAML; registered in bootstrap (container/capabilities/lifecycle). Surfaced via `GET /v1/learning/events[/{id}]`, `POST /v1/learning/events/{id}/apply`, `.../revert`, `GET|POST /v1/learning/experiences`; `atlas learn events|show|apply|revert|experiences|recall`. **Scope:** ledger + Experience store + job observation + review/apply/revert/recall; promotion into the *other* stores (knowledge graph, code/architecture, generalized patterns) and higher Learning Levels L2–L5 land at **S19** — the ledger already models `store`/`level`, so S19 adds sinks, not schema | ✅ Accepted |
| ADR-0066 | 2026-07-11 | **Non-blocking HITL & Report Generator** (Stage 2 S17, §5a.5). The research pipeline gains an *output* and a *human loop*. New `atlas/reports/`: **`ReportGenerator.generate()`** is a **pure, deterministic** assembly of the nine scientific-review sections — Executive Summary → Answer → Confidence → Methodology → Evidence → References → Conflicting Views → Limitations → Next Research — from *verified* claim dicts (the `Claim.as_dict` shape from S15) + source dicts; each numeric answer carries its claim's calculated confidence + supporting/contradicting counts. **Overall confidence is derived, never guessed** (most-common claim confidence, ties → the *more conservative* level); **Conflicting Views** auto-flags claims with contradicting sources or weak/insufficient evidence; **Next Research** is derived from low-confidence / non-converged claims. An optional **`summarizer`-role LLM** only *polishes* the executive-summary prose — no LLM (or any failure) ⇒ deterministic fallback, so a report is always producible; renders a structured dict + a Markdown document. **`ReportService`** = the `reports` capability: `report(objective, graph, budget?)` runs the **verify→render** pipeline (Verification Engine → §5a.5), `render(objective, …)` renders directly from verified claims or a gathered answer + sources (no verification). **Job Engine**: on finalize `JobService` builds a report from completed steps (answers + citations→references) and attaches `result.report`/`report_sections`/`overall_confidence` (best-effort — a report never fails the job, R2/R3); **`list_blocked()`** aggregates blocked steps across jobs into one HITL queue (R3), and **`job.step_blocked`/`job.finalized`** events fire through the dispatcher (in-app notify, Q2). Surfaced via `POST /v1/report` + `GET /v1/jobs/blocked`; `atlas report` + `atlas jobs --blocked`. Fully autonomous multi-round gather→verify→decide orchestration is deferred to S18 | ✅ Accepted |
| ADR-0064 | 2026-07-11 | **Verification Engine + Evidence Graph — verification is a first-class subsystem** (Stage 2 S15, D8/§5a). Atlas emits **claims**, not raw conclusions. `atlas/evidence/` = a serialisable model — `Source`, `EvidenceItem` (source_id, level, extracted_value, snippet, locator, stance), `ClaimValue`, `Claim` (statement/value/evidence/*calculated* confidence/convergence/`last_verified`/`verification_method`/`reasoning_trace`), and `EvidenceGraph` (sources+claims, `as_dict`/`from_dict`) — so a graph persists in a job result and is **re-verifiable** when new evidence appears. `atlas/verification/` = the engine (pure, no LLM/I/O, hermetic): **Evidence Levels L1–L5** (quality not count); `convergence(values)` = largest cluster within a relative tolerance ∈ [0,1] (tight `3.7/3.9/4.0/3.8`→1.0; scattered `2/11/6/4`→low); `verify_claim` sets **calculated** confidence HIGH/MEDIUM/LOW/INSUFFICIENT (score = 0.6·convergence + 0.4·quality, contradiction penalty; a single or low-level source can never be HIGH) with a human reasoning trace; `decide(claim, budget, iteration)` enforces the per-job **Evidence Budget** (`min_sources`/`min_peer_reviewed`/`min_government`/`convergence`/`max_search_iterations`) → `stop`/`continue` with explicit unmet criteria (stop on *convergence*, not paper count). `VerificationService` = the `verification` capability (`verify(graph, budget?)` → per-claim decision); `research.*` config (`ResearchConfig`); `POST /v1/verify` + `atlas verify`. **Scope = engine/graph/budget primitives**; the live gather→verify→decide research loop + scientific-review Report Generator land at S17, and Python-computed results (S16) enter the same graph as **L5** evidence | ✅ Accepted |
| ADR-0063 | 2026-07-11 | **Code Understanding — `CodeCapability`, Tier B** (Stage 2 S14, D9/§5b): read code as *structure*, not text. New `atlas/code/`: **Python parsed with the stdlib `ast`** (symbols/imports + **call sites with enclosing symbol** for the cross-file call graph — the Python-first path); **other languages via tree-sitter** (`tree-sitter-language-pack`: JS/TS/TSX/C/C++/Rust/Go/Java/Bash/SQL, symbols+imports). A `CodeParser` dispatches and returns an honest per-file **outcome** (`ok`/`shallow`/`unsupported`/`error`), never raising (R2). Higher layers: **repo map** (manifests → dependencies, inferred frameworks, entry points), **symbol index**, **import graph + cross-file call graph** (conservative resolution — builtins/externals ignored, ambiguous-but-known counted not guessed), and **pattern mining** (evidence-backed recurring patterns → seed for S19). `CodeService` = the `code` capability (`parse`/`repo_map`/`index`/`search_symbols`/`graph`/`patterns`/`explain`): **code-aware chunking** (one chunk per symbol) into the knowledge base for semantic code search, and a **`code`-role LLM `explain`** grounded on the parsed structure. Concrete `CodeCapability` contract registered (catalog `CAP_CODE` provided). Surfaced via `POST /v1/code/*` + `atlas code …`; `code.*` config; deps `tree-sitter`+`tree-sitter-language-pack` | ✅ Accepted |
| ADR-0062 | 2026-07-11 | **Web Search + Downloader** (Stage 2 S13b): first research-retrieval capabilities, built on the resilient net layer (ADR-0061). **D5 locked → DuckDuckGo** (keyless HTML) default: `atlas/search/` defines a `SearchProvider` protocol → `SearchResponse`/`SearchHit`, `DuckDuckGoProvider` (unwraps `uddg` redirects, translates the net outcome instead of raising); `SearchPlugin` registers the `search` capability + `web.search` tool with an **ordered provider list → provider fallback** (SearXNG/Brave/Serper swap in via `plugins.search.providers` without touching the planner). `DownloaderPlugin` registers `downloader` + `web.download` (size-capped fetch → sandbox-confined downloads dir; honest block/skip, R2). Planner gains a `web_search` intent (+ `AssistantService._do_web_search` reporting blocked/empty honestly; `JobPlanner` accepts it). Surfaced via `POST /v1/search` + `atlas websearch`/`download`; `plugins.search`/`plugins.downloader` config, both enabled by default | ✅ Accepted |
| ADR-0061 | 2026-07-11 | **Document Reader + resilient net layer** (Stage 2 S13a): shared extractors expanded to the fixed format set (pdf/docx/pptx/xlsx/csv/md/txt/html/json) with lazy per-parser imports; new `atlas/documents/DocumentService` (`document` capability) returns an `ExtractedDocument` **outcome** (ok/unsupported/empty/error) and never raises on a bad file (R2); scan + `atlas ingest` use it. New `atlas/net/FetchClient` (D10/§5c): one polite client (per-domain throttle + `robots.txt` + bounded backoff/retry w/ jitter + response cache) returning structured outcomes (`ok`/`blocked`/`skipped`/`error`) so jobs degrade not crash (R2/R3); `WebPlugin` fetches through it; top-level `net.*` config. Surfaced via `GET /v1/documents/formats` + `atlas formats` | ✅ Accepted |
| ADR-0060 | 2026-07-11 | **Job Engine — one step per self-re-enqueuing task** (Stage 2 S12): a `job` (migration 0010: `job.jobs` + `job.steps`) is decomposed by `JobPlanner` (deterministic `Planner` fallback + optional planner-role LLM) and run by `JobService` on the durable scheduler. `create_job` enqueues an `advance_job` task that runs **one** runnable step then **re-enqueues itself**, so many jobs interleave on the worker pool (R1) without a long job starving the scheduler, while steps stay sequential per job (Q1). A `blocked` step (missing capability/file/login) is **non-fatal** and cascades to dependents (R3): the job finishes `completed_with_blocks` and is resumable. Steps reuse `AssistantService.run_step` (the chat dispatch, D1) extended with a `blocked` outcome. Reboot recovery re-hydrates running jobs/steps (Q10). Surfaced via `/v1/jobs*` + `atlas jobs`/`atlas job` | ✅ Accepted |

> ADR-0029 through ADR-0035 were **confirmed on 2026-07-11** (see Q1–Q5 answers in
> §17.12). Note ADR-0033 reflects a deliberate deviation from the initial
> recommendation: PDF + HTML extraction is included **now** (not deferred).
>
> ADR-0036 through ADR-0044 (2026-07-11) capture the cross-cutting foundations and
> revised roadmap requested by the maintainer; see §18 for the detailed design and
> phased introduction. A few minor sub-choices remain open (flagged in §18.9).

---

## 15. Next Steps

### ✅ Decisions finalized (2026-07-11)

All open questions resolved. See Decision Log (ADR-0011 through ADR-0021).

### Implementation order (Database First — ADR-0021)

```
Step 1  Apply SQL migrations (0001 → 0005)                     ✅ DONE
Step 2  Repo setup (uv, gitignore, secrets, cleanup)           ✅ DONE
Step 3  Configuration Manager (Pydantic v2)                    ✅ DONE
Step 4  Database connection manager + migration runner (Py)    ✅ DONE
Step 5  Logging                                                ✅ DONE
Step 6  Repositories layer (SQL isolated here)                 ✅ DONE
Step 7  atlas/kernel/ + atlas/events/ + run.py bootstrap        ✅ DONE
Step 8  Health monitor + scheduler + LLM + knowledge (Sprint 2)  ✅ DONE
Step 9  Agent layer + RAG + ingestion source (Sprint 3)          ✅ DONE
Step 10 Foundations hardening (models/exceptions/interfaces/     ✅ DONE
        telemetry/capabilities) — Sprint 4 (§18)
Step 11 REST API + CLI + Auth (Sprint 5)                          ✅ DONE
Step 12 Memory System (Sprint 6)                                  ✅ DONE
Step 13 Plugins & Tools (Sprint 7)                                ✅ DONE
Step 14 Multi-agent: ReAct assistant + tools (Sprint 8)           ✅ DONE
Step 15 Operations: systemd/Docker, metrics, backups (Sprint 9)   ✅ DONE
Step 16 Web UI (backlog)                                          ← NEXT
        (ADR-0044 revised order)
```

> The kernel (Step 7) is built as the `atlas/kernel/` package per ADR-0023, with
> the `atlas/events/` package per ADR-0025. `atlas/core/` will be retired.

### Progress Log

**2026-07-11 — Database foundation complete**

- Migrations `0001`–`0005` applied; all objects owned by `atlas`
- Migration tracking baselined in `system.migrations` (5 applied, 0 pending)
- `uv` environment created; deps installed (pydantic v2, psycopg3, pyyaml, dotenv)
- `atlas/config/manager.py` — typed config, `.env` secrets, env overrides
- `atlas/database/connection.py` — psycopg3 pool + health check (verified: `atlas` role, correct `search_path`)
- `atlas/database/migrations.py` + `cli.py` — migration runner (`status` / `migrate` / `baseline`)
- Console script: `uv run atlas-db <command>`

**2026-07-11 — Logging complete (Step 5)**

- `atlas/utils/logging.py` — console + rotating file handler (10MB × 5 from config)
- Level from config; `get_logger(name)` + idempotent `setup_logging()`
- 14 pytest tests passing (logging tests are hermetic via `tmp_path`)
- ✅ Verified end-to-end: log line written to `/data/atlas_data/logs/atlas.log`
- Runtime ownership fixed: `chown -R jagd:jagd /data/atlas_data` applied

**2026-07-11 — Repositories layer complete (Step 6)**

- `atlas/repositories/base.py` — query helpers over `DatabaseManager` (dict rows)
- `settings_repo.py` (`system.settings`), `task_repo.py` (`scheduler.tasks`), `event_repo.py` (`audit.events`)
- SQL now isolated here per ADR-0027; services/agents will call repos, never SQL
- 18 pytest tests passing (4 new repo integration tests; skip gracefully w/o DB)

**2026-07-11 — Kernel + Events complete (Step 7)**

- `atlas/events/` — `event.py`, `dispatcher.py`, `handlers.py`, `subscriptions.py` (in-process bus, ADR-0025); handler failures isolated
- `atlas/kernel/` — `registry.py`, `service_container.py` (DI), `lifecycle.py`, `application.py`, `bootstrap.py` (ADR-0023)
- `atlas/services/base.py` (Service protocol + HealthStatus), `database_service.py` (lifecycle adapter)
- `run.py` entry point: `uv run python run.py [--once]`
- Old `atlas/core/` stub retired
- ✅ Verified: `run.py --once` boots config → logging → DB service → `KernelStarted` → ready → health `[OK] database` → graceful stop
- 29 pytest tests passing

### Commands available now

```bash
uv run atlas-db status      # show applied vs pending migrations
uv run atlas-db migrate     # apply pending migrations (as atlas)
uv run atlas-db baseline    # mark all present migrations as applied
uv run pytest -q            # run tests
```

### Sprint 1 — COMPLETE ✅

The foundation is done: config, logging, database, repositories, kernel, events,
and a working `run.py` bootstrap. Atlas starts, health-checks, and stops cleanly.

### Sprint 2 (Knowledge Foundation) — in progress

- ✅ Health monitor service (periodic checks → `system.health`, emits `ServiceUnhealthy`)
- ✅ Scheduler service + workers (uses `scheduler.*` tables; crash recovery)
- ✅ LLM service + Ollama provider (generate/chat/embed, reasoning-model handling)
- ✅ Knowledge/embedding tables (migration `0006`), repositories, ingest + search

**2026-07-11 — Health monitor complete (Sprint 2.1)**

- `atlas/repositories/health_repo.py` — record/latest/recent over `system.health`
- `atlas/services/health.py` — `HealthMonitor`: baseline check on start + daemon
  thread every `monitoring.health_interval`s; emits `ServiceUnhealthy` on failure
- `MonitoringConfig` added (default 30s interval)
- Fixed a circular import (kernel.registry ↔ services) via TYPE_CHECKING
- ✅ Verified: `run.py --once` starts database + health_monitor, records rows to
  `system.health`, reports `[OK]` for both; 33 pytest tests passing

**2026-07-11 — Scheduler service complete (Sprint 2.2)**

- `atlas/scheduler/handlers.py` — `HandlerRegistry` maps `task_type` → handler
  callable `(payload) -> dict|None`; future task types (embedding, ingestion)
  register here without touching the scheduler.
- `atlas/scheduler/service.py` — `SchedulerService` (kernel-managed):
  - N worker threads (`scheduler.workers`, default 2) poll for pending tasks.
  - **Atomic claim** via `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)` —
    no two workers (or processes) ever grab the same task.
  - **Crash recovery**: on start, tasks stuck in `claimed`/`running` (killed mid-run)
    reset to `pending` and re-run; emits `TasksRecovered`.
  - **Retry with exponential backoff**: `delay = backoff_base * 2**retry_count`,
    re-queued via future `scheduled_at`, up to `max_retries`; each attempt recorded
    in `scheduler.task_runs`; emits `TaskRetry` / `TaskFailed` / `TaskCompleted`.
  - `health_check` reports live worker count.
- `TaskRepository` extended: `claim_next`, `recover_interrupted`, `mark_completed`,
  `reschedule_for_retry`, `mark_failed_permanent`, `start_run`, `finish_run`.
- `SchedulerConfig` gains `poll_interval` (1.0s) and `backoff_base` (2.0s).
- Wired into `bootstrap` (start order: database → scheduler → health_monitor) and
  exposed via the container (`task_repo`, `task_handlers`).
- Test hygiene: DB integration guards now fast-probe (2s `connect_timeout`) instead
  of blocking the pool's 30s timeout when Postgres is unreachable.
- ✅ Verified: 42 pytest tests pass (incl. integration: complete / retry-then-fail /
  crash-recovery); `run.py --once` shows `[OK] scheduler: 2/2 workers alive`; live
  demo enqueued `demo_add{a:3,b:4}` → `worker-0` produced `{'sum': 7}`, task
  `completed`, run recorded in `scheduler.task_runs`.

**2026-07-11 — LLM service complete (Sprint 2.3)**

- Environment check: Ollama 0.21.0 (`/usr/local/bin/ollama`), systemd service on
  `127.0.0.1:11434`, model store `/usr/share/ollama/.ollama/models`; models present:
  `qwen3:4b` (chat) + `llama3:latest` (embeds). Server ignores the shell's empty
  `OLLAMA_MODELS=/data/ai_agent/models`. `nomic-embed-text` not yet pulled.
- `atlas/llm/provider.py` — vendor-neutral `LLMProvider` protocol + `ChatMessage`,
  `LLMResponse` (text + separated `thinking` + usage), `EmbeddingResponse`.
- `atlas/llm/ollama_provider.py` — `OllamaProvider` over the REST API
  (`/api/generate`, `/api/chat`, `/api/embed`, `/api/tags`) using `httpx`:
  - **Reasoning-model handling**: qwen3 ignores `think=false` and leaks
    chain-of-thought (inline, only a stray `</think>`). We default `think=true`
    so Ollama returns a clean answer + a separate `thinking` field, and defensively
    strip both well-formed and orphan `</think>` blocks. Non-reasoning models
    reject `think` → automatic retry without it.
  - Configurable temperature/timeout/keep_alive; `num_predict`, `top_p`, etc.
    pass through per-call.
- `atlas/llm/service.py` — `LLMService` (kernel-managed): `generate/chat/embed`;
  health check verifies the server is up AND the chat model is installed (missing
  chat model = unhealthy; missing embedding model = noted, non-fatal).
- `LLMConfig` extended: `embedding_model`, `timeout`, `keep_alive`, `think`.
- Added `httpx` dependency; wired the provider+service into `bootstrap` (start order:
  database → llm → scheduler → health_monitor) and the container (`llm`).
- ✅ Verified: 58 pytest tests pass (incl. live Ollama integration for
  generate/embed); `run.py --once` → `[OK] llm: ollama up; chat 'qwen3:4b',
  embed 'nomic-embed-text' [not pulled]`; live `generate("2+2")` → clean
  `text='4'` with reasoning captured in `thinking`.

**Note for Sprint 2.4**: `ollama pull nomic-embed-text` (768-dim, ~274 MB) before
building the embedding pipeline; `qwen3:4b` does not support embeddings (`llama3`
does, but a dedicated model is better and defines the vector dimension).

**2026-07-11 — Knowledge foundation complete (Sprint 2.4)**

- Pulled `nomic-embed-text` (768-dim). `qwen3:4b` cannot embed (501); dedicated
  model defines the `vector(768)` column dimension.
- **pgvector access fix (`0001`)**: `atlas` had no rights on `public` (where the
  `vector` type/operators live), so `0006` failed with `type "vector" does not
  exist`. Added `GRANT USAGE ON SCHEMA public TO atlas` + appended `public` to the
  role `search_path`, keeping `CREATE` revoked (ADR-0014 intact). `0001` is
  idempotent and was re-run as superuser.
- **Migration `0006`** (`knowledge.documents` / `chunks` / `embeddings`):
  checksum-dedup documents with a status pipeline (pending→chunked→embedded→
  failed), ordered chunks (unique per doc+ordinal, cascade delete), embeddings
  unique per (chunk, model) with an **HNSW cosine index** (pgvector 0.8.4).
- **Repositories**: `DocumentRepository` (dedup by sha256), `ChunkRepository`
  (batch upsert), `EmbeddingRepository` (pgvector literals + `<=>` cosine search).
- **`atlas/knowledge/`**: `chunk_text` (overlapping word windows) and
  `KnowledgeService` — `ingest_text` (dedup→chunk→embed inline), `search`
  (embed query → ANN), and an `embed_document` **scheduler handler** for the
  deferred/resilient path (survives restarts via crash recovery).
- `KnowledgeConfig` (chunk size/overlap, embed batch); LLM health model-name
  matching handles Ollama's bare-vs-`:latest` naming; wired into bootstrap +
  container (`knowledge`).
- ✅ Verified: 67 pytest tests pass (incl. live Postgres+Ollama ingest/search);
  `atlas-db migrate` applied `0006`; `run.py --once` → `[OK] llm: ... embed
  'nomic-embed-text'`; live demo ingested 3 docs and semantic search returned the
  correct document for each of 3 natural-language queries (sim 0.54–0.65).

### Sprint 3 (Agent Layer & RAG) — ✅ COMPLETE

Sprint 2 delivered the capability layer (LLM + knowledge + scheduler + health).
Sprint 3 added the **agent layer** — the top of the four-layer stack — plus the
**ingestion source** that feeds the knowledge base automatically. See the detailed
plan in [Section 17](#17-sprint-3--agent-layer--rag-detailed-plan). ADRs 0029–0035
accepted; decisions confirmed via Q1–Q5 (§17.12).

**2026-07-11 — Agent layer & RAG complete (Sprint 3)**

- **Migration `0007`** created the `agent` schema (`agent.agents`, `agent.runs`,
  `agent.steps`). The `atlas` role owns the database, so `atlas-db migrate` applied
  it directly — **no superuser round-trip** (unlike `0001`/`0006`). ADR-0028 is now
  realized, so it moves to ✅ Accepted.
- **`AgentRunRepository`** (ADR-0027): agents/runs catalog + per-run ordered step
  trace; the only SQL layer for agent state.
- **Agent layer** (`atlas/agents/`): `Agent` protocol + `AgentResult`/`Citation`
  (`base.py`); `RagAgent` (`rag_agent.py`) — retrieve (`knowledge.search`) → filter
  by `similarity_floor` → assemble numbered context (char-capped) → `llm.chat` →
  inline `[n]` citations + trailing Sources list. Strict grounding short-circuits to
  "I don't know" when nothing clears the floor; `grounding="blended"` is a config
  flip (ADR-0035). Every run + step is persisted; failures are recorded then raised.
- **`AgentService`** (`atlas/services/agent_service.py`): kernel-managed registry/
  dispatcher; upserts the agent catalog on start; `run_agent` scheduler handler for
  the deferred path (ADR-0034).
- **Filesystem ingestion source** (`atlas/ingestion/`): `extractors.py`
  (text/markdown direct, PDF via `pypdf` text layer, HTML via `beautifulsoup4`;
  scanned/image PDFs → skipped for future OCR) + `FilesystemSource` — scan → extract
  → dedup (checksum) → `ingest_text(embed=False)` → enqueue `embed_document`.
  Registered as a Service; `ingest_scan` re-enqueues itself every
  `ingestion.scan_interval`s (durable periodic scans), seeded once at startup and
  guarded against duplicate chains across restarts.
- **Scheduler enhancement** (additive, serves Q3): `TaskRepository.create` /
  `SchedulerService.enqueue` gained `delay_seconds` (via `scheduled_at`), plus
  `count_pending_of_type`, enabling delayed self-re-enqueue without a cron.
- **Config**: `AgentConfig` (`retrieval_k`, `similarity_floor`, `max_context_chars`,
  `grounding`, `system_preamble`) + `IngestionConfig` (`enabled`, `extensions`,
  `scan_interval`); wired into bootstrap + container (`agent`, `agent_run_repo`,
  `ingestion`). Start order: **database → llm → scheduler → agent → ingestion →
  health_monitor**.
- **Deps**: `pypdf`, `beautifulsoup4` (+ `soupsieve`); `requirements.txt` refreshed.
- ✅ Verified: **93 pytest tests pass** (was 67; +26 across agents/ingestion incl.
  live Postgres+Ollama RAG end-to-end + a run/step persistence check, and a
  hand-built minimal PDF text-extraction test); `run.py --once` → all six services
  `[OK]` incl. `agent: 1 agent(s): rag` and `ingestion: ... every 300s`; **live
  demo**: dropped a markdown file → `ingest_scan` ingested it → scheduler embedded
  it → `rag` agent answered *"The internal codename for Atlas Sprint 3 is
  'Cartographer' [1]"* (sim 0.78) and listed the ingestion file types (sim 0.62),
  each with a citation, then cleaned up.

**Deviations from the original recommendation (flagged per your request):**
- **PDF + HTML extraction included now** (Q4) rather than deferred — added `pypdf` +
  `beautifulsoup4`; scanned/image-only PDFs remain a future OCR task.
- **Grounding made configurable** (Q2) via `agent.grounding` so blended mode can be
  enabled later without code changes.
- **Periodic ingestion** implemented via a self-re-enqueuing `ingest_scan` task
  (needed a small additive `delay_seconds` on the scheduler) rather than a new cron
  subsystem — keeps the kernel/scheduler simple while satisfying "scheduled scan".

### Sprint 4 (Foundations Hardening) — ✅ COMPLETE

F4 locked (dedicated sprint, maintainer-confirmed): the cross-cutting foundations
landed as their own hardening pass — before feature sprints build on raw dicts,
generic exceptions, and untyped providers — following the accepted §18.10 order.
No external behaviour changed; only structure and observability.

**2026-07-11 — Foundations hardening complete (Sprint 4)**

- **4.1 `atlas/exceptions/`** (ADR-0037): `AtlasError` root + per-domain families
  (`ConfigError`; `DatabaseError`/`DatabaseConnectionError`/`MigrationError`/
  `QueryError`; `LLMError`/`ProviderUnreachableError`/`ModelMissingError`/
  `GenerationError`; `KnowledgeError`/`IngestError`/`EmbeddingMismatchError`/
  `SearchError`; `AgentError`/`AgentNotFoundError`/`AgentRunError`; `PluginError`/
  `PluginLoadError`/`CapabilityMissingError`). Wired at the boundaries the plan
  called out: the embed-count-mismatch `RuntimeError` → `EmbeddingMismatchError`,
  `AgentService.get` `KeyError` → `AgentNotFoundError`, and `OllamaError` now
  subclasses `LLMError` (was bare `RuntimeError`). `details` kwargs carry structured
  context for telemetry without message parsing.
- **4.2 `atlas/models/`** (ADR-0036): frozen, slotted dataclasses (`Document`,
  `Chunk`, `Embedding`, `Task`, `TaskRun`, `AgentRecord`, `AgentRun`, `AgentStep`,
  `HealthRecord`) with a `Model.from_row`/`from_rows` mapping layer (UUID→str
  normalization, extra columns ignored, defaults applied). Converted **2 repos**
  incrementally (F5): `DocumentRepository` (create/get/get_by_checksum/
  list_by_status → `Document`) with `KnowledgeService` moved to attribute access,
  and `HealthRepository` (latest/recent → `HealthRecord`). Other repos keep dict
  returns until their callers move over.
- **4.3 `atlas/interfaces/`** (ADR-0038): protocols consolidated for discoverability;
  `LLMProvider` re-exported from its home; new **`EmbeddingProvider`** splits
  embeddings from chat (a pure embedding backend need not implement chat/generate —
  test-locked); forward-looking `MemoryProvider` (Sprint 6) and `StorageProvider`
  (which `DatabaseManager` already satisfies structurally).
- **4.4 `atlas/telemetry/`** (ADR-0039): in-process `MetricsRegistry`
  (counters/gauges/histograms w/ p50/p95, thread-safe), `timer`/`@timed`, and
  ContextVar-based `Span` tracing (`start_span`/`current_span`, nested spans share a
  trace id). Wired at the seams — `LLMService.generate/chat/embed`,
  `KnowledgeService.search`/`embed_document`, `SchedulerService` task execution
  (+ completed/failed counters), and `RagAgent.run` (span + retrieve/generate
  timers). No exporter yet; `get_metrics().snapshot()` is the future OTel/Prometheus
  hook (F2).
- **4.5 capability/plugin seam** (ADR-0040/0041): `kernel/capabilities.py`
  (`CapabilityRegistry`: register/has/get/names/describe; missing →
  `CapabilityMissingError`) — agents ask the kernel instead of importing modules and
  degrade gracefully; complements (does not replace) the DI container (F3/ADR-0043).
  `plugins/base.py` establishes the `Plugin` protocol + `BasePlugin` (boundary only;
  concrete plugins are Sprint 7). `Application` now exposes `.capabilities` and a
  `capability(name)` API; bootstrap advertises `llm`/`knowledge`/`scheduler`/
  `agent`/`ingestion`.
- **Tests**: +33 unit tests across `test_exceptions`, `test_models`,
  `test_interfaces`, `test_telemetry`, `test_capabilities` (existing
  agent/knowledge/health tests updated to the typed contracts).
- ✅ Verified: **117 pytest tests pass** (0 skipped — live Postgres + Ollama present,
  so the RAG end-to-end integration ran too); `run.py --once` boots all six services
  `[OK]` with capabilities registered and clean shutdown.

**Not in Sprint 4 (by design):** document versioning (ADR-0042) needs a migration
and lands with the Knowledge/Memory work; concrete plugins land in Sprint 7; the
remaining repos convert to models incrementally as callers move over (ADR-0036/F5).

---

## 16. Architecture Maturity Scorecard

A snapshot of the target architecture's qualities (aspirational, tracked over time):

| Area | Score | Notes |
|------|-------|-------|
| Project structure | 9.5 / 10 | Clear four-layer separation (kernel / services / plugins / agents) |
| Separation of concerns | 9 / 10 | Repositories isolate SQL; providers isolate backends |
| Scalability | 9.5 / 10 | Event-driven, single server today → multi-machine later |
| Testability | 9 / 10 | DI container + repository pattern make mocking easy |
| Long-term maintainability | 9.5 / 10 | Small stable kernel; capabilities evolve independently |

### Guiding one-liner

> **Atlas is an AI Operating System with a microkernel architecture.**
> Kernel stays small and stable. Services provide capabilities. Plugins provide
> integrations. Agents orchestrate. Agents know *what* they want, never *how* it is done.

---

## 17. Sprint 3 — Agent Layer & RAG (Detailed Plan)

> **Status:** 🕐 Proposed — for discussion before implementation (discuss-then-build).
> **Depends on:** Sprint 2 (LLM, knowledge, scheduler, health — all ✅).
> **New ADRs:** 0029–0034 (proposed).

### 17.1 Goal

Deliver the **top layer** of the four-layer architecture: an **agent** that answers
natural-language questions over Atlas' own knowledge base (retrieval-augmented
generation), plus the **ingestion source** that keeps that knowledge base fed from
`/data/atlas_data/documents`. After Sprint 3, Atlas can ingest your files and
*reason over them* — the first end-to-end "useful" loop.

```
files on disk ─▶ ingestion source ─▶ knowledge (chunk+embed) ─▶ RAG agent ─▶ answer+citations
                    (Sprint 3)            (Sprint 2)              (Sprint 3)
```

### 17.2 Guiding principles (unchanged, applied here)

- **Agents know *what*, not *how* (ADR-0006).** The RAG agent calls
  `knowledge.search(...)` and `llm.chat(...)` through kernel APIs — never SQL, never
  the Ollama HTTP client directly.
- **Repository pattern (ADR-0027).** All agent-run persistence goes through a new
  `AgentRunRepository`; the agent itself holds no SQL.
- **Resilience (ADR-0007/0032).** Every run is recorded; long/deferred runs go
  through the scheduler so they survive restarts.
- **Small stable kernel (ADR-0022).** No kernel changes required — agents wire in
  through the existing container + registry, exactly like Sprint 2 services.

### 17.3 Scope

**In scope**
- `agent` schema (migration `0007`): `agent.agents`, `agent.runs`, `agent.steps`.
- `AgentRunRepository`.
- `Agent` protocol + `AgentService` (registry/dispatcher for agents).
- `RagAgent` — retrieval-augmented QA with inline citations.
- Filesystem ingestion source under `atlas/ingestion/` (scan → extract → dedup →
  enqueue) for **text, markdown, PDF, and HTML** (ADR-0033).
- `AgentConfig` (incl. configurable `grounding`, ADR-0035) + `IngestionConfig`;
  bootstrap + container wiring.
- `run_agent` and `ingest_scan` scheduler handlers (deferred paths).
- Two small dependencies: `pypdf` (PDF text), `beautifulsoup4` (HTML → text).
- Tests (unit + live integration) and a live demo, per house style.

**Out of scope (deferred)**
- Multi-step / tool-using agents, planning loops, ReAct (Sprint 4+).
- Memory service integration (Sprint 5).
- Browser/web plugins (Sprint 6).
- REST/CLI chat interface (Sprint 7) — Sprint 3 exposes agents programmatically
  and via a small demo script only.
- **OCR of scanned/image-only PDFs** — Sprint 3 extracts the embedded text layer
  from PDFs; documents with no text layer need a future `OCRService`.

### 17.4 Design decisions (proposed — to confirm)

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| G1 | Agent-run storage | new `agent` schema / reuse `audit` | **`agent` schema** (ADR-0028/0029) |
| G2 | First agent type | RAG QA / summarizer / chat | **RAG QA** (ADR-0031) |
| G3 | Retrieval depth | fixed top-k / configurable | **configurable, default k=5** |
| G4 | Grounding strictness | strict (answer only from context) / blended | **strict default, configurable** (ADR-0035): `agent.grounding`; strict falls back to "I don't know" when no chunk clears the similarity floor |
| G5 | Citations | none / chunk-id refs / inline `[n]` | **inline `[n]` + trailing Sources list** |
| G6 | Ingestion trigger | manual / scheduled scan / filesystem watch | **scheduled scan** (poll) now; watch later |
| G7 | Ingestion file types | text+md only / +pdf/html | **text + markdown + PDF + HTML** (ADR-0033; scanned PDFs → later OCR) |
| G8 | Agent invocation | inline only / inline + scheduler | **both** (ADR-0034) |
| G9 | Prompt/citation format | hard-coded / config template | **small config knobs** (system preamble, k, sim floor) |

### 17.5 Data model — migration `0007_agent_foundation.sql`

Creates the `agent` schema (ADR-0028) and three tables. UUID PKs (ADR-0002),
`TIMESTAMPTZ` timestamps, JSONB for flexible payloads.

```
agent.agents        -- catalog of registered agents (name, kind, config snapshot)
    id UUID PK, name TEXT UNIQUE, kind TEXT, description TEXT,
    enabled BOOL, config JSONB, created_at, updated_at

agent.runs          -- one row per invocation (the unit of observability/recovery)
    id UUID PK, agent_id UUID FK→agent.agents,
    status TEXT,             -- pending → running → completed | failed | cancelled
    input JSONB,             -- {query, options}
    output JSONB,            -- {answer, citations, usage}
    error TEXT,
    started_at, finished_at, created_at
    (status pipeline mirrors scheduler.tasks; enables crash recovery)

agent.steps         -- ordered trace within a run (retrieval, generation, ...)
    id UUID PK, run_id UUID FK→agent.runs (CASCADE),
    ordinal INT, kind TEXT,  -- 'retrieve' | 'generate'
    detail JSONB,            -- retrieval: {query, k, hits:[{chunk_id, similarity}]}
                             -- generate:  {model, prompt_chars, usage}
    created_at
    UNIQUE (run_id, ordinal)
```

Rationale: `agent.runs` is the durable record (what was asked, what came back,
token/timing usage); `agent.steps` is the audit trail for *how* the answer was
produced (which chunks, which model). Both are pure observability — the agent
writes them through `AgentRunRepository`.

### 17.6 Component design

**`atlas/agents/base.py` — `Agent` protocol (ADR-0030)**

```python
@dataclass(frozen=True)
class AgentResult:
    answer: str
    citations: list[Citation]      # [{index, document_id, chunk_id, similarity, snippet}]
    usage: dict[str, Any]
    run_id: str

@runtime_checkable
class Agent(Protocol):
    name: str
    kind: str
    def run(self, query: str, **options: Any) -> AgentResult: ...
```

**`atlas/agents/rag_agent.py` — `RagAgent` (ADR-0031)**

Constructor injects only kernel-level dependencies: `KnowledgeService`,
`LLMService`, `AgentRunRepository`, plus config (`k`, `similarity_floor`,
`system_preamble`). Flow:

1. Open a run (`agent.runs` → `running`).
2. **Retrieve:** `knowledge.search(query, limit=k)` → `list[SearchResult]`.
   Record a `retrieve` step. In `grounding="strict"` (default), if nothing clears
   `similarity_floor`, short-circuit to a grounded "I don't have information on
   that" answer. In `grounding="blended"` (ADR-0035), the model may answer from its
   own knowledge, clearly marking which parts are *not* from the knowledge base.
3. **Assemble context:** number the surviving chunks `[1..n]`, build a context
   block, and a system prompt (whose grounding instruction is chosen by
   `agent.grounding`) telling the model to cite sources as `[n]` and append a
   trailing "Sources" list.
4. **Generate:** `llm.chat([system, user])` → `LLMResponse`. Record a `generate`
   step (model, usage).
5. **Finalize:** map `[n]` → `Citation` (document_id, chunk_id, similarity,
   snippet); close the run (`completed`, store `output`), or `failed` + `error`.

Reuses existing types verbatim: `SearchResult` (`chunk_id`, `document_id`,
`ordinal`, `content`, `similarity`), `ChatMessage`, `LLMResponse`.

**`atlas/services/agent_service.py` — `AgentService` (ADR-0030)**

Kernel-managed service (`name = "agent"`, conforms to the `Service` protocol:
`start/stop/health_check`). Holds a small registry `name → Agent`, exposes
`run(agent_name, query, **opts) -> AgentResult` and `list()`. `health_check`
reports registered agent count and that its dependencies are resolvable.
`run_agent_task(payload)` is the scheduler handler (ADR-0034) for deferred runs.

**`atlas/repositories/agent_run_repo.py` — `AgentRunRepository` (ADR-0027)**

Subclasses `BaseRepository`; methods: `create_agent`/`get_agent_by_name`,
`open_run`, `finish_run`, `fail_run`, `add_step`, `recent_runs`. Only layer with
SQL against the `agent` schema.

**`atlas/ingestion/` — `FilesystemSource` + extractors (ADR-0033)**

Scans `cfg.paths.documents` for configured extensions and dispatches each file to a
small **extractor** by type, producing plain text:

- `.txt` / `.md` → read UTF-8 directly.
- `.pdf` → `pypdf` extracts the embedded text layer (page-joined). Files with no
  text layer (scanned images) are skipped with a logged warning → future OCR.
- `.html` / `.htm` → `beautifulsoup4` strips tags/scripts/styles to visible text.

Extractors live in `atlas/ingestion/extractors.py` behind a tiny
`extract(path) -> str | None` protocol, so new formats are additive. The source
then calls `knowledge.ingest_text(source="filesystem", content=<text>, uri=<path>,
title=<name>, content_type=<mime>)`. The existing checksum dedup in
`DocumentRepository` makes re-scans idempotent — an unchanged file is skipped; a
changed file re-ingests. `embed=False` on ingest so the resilient scheduler path
(`embed_document`) does the embedding. `scan_task` is registered as an
`ingest_scan` scheduler task so periodic ingestion survives restarts (G6).

### 17.7 Config additions — `atlas/config/manager.py`

```python
class AgentConfig(BaseModel):
    retrieval_k: int = 5              # chunks retrieved per query
    similarity_floor: float = 0.35   # below this, strict mode answers "I don't know"
    max_context_chars: int = 6000    # cap assembled context
    grounding: str = "strict"        # "strict" | "blended" (ADR-0035)
    system_preamble: str = "You are Atlas, answering from the provided context."

class IngestionConfig(BaseModel):
    enabled: bool = True
    extensions: list[str] = [".txt", ".md", ".pdf", ".html", ".htm"]
    scan_interval: int = 300         # seconds between scheduled scans (0 = manual)
```

Both added to `AtlasConfig` with defaults (`agent: AgentConfig = AgentConfig()`,
`ingestion: IngestionConfig = IngestionConfig()`); env overrides via
`ATLAS_AGENT_*` / `ATLAS_INGESTION_*` come free from the existing loader.

> **How to switch grounding later (ADR-0035):** set `agent.grounding: blended` in
> `config/local.yaml` (or `ATLAS_AGENT_GROUNDING=blended`). No code change — the
> agent picks the system-prompt grounding clause from this value at run time. Keep
> `strict` while you want answers provably tied to your documents; switch to
> `blended` when you want the model to fill gaps from its own knowledge (it will
> label those parts as not sourced from the knowledge base).

### 17.8 Wiring — `atlas/kernel/bootstrap.py`

No kernel changes; follows the Sprint 2 pattern exactly:

- Build `AgentRunRepository(db_manager)`, `RagAgent(...)`, `AgentService(...)`.
- `container.register_instance("agent", agent_service)` (+ `agent_run_repo`).
- `registry.register(agent_service)` — start order becomes
  **database → llm → scheduler → agent → health_monitor** (agent after its deps).
- `handlers.register("run_agent", agent_service.run_agent_task)` and
  `handlers.register("ingest_scan", fs_source.scan_task)`.
- If `cfg.ingestion.scan_interval > 0`, enqueue a recurring `ingest_scan` task.

### 17.9 Sub-sprints

```
Sprint 3.1  Migration 0007 (agent schema) + AgentRunRepository
Sprint 3.2  Agent protocol + AgentService (registry, lifecycle, health)
Sprint 3.3  RagAgent (retrieve → assemble → generate → cite) + run persistence
Sprint 3.4  Filesystem ingestion source + scheduler handlers
Sprint 3.5  Config + bootstrap wiring + tests + live demo
```

### 17.10 Testing strategy

- **Unit (no DB/Ollama):** context assembly + citation mapping (deterministic),
  similarity-floor fallback, ingestion file discovery/dedup logic — all via
  in-memory fakes of `KnowledgeService`/`LLMService`/repos (as Sprint 2 did).
- **Integration (live Postgres + Ollama, skip-if-unavailable):** apply `0007`;
  ingest a temp file → embed → `RagAgent.run(question)` returns a grounded answer
  citing the right chunk; run row + step rows recorded; `run.py --once` shows
  `[OK] agent`.
- Keep the `test_migrations` foundation check flexible (already prefix-based).

### 17.11 Completion criteria

```bash
uv run pytest -q            # all green incl. live agent RAG integration
uv run python run.py --once # [OK] agent: N agent(s); rag ready
```

Plus a live demo: drop a `.md` file in `/data/atlas_data/documents`, run a scan,
ask the RAG agent a question about it, and get a correct answer **with a citation**
pointing back to the source chunk — then clean up the demo doc.

### 17.12 Open questions for you — ✅ answered 2026-07-11

| # | Question | Decision |
|---|----------|----------|
| Q1 | `agent` schema now vs. reuse `audit`? | ✅ **new `agent` schema** (migration `0007`) |
| Q2 | Strict grounding vs. blended? | ✅ **strict default, configurable** to blended later (ADR-0035) |
| Q3 | Ingestion trigger? | ✅ **scheduled scan (poll)** |
| Q4 | File types? | ✅ **text + md + PDF + HTML** (deviation from recommendation — PDF/HTML included now) |
| Q5 | Citation style? | ✅ **inline `[n]` + trailing Sources list** |

Decisions locked (ADR-0029–0035 Accepted). Building order: Sprint 3.1 → 3.5.
Any deviation discovered during implementation will be raised for confirmation
before proceeding.

---

## 18. Cross-Cutting Foundations & Revised Roadmap

> **Status:** ✅ Accepted as requirements (ADR-0036–0044, 2026-07-11).
> **Why now:** these are structural concerns best introduced *before* the codebase
> reaches ~20–30k lines, while there are few call sites to migrate. They are added
> **incrementally** (mostly Sprint 4), not in one big-bang refactor.

### 18.1 Guiding rule — the kernel is not a god object (ADR-0043)

Responsibilities stay strictly separated as Atlas grows:

| Layer | Owns | Never does |
|-------|------|-----------|
| **Kernel** | startup/shutdown, lifecycle, DI, registry, capability registry | business logic, SQL, integrations |
| **Services** | business logic (capabilities) | persistence details, external I/O |
| **Repositories** | persistence (SQL) | business rules, orchestration |
| **Plugins** | external integrations | knowing about agents |
| **Agents** | orchestration & decisions | SQL, provider calls, imports of integrations |

Every new item below is checked against this table: nothing new goes *into* the
kernel unless it is lifecycle/DI/registry/capability wiring.

### 18.2 Domain models — `atlas/models/` (ADR-0036)

Today repositories return raw `dict`s that cross module boundaries (documents,
chunks, tasks, agent runs, health, memory). We introduce typed models so shape is
explicit and mistakes are caught early.

- Frozen dataclasses by default (fast, dependency-free); Pydantic where validation
  or (de)serialization at an edge (API, config) adds value. *(Open: dataclass vs
  Pydantic split — see §18.9.)*
- Models: `Document`, `DocumentVersion`, `Chunk`, `Embedding`, `Task`, `TaskRun`,
  `AgentRun`, `AgentStep`, `HealthRecord`, `MemoryItem`, plus value types already in
  place (`SearchResult`, `Citation`, `AgentResult`).
- **Repositories become the mapping layer** (rows ↔ models): `fetch_* -> Model`.
  This is where ADR-0027 (SQL only in repos) meets ADR-0036 (models only above).
- Migration is incremental: introduce `models/`, convert one repository at a time,
  keep dict-returning methods until callers move over.

### 18.3 Typed exceptions — `atlas/exceptions/` (ADR-0037)

A single root `AtlasError` with per-domain subclasses so callers can catch
precisely and telemetry can classify failures:

```
AtlasError
├── ConfigError
├── DatabaseError        (connection, migration, query)
├── LLMError             (provider unreachable, model missing, generation)
├── KnowledgeError       (ingest, embed mismatch, search)
├── AgentError           (run failed, no such agent)
└── PluginError          (load, capability missing)
```

Replaces bare `RuntimeError`/`KeyError`/`Exception` at boundaries (e.g. the
embed-count-mismatch `RuntimeError`, `AgentService.get` `KeyError`). Internal
`except Exception` guards that must never crash a loop (scheduler worker, health
monitor) stay, but re-raise typed errors where they surface to callers.

### 18.4 Provider interfaces — `atlas/interfaces/` (ADR-0038)

Services depend on abstract protocols, not concrete backends. `LLMProvider`
already exists (`atlas/llm/provider.py`) and is the template. We add:

- `EmbeddingProvider` — split embedding from chat so a dedicated embedding backend
  (or a different model server) can be swapped independently.
- `MemoryProvider` — abstraction for the Sprint 6 memory store (pgvector today;
  Redis/other later).
- `StorageProvider` — optional abstraction over the repository layer for non-PG
  backends far in the future.

Consolidating existing protocols under `interfaces/` (re-exporting from their
current homes for back-compat) keeps the "depend on abstractions" rule visible.

### 18.5 Telemetry — `atlas/telemetry/` (ADR-0039)

Introduced early so instrumentation is habitual, not retrofitted:

- `timers.py` — `@timed("knowledge.embed")` decorator + `with timer(...)` context
  manager; emits duration to metrics.
- `metrics.py` — in-process counters/gauges/histograms (pluggable exporter later:
  Prometheus/OTel). No new heavy dependency for the first cut.
- `tracing.py` — lightweight span context so one request can be followed across
  `Agent → Knowledge → Chunking → Embedding → LLM`.

Wired at the seams (service methods, scheduler task execution, agent steps) so the
whole pipeline is timed automatically. Optional persistence to `audit`/`analytics`
later.

### 18.6 Capability Registry (ADR-0040)

A kernel component (`kernel/capabilities.py`) mapping capability name → provider.
Services and plugins register the capabilities they offer; agents ask the kernel
rather than importing modules:

```python
if kernel.capabilities.has("browser"):
    result = kernel.capabilities.get("browser").search(...)
```

This is the seam that makes plugins truly optional and swappable (ADR-0041): an
agent degrades gracefully when a capability is absent instead of failing an import.
Complements — does not replace — the DI container (container = *how* to build;
capability registry = *what* is available to agents). Kept minimal to honour
ADR-0043.

### 18.7 Plugins — everything external (ADR-0041)

All external integrations become plugins under `atlas/plugins/` that self-register
and expose capabilities: `filesystem`, `browser`, `postgres`, `github`, `shell`,
`weather`, `email`, `scada`, `calendar`. Long term even Ollama can move behind an
`llm` plugin. Built out in **Sprint 7**; the base protocol + capability
registration land in Sprint 4 so the boundary exists before the first plugin.

> The current `FilesystemSource` (Sprint 3, under `atlas/ingestion/`) is the
> pre-plugin form of the filesystem integration; it will migrate to a
> `plugins/filesystem/` capability in Sprint 7 without changing the knowledge
> service.

### 18.8 Document versioning (ADR-0042)

Replaces "delete the old document row when a file changes". Instead:

```
Document (logical)
  ├── Version 1  (checksum A)
  ├── Version 2  (checksum B)   ← active
  └── Version 3  (checksum C)   ← active
```

- A `Document` identity keyed by stable `uri`/source; each ingest with a new
  checksum creates a `DocumentVersion`. The latest is `active`; search targets
  active versions by default, with history retained for audit/rollback.
- Requires a schema change (a future migration `00NN`): add
  `knowledge.document_versions` (or version columns) and point chunks/embeddings at
  a version rather than the document. Designed in the Memory/Knowledge deepening
  work; **not** retrofitted into Sprint 3.
- Until then, the Sprint 3 behaviour (new checksum → new document row) stands as a
  known, acceptable interim.

### 18.9 Open sub-questions (small)

| # | Question | Recommendation |
|---|----------|----------------|
| F1 | Models: dataclasses everywhere, or Pydantic at edges (API/config)? | **dataclasses internally, Pydantic at edges** |
| F2 | Telemetry backend for v1? | **in-process; OTel/Prometheus exporter later** |
| F3 | Capability Registry vs DI container overlap? | **keep both; container builds, registry advertises** |
| F4 | Do foundations get their own Sprint 4, or fold into each feature sprint? | ✅ **LOCKED: dedicated Sprint 4 (hardening)** — maintainer confirmed 2026-07-11: give it a dedicated sprint so enough research/time is spent making the foundations strong before proceeding |
| F5 | Convert repos to models big-bang or incrementally? | **incrementally, one repo at a time** |

### 18.10 Introduction sequence (Sprint 4 — Foundations Hardening) — ✅ COMPLETE

```
4.1  exceptions/  (root + per-domain)         ✅ — lowest risk, immediate value
4.2  models/      (+ convert 1–2 repos)        ✅ — incremental, dict→model
4.3  interfaces/  (consolidate protocols)      ✅ — EmbeddingProvider split
4.4  telemetry/   (timers→metrics→tracing)     ✅ — wired at service seams
4.5  kernel/capabilities.py + plugins/base.py  ✅ — the plugin/capability seam
```

Each sub-step kept all tests green and the app booting; nothing here changed
external behaviour, only structure and observability. Document versioning
(ADR-0042) remains scheduled with the Knowledge/Memory work (needs a migration),
not in Sprint 4.

---

## 19. Sprint 5 — REST API + CLI + Auth (Detailed Plan)

> **Status:** ✅ COMPLETE (2026-07-11). **Depends on:** Sprints 1–4.
> **New ADRs:** 0045 (FastAPI), 0046 (API-key auth), 0047 (argparse CLI).

### 19.1 Goal

Give Atlas an **official interface** (ADR-0044, interface-first): an authenticated
REST API and a unified `atlas` CLI, both driving the *same* kernel services agents
use. No new database schema — this sprint is pure surface area.

```
HTTP client ─┐
             ├─▶ Atlas API (FastAPI) ─┐
CLI (atlas) ─┘                        ├─▶ container.resolve(...) ─▶ services ─▶ repos/providers
                                      │      (agent, knowledge, ...)
             in-process (CLI) ────────┘
```

### 19.2 Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| I1 | HTTP framework | **FastAPI + uvicorn** (ADR-0045) — Pydantic v2-native, OpenAPI docs, sync endpoints via threadpool |
| I2 | Auth model | **Static API key**, `Authorization: Bearer`, keys from `ATLAS_API_KEYS` (ADR-0046); constant-time compare; **fail closed** if unset |
| I3 | CLI | **stdlib argparse**, single `atlas` entry point (ADR-0047); one-shot commands run in-process |
| I4 | Sync vs async | sync endpoints (ADR-0002); services unchanged |
| I5 | DB-backed keys | deferred; `.env` keys are enough for a personal, self-hosted node |

### 19.3 Components

- **`atlas/config/manager.py`** — `ApiConfig` (host, port, `keys`, `docs_enabled`,
  `cors_origins`). Keys are a secret: `ATLAS_API_KEYS` (comma-separated) handled in
  the env-override step like `ATLAS_DB_PASSWORD` (ADR-0013); `defaults.yaml` gained a
  documented `api:` block (no secrets).
- **`atlas/api/`** —
  - `schemas.py`: request/response Pydantic models (the public contract, separate
    from domain models — the "validation at the edge" half of §18.9 F1).
  - `auth.py`: `require_api_key` bearer dependency; fail-closed.
  - `routes.py`: `public_router` (`GET /health`) + `v1_router` (auth-gated):
    `GET /v1/health`, `GET /v1/agents`, `POST /v1/agents/{name}/run`,
    `POST /v1/knowledge/search`, `POST /v1/knowledge/ingest`.
  - `app.py`: `create_app(application)` — wires routes, CORS, and an `AtlasError`
    handler mapping typed exceptions → HTTP codes (`AgentNotFoundError`/
    `CapabilityMissingError`→404, `LLMError`→502, other `AtlasError`→500). Lifespan
    starts/stops the kernel, so the API server *is* a running Atlas.
  - `server.py`: `serve()` builds the Application, wraps it, runs uvicorn.
- **`atlas/cli/main.py`** — `atlas serve | status | agents | ask | search | ingest`.
  One-shot commands resolve services from the container **without** starting the
  lifecycle (no worker threads); `serve` runs the API; `status` mirrors
  `run.py --once`. Console script `atlas` added to `pyproject.toml`.

### 19.4 Testing

- **API (hermetic):** a fake Application is injected into `app.state`; the
  `TestClient` is used *without* the context manager so the kernel lifespan never
  runs. Covers public vs authed routes, 401 (missing/bad key, fail-closed),
  agents list/run, unknown-agent→404, search, ingest, request validation (422),
  detailed health, and OpenAPI availability.
- **CLI:** the argparse parser is tested directly; handlers run with a fake app,
  covering agents/ask/search/ingest (incl. missing-file → exit 1).

### 19.5 Verified

- **137 pytest tests pass** (+20 API/CLI over Sprint 4's 117); no schema change.
- Live: `atlas agents` → `rag`; `atlas status` → all six services `[OK]`.
- Live HTTP (`atlas serve`, `ATLAS_API_KEYS` set): `GET /health` → 200; unauthed
  `/v1/agents` → 401; keyed `/v1/agents` → `{"agents":["rag"]}`; keyed
  `POST /v1/agents/rag/run` → grounded answer + persisted `run_id`.

### 19.6 Out of scope (deferred)

- DB-backed / revocable API keys, rate limiting, per-key scopes.
- Streaming responses (SSE/WebSocket) for agent output.
- A web UI (CORS hooks are in place for a future local frontend).
- Async endpoints (revisit if/when a service becomes async, ADR-0002).

---

## 20. Sprint 6 — Memory System (Detailed Plan)

> **Status:** ✅ COMPLETE (2026-07-11). **Depends on:** Sprints 1–5.
> **New ADRs:** 0048 (single-table memory, partial HNSW, event-time dimension).
> **Migration:** `0008_memory_foundation.sql` (first new schema object since Sprint 3;
> applied by the `atlas` role via `atlas-db migrate` — atlas owns `memory` from 0001).

### 20.1 Goal

Give Atlas a **memory** it can write to and recall from — the first realisation of
the `MemoryProvider` interface stubbed in Sprint 4 (ADR-0038). Three kinds under one
roof:

- **working** — short-term, session-scoped, expires (TTL); not embedded by default.
- **episodic** — append-heavy event log, time-ordered by `occurred_at`; embedded.
- **semantic** — durable facts, embedded, recalled by similarity.

```
remember(content, kind) ─▶ (embed if semantic/episodic) ─▶ memory.items
recall(query)           ─▶ embed query ─▶ cosine search over embedded, live rows
                                          (expired rows filtered; prune reclaims)
```

### 20.2 Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| M1 | Schema shape | **Single `memory.items`** table + `kind` discriminator + inline nullable `embedding` (ADR-0048). User-steered after weighing split-tables / items+embeddings |
| M2 | Scale strategy | **Partial HNSW** (`WHERE embedding IS NOT NULL`) + partial indexes on kind/scope/expiry; repo-isolated so partitioning is a later, transparent migration |
| M3 | Date dimension | **`occurred_at`** event-time (distinct from audit `created_at`), indexed `(kind, occurred_at DESC)` — user-requested; enables "around date X" recall + future RANGE partitioning |
| M4 | Taxonomy scope | **All three kinds now** (working/episodic/semantic) with semantic recall + working-memory TTL |
| M5 | Integration | **Standalone** service + API/CLI; deep RAG/agent wiring deferred to Sprint 8 |
| M6 | Embeddings | **Reuse** `LLMService.embed` + `nomic-embed-text` (768-dim) + pgvector cosine — same stack as the knowledge base |
| M7 | Expiry | recall filters `expires_at`; a durable **`memory_prune`** scheduler task (self-re-enqueuing, like `ingest_scan`) physically reclaims |

### 20.3 Components

- **`database/migrations/0008_memory_foundation.sql`** — `memory.items`
  (`kind`/`scope`/`content`/`embedding vector(768)`/`embedding_model`/`importance`/
  `metadata`/`occurred_at`/`expires_at`/`created_at`/`updated_at`), `kind` CHECK,
  partial HNSW cosine index, `(kind, occurred_at DESC)`, `(scope, occurred_at DESC)`,
  partial `expires_at` index.
- **`atlas/models/memory.py`** — `MemoryItem` frozen dataclass (ADR-0036); carries a
  transient `similarity` set on recall. Embedding stays in pgvector, off the model.
- **`atlas/repositories/memory_repo.py`** — `MemoryRepository` (model-returning from
  day one): `add / get / semantic_search / recent / forget / prune_expired / count`.
  Recall/recent filter `(expires_at IS NULL OR expires_at > now())`.
- **`atlas/interfaces/memory.py`** — `MemoryProvider` updated to return typed
  `MemoryItem`s.
- **`atlas/services/memory_service.py`** — `MemoryService` (kernel Service +
  `MemoryProvider`): `remember / recall / recent / forget / prune`, embedding policy
  per kind, TTL, similarity floor, and the `memory_prune` scheduler handler.
- **`atlas/config/manager.py` + `config/defaults.yaml`** — `MemoryConfig`
  (`recall_k`, `similarity_floor`, `working_ttl_seconds`, `embed_working`,
  `prune_interval`).
- **`atlas/kernel/bootstrap.py`** — build `MemoryService` after the scheduler (so it
  can enqueue its prune chain); register in container + `CapabilityRegistry`
  (`memory`) + lifecycle; register the `memory_prune` handler.
- **`atlas/api/`** — `POST /v1/memory/remember`, `POST /v1/memory/recall`,
  `GET /v1/memory/recent`, `DELETE /v1/memory/{id}` + schemas.
- **`atlas/cli/main.py`** — `atlas remember | recall | forget`.

### 20.4 Testing

- **Model/service (hermetic):** `from_row`/`to_dict`; remember embeds semantic,
  working gets TTL + no embed, explicit TTL override, recall similarity floor,
  forget/prune passthrough, health count. Fakes only — no DB/Ollama.
- **Repository (integration, DB-gated):** add → get → semantic_search (similarity
  populated) → recent → forget; expired rows excluded from recall and reclaimed by
  `prune_expired`.
- **API/CLI:** remember/recall/recent/forget over HTTP (incl. bad-kind → 422, auth
  required) and the three CLI commands (incl. `forget` not-found → exit 1).

### 20.5 Verified

- **158 pytest tests pass** (+21 over Sprint 5's 137: memory model/service/repo
  plus extended API/CLI coverage).
- Migration `0008` applied (`atlas-db migrate` → `Applied migrations: 0008`).
- Live end-to-end: `atlas remember` embedded via Ollama and stored in pgvector;
  `atlas recall` returned it at similarity **0.628**; `atlas forget` removed it.

### 20.6 Out of scope (deferred)

- Deep agent integration (recall into RAG context, write-back of run summaries) —
  Sprint 8, with the multi-agent redesign.
- Table **partitioning** (LIST by kind / RANGE by `occurred_at`) — deliberately not
  built now; the repository seam makes it a transparent later migration (ADR-0048).
- Importance-decay / automatic consolidation / summarisation of old episodic memory.
- Cross-encoder re-ranking of recalls; hybrid keyword+vector recall.

---

## 21. Sprint 7 — Plugins & Tools (Detailed Plan)

> **Status:** ✅ COMPLETE (2026-07-11). **Depends on:** Sprints 1–6.
> **New ADRs:** 0049 (config-list plugin loading), 0050 (ToolRegistry).
> **No migration** — pure code/kernel surface.

### 21.1 Goal

Turn the Sprint 4 plugin *seam* (`Plugin`/`BasePlugin` + `CapabilityRegistry`) into a
working **plugin system**: load external integrations from config, let them
self-register **capabilities** (coarse) and **tools** (fine-grained, invokable), and
expose those tools over API/CLI. This is the foundation Sprint 8's tool-selecting
agents build on.

```
config.plugins.enabled ─▶ PluginManager.load ─▶ build(config) ─▶ Plugin
                                                     │
                        plugin.register(kernel) ─────┼─▶ capabilities.register(...)
                                                     └─▶ tools.register("web.fetch", ...)
agents / API / CLI ─▶ kernel.invoke_tool("web.fetch", url=...) ─▶ plugin action
```

### 21.2 Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| P1 | Discovery | **Explicit config list** (ADR-0049) — `plugins.enabled` dotted module paths; `build(config)` factory; fail-closed, no disk/entry-point scanning |
| P2 | Action model | **ToolRegistry** (ADR-0050) — named callable + description + param hints; complements capabilities; the Sprint 8 selection catalog |
| P3 | Concrete plugins | **filesystem + web** only now; github/database/email deferred (need creds/services) but trivial to add via a new module + one `enabled` line |
| P4 | Resilience | One bad plugin **never blocks boot** — load/register/start errors captured per-plugin and surfaced via the `plugins` health entry |
| P5 | Lifecycle | `PluginManager` is a kernel **Service** owning plugin start/stop/health; registered last so the health monitor observes it |
| P6 | Filesystem safety | Reads/lists **sandboxed** to a configured root (default `paths.documents`); path-escape + size-cap enforced |
| P7 | Web safety | http(s) only; body size-capped; HTML reduced to text via the shared `html_to_text` extractor |

### 21.3 Components

- **`atlas/kernel/tools.py`** — `Tool` + `ToolRegistry` (register/has/get/invoke/
  names/describe); duplicate name → `ToolError`, missing → `ToolNotFoundError`.
- **`atlas/kernel/application.py`** — Application gains `tools` + `invoke_tool(name, **kw)`.
- **`atlas/plugins/manager.py`** — `PluginManager` (Service): `load(config)`,
  `register_all(kernel)`, lifecycle, aggregated health, captured `errors`.
- **`atlas/plugins/filesystem_plugin.py`** — `FilesystemPlugin` (`fs.list`, `fs.read`),
  sandboxed to a root; `build(config)`.
- **`atlas/plugins/web_plugin.py`** — `WebPlugin` (`web.fetch`), via the resilient net
  layer (throttle/robots/backoff/cache) + HTML→text; `build(config)`.
- **`atlas/plugins/search_plugin.py`** — `SearchPlugin` (`search` cap, `web.search`),
  ordered `SearchProvider`s with fallback (D5); `build(config)` (Stage 2 S13b).
- **`atlas/plugins/downloader_plugin.py`** — `DownloaderPlugin` (`downloader`,
  `web.download`) → sandboxed downloads dir; `build(config)` (Stage 2 S13b).
- **`atlas/ingestion/extractors.py`** — extracted a reusable `html_to_text(html)`.
- **`atlas/config/manager.py` + `defaults.yaml`** — `PluginsConfig`
  (`enabled`, `filesystem.{root,max_bytes}`, `web.{timeout,max_bytes,user_agent}`);
  both built-ins enabled by default.
- **`atlas/kernel/bootstrap.py`** — construct `Application` earlier (holds shared
  registries by reference), then load + register plugins, register the manager as a
  service + `plugins` capability; health monitor stays last.
- **`atlas/api/`** — `GET /v1/plugins`, `GET /v1/tools`, `POST /v1/tools/{name}/invoke`;
  `ToolNotFoundError`→404, other `PluginError`→400.
- **`atlas/cli/main.py`** — `atlas plugins | tools | tool <name> [--arg k=v ...]`.
- **`atlas/exceptions/plugin.py`** — added `ToolError`/`ToolNotFoundError`.

### 21.4 Testing

- **ToolRegistry:** register/invoke, duplicate → `ToolError`, missing → `ToolNotFoundError`,
  sorted describe catalog.
- **PluginManager:** loads both built-ins from config; bad module recorded (no raise) +
  unhealthy; `register_all` advertises capabilities + tools on a fake kernel; a plugin
  that throws on `start` is captured, not propagated.
- **FilesystemPlugin:** list/read; path-escape → `PluginError`; size cap enforced.
- **WebPlugin:** HTML→text (script stripped), plain-text passthrough (httpx
  monkeypatched); non-http scheme → `PluginError`.
- **API/CLI:** list plugins/tools, invoke tool, unknown tool → 404, auth required;
  CLI plugins/tools/tool (incl. malformed `--arg` → exit 1).

### 21.5 Verified

- **181 pytest tests pass** (+23 over Sprint 6's 158).
- Live: `atlas plugins` → `filesystem`, `web`; `atlas tools` → the three tools;
  `atlas tool fs.list --arg path=.` → JSON listing; `atlas tool web.fetch --arg
  url=https://example.com` → HTTP 200 with extracted readable text.

### 21.6 Out of scope (deferred)

- **github / database / email** plugins (need external creds/services) — add a module
  + one `enabled` line each; the seam is proven.
- Filesystem **writes** (create/edit/delete) — read-only for now; write actions want
  a permission model first.
- Per-tool **param schemas / validation** and permission scopes — Sprint 8 may layer
  typed schemas on the ToolRegistry for LLM tool-calling.
- Third-party plugin distribution via Python **entry points** (ADR-0049 leaves room).

---

## 22. Sprint 8 — Multi-Agent (Detailed Plan)

> **Status:** ✅ COMPLETE (2026-07-11). **Depends on:** Sprints 1–7 (esp. the ToolRegistry).
> **New ADRs:** 0051 (ReAct + prompt JSON tool-calling), 0052 (agents-as-tools).
> **No migration** — reuses the `agent` schema (runs/steps) from Sprint 3.

### 22.1 Goal

Give Atlas an agent that can **reason and act**: pick tools, run them, read the
results, and iterate to an answer — including delegating to other agents. This is
the orchestration layer the whole stack was built toward.

```
query ─▶ [system prompt = preamble + tool catalog + JSON protocol]
        loop (≤ max_iterations):
          LLM → {"tool","args"} ─▶ ToolRegistry.invoke ─▶ "Observation: ..." ─┐
          LLM → {"final": ...}   ─▶ break ◀───────────────────────────────────┘
        reflection pass → final answer   (every step persisted to agent.steps)
```

### 22.2 Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| A1 | Pattern | **ReAct + reflection** (ADR-0051) — iterative reason→act→observe, then a self-review pass; bounded by `max_iterations` |
| A2 | Tool-calling | **Prompt-based JSON** (ADR-0051) — catalog rendered into the prompt; one JSON object per turn, parsed robustly (fenced/embedded tolerated). Model-agnostic, hermetically testable |
| A3 | Multi-agent | **Agents-as-tools** (ADR-0052) — `agent.rag` registered in the ToolRegistry; the assistant delegates via the same path as plugin tools |
| A4 | Reasoning mode | Ollama **think off** for this agent — the JSON `thought` field carries reasoning; avoids slow/timeout-prone CoT on `qwen3:4b` |
| A5 | Robustness | Tool errors become observations (loop continues); parse failures nudge + retry; step-limit forces a best-effort final; empty answers get a fallback |
| A6 | Observability | Reuses `agent.runs`/`agent.steps` — every act/observe/final/reflect step is persisted (ADR-0032) |

### 22.3 Components

- **`atlas/agents/react_agent.py`** — `ReActAgent` (`name="assistant"`, `kind="react"`):
  the loop, JSON action parsing, tool invocation, forced-final, reflection, and
  run/step persistence (mirrors `RagAgent`).
- **`atlas/config/manager.py` + `defaults.yaml`** — `ReactConfig`
  (`max_iterations`, `reflection`, `max_observation_chars`, `temperature`, `think`).
- **`atlas/kernel/bootstrap.py`** — builds the assistant (holding the shared
  ToolRegistry by reference, so it sees plugin tools), registers it in the
  `AgentService`, and registers each other agent as a tool (`agent.rag`).
- No API/CLI change needed: `POST /v1/agents/assistant/run` and
  `atlas ask "..." --agent assistant` work through the existing agent surface.

### 22.4 Testing

- **13 hermetic tests** (`tests/test_react.py`) with a scripted fake LLM + real
  ToolRegistry: direct final; tool→observation→final (observation actually fed
  back); tool error → observation, loop continues; parse-error recovery; step-limit
  forced final; reflection revises / keeps-on-empty; agents-as-tools delegation;
  JSON parsing (plain/fenced/embedded/garbage); config snapshot.

### 22.5 Verified

- **194 pytest tests pass** (+13 over Sprint 7's 181).
- Live (real Ollama `qwen3:4b`): `atlas agents` → `assistant`, `rag`;
  `atlas ask "What is 12 times 8?" --agent assistant` → `12 × 8 = 96`
  (reason → final → reflection → run/steps persisted).
- **Bug fixed during smoke:** the `final` step shared an `ordinal` with the
  reflection step → `uq_agent_steps_run_ordinal` violation crashed runs; fixed by
  incrementing `ordinal` after the final step.

### 22.6 Out of scope / caveats (deferred)

- **Model latency:** heavy multi-step runs on `qwen3:4b` can exceed the 120s
  per-call `llm.timeout` on modest hardware. For interactive agent use, raise
  `llm.timeout` or point `llm.model` at a faster model. (Logic is fully unit-tested
  independent of model speed.)
- **Native Ollama tool-calling** (function schemas) — deferred behind the same
  interface (ADR-0051).
- **Explicit planner** (decompose-then-execute) and cross-agent memory sharing —
  the ReAct loop covers current needs; revisit if multi-step planning grows.
- **Per-tool typed param schemas / validation** for stricter tool-calling.

---

## 23. Sprint 9 — Operations (Detailed Plan)

> **Status:** ✅ COMPLETE (2026-07-11). **Depends on:** Sprints 1–8.
> **New ADRs:** 0053 (systemd-first + Docker artifacts), 0054 (Prometheus + JSON metrics),
> 0055 (scheduler-driven pg_dump backups).
> **No migration** — backups dump the existing schemas; nothing new persisted.

### 23.1 Goal

Make Atlas **deployable, observable, and recoverable** on a self-hosted node:
run it as a managed service, scrape its metrics, and back the database up on a
schedule that survives restarts — without adding external daemons or cron.

```
systemd atlas.service ─▶ atlas serve ─▶ kernel (scheduler/health/ingestion/memory-prune/backup)
                                         │
       Prometheus ──scrape──▶ GET /metrics (text)   GET /v1/metrics (JSON, authed)
                                         │
       scheduler "backup" task ─▶ pg_dump -Fc ─▶ /data/atlas_data/backups (retention N)
                                         └─re-enqueue(+interval)┘   restore via scripts/restore.sh
```

### 23.2 Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| O1 | Process model | **systemd-first + optional Docker** (ADR-0053) — one `atlas.service` runs `atlas serve`, whose lifespan boots the full kernel (scheduler, health, ingestion, memory-prune, backups). Postgres + Ollama on host. A Dockerfile + compose (app + pgvector) ship for portability |
| O2 | Monitoring | **Prometheus `/metrics` (public text) + JSON `/v1/metrics` (authed)** (ADR-0054) — renders the existing in-process telemetry `snapshot()` (ADR-0039); no client library. Gated by `api.metrics_enabled` |
| O3 | Backups | **Scheduler-driven `pg_dump -Fc` with retention** (ADR-0055) — a durable `backup` task self-re-enqueues (same pattern as ingestion/memory-prune), prunes to `backup.retention`, plus on-demand `atlas backup` and a `pg_restore` script |
| O4 | Secrets | DB password passed to `pg_dump` via `PGPASSWORD` env (never argv/process list); sourced from config (ADR-0013). systemd `EnvironmentFile=/etc/atlas/atlas.env` |
| O5 | Single service | Not a separate API vs worker split — the API server already starts the kernel; one unit avoids two competing schedulers on one box |

### 23.3 Components

- **`atlas/telemetry/prometheus.py`** — `render_prometheus(snapshot)`: counters/gauges →
  `atlas_<name>{labels} value`, histograms → `_count/_sum/_avg/_max/_p50/_p95`;
  names sanitized, label values escaped.
- **`atlas/ops/backup.py`** — `BackupManager` (a lifecycle `Service`): `backup()`
  (pg_dump custom format), `prune()` (retention), `backup_task()` (re-enqueues),
  `start()` (seeds one chain, idempotent via `count_pending`), `health_check()`.
- **`atlas/api/routes.py`** — public `GET /metrics` (Prometheus text) + authed
  `GET /v1/metrics` (JSON), both 404 when `metrics_enabled=false`.
- **`atlas/cli/main.py`** — `atlas backup` (on-demand dump).
- **`atlas/config/manager.py` + `defaults.yaml`** — `BackupConfig`
  (`enabled`, `interval_seconds`, `retention`, `pg_dump_path`, `pg_restore_path`),
  `paths.backups`, `api.metrics_enabled`.
- **`atlas/kernel/bootstrap.py`** — builds the `BackupManager`, registers the
  `backup` handler, and wires it as a service/capability/container entry.
- **Deploy artifacts** — `deploy/systemd/atlas.service` (hardened unit) +
  `deploy/atlas.env.example`; `deploy/docker/Dockerfile` + `docker-compose.yml`
  (app + pgvector Postgres, Ollama via `host.docker.internal`) + `.dockerignore`;
  `scripts/restore.sh` (idempotent `pg_restore --clean --if-exists`).

### 23.4 Testing

- **20 new tests.** `tests/test_ops.py` (Prometheus rendering: counters/gauges/
  labels/histograms/escaping/empty; BackupManager: pg_dump invocation with
  `PGPASSWORD`, failure + missing-binary → `BackupError`, retention prune,
  re-enqueue, start seed/skip-when-pending/skip-when-manual, health). API tests
  for `/metrics`, `/v1/metrics` (auth + disabled→404). CLI test for `atlas backup`.
  All hermetic — `subprocess.run` monkeypatched, no live Postgres needed.

### 23.5 Verified

- **214 pytest tests pass** (+20 over Sprint 8's 194). *(Stage 2 Sprint 10 later
  brought this to 275; see `docs/STAGE_2_PLAN.md`.)*
- Live: `atlas backup` → 102 KB custom-format dump in `/data/atlas_data/backups`;
  `pg_restore --list` confirms a valid archive (94 TOC entries, all schemas:
  agent/audit/knowledge/memory/public).

### 23.6 Out of scope / caveats (deferred)

- **Alerting / dashboards** (Grafana panels, alert rules) — the scrape endpoint is
  in place; wiring a Prometheus/Grafana stack is an operator task.
- **Off-host backup shipping** (S3/rsync) and point-in-time recovery (WAL archiving)
  — current backups are local logical dumps with retention; revisit if durability
  needs grow.
- **Container image publishing / CI** — Dockerfile + compose are provided but not
  pushed to a registry or built in CI yet.
- **Log shipping / centralized logs** — rotating file logs remain local.

---

## Backlog — Web UI

Not yet scheduled. The REST API already ships with API-key auth and CORS hooks
(§19) specifically so a local frontend can be added without backend changes. Slot
it as **Sprint 10 (after Operations)**, or pull it in right after Ops if a visual
chat surface for the assistant becomes a priority.

---

*This document is the starting point for Atlas. Every line of code we write should
trace back to a decision recorded here.*
