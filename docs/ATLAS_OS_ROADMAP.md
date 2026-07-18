# Atlas — OS Roadmap (post–Stage 3): Intelligence Domains, Missions & Durable State

> **Status:** 🟢 **FROZEN FOR IMPLEMENTATION (2026-07-18).** The top-level architecture and
> principles (P1–P9) are locked; remaining items are non-blocking, per-phase design details
> (see §12). Next step is to spin out `docs/PHASE_0_PLAN.md` and begin Phase 0. No code yet.
> **Created:** 2026-07-18 · **Review round 1:** 9/11 open questions resolved.
> **Review round 2:** added **Storage Manager** + **Asset Store**, enriched **Capability
> Registry**, reclassified the **Decision Engine as a Kernel Service**, added **Mission
> priorities** + **Mission Templates** + an **Operations Dashboard**, adopted the
> **Architecture Constitution** (§3 P7); **remote access deferred** (chosen approach when
> built: **Tailscale**); **hot/warm/cold tiering deferred** (single disk today); the name
> **Engineering Intelligence is final**.
> **Review round 3:** added **P9 — Everything is Explainable** (§3) and froze the plan.
> See §11 for the full decision log and §12 for remaining ambiguities.
>
> **Supersedes the framing of:** "Stage 4 / Stage 5". Those become **Phases** and
> **Missions** here (see §1). The Stage 3 / 3.2 / 3B plans remain the *history* of the
> research spine and knowledge/learning foundation (`docs/STAGE_3_PLAN.md`,
> `docs/STAGE_3_2_PLAN.md`, `docs/STAGE_3B_PLAN.md`).
>
> **Prerequisite reality:** Stage 3B shipped a working research pipeline, a governed
> Knowledge OS + Learning OS, per-source pipeline tracing, and advice-only experience
> learning. This roadmap builds the *operating-system* layer on top of that.

---

## 0. How to use this document

| Section | Role |
|---------|------|
| §1 | The reframe: **Stages → Intelligence Domains + Missions** (locked top-level architecture) |
| §2 | **Honest current state** — what already exists vs. what is absent (grounded in code) |
| §3 | **Locked principles (P1–P9)** — durability, model-independence, remote access (deferred), design-for-failure, few-intelligences, everything-versioned, the **Architecture Constitution** (P7), **storage discipline** (P8), and **everything-explainable** (P9) |
| §4 | Target architecture (frozen top level) + the four planes |
| §5 | **New subsystems** to build — each with *what exists today*, proposed shape, data model, and open questions |
| §6 | **Phase roadmap** (0 → A → B → C → D) with dependencies + acceptance criteria |
| §7 | **Model-migration playbook** (swap the LLM/embeddings without rebuilding knowledge) |
| §8 | Proposed data-model additions (new schemas/tables) |
| §9 | **Open questions for discussion** (decide these before building) |
| §10 | Non-goals |
| §11 | Decision log (append-only) |
| §12 | **Implementation readiness & remaining ambiguities** (plan frozen; non-blocking items to resolve per phase) |

Nothing here is implemented yet. Where the text says "**Exists**" it means the capability
is already in the codebase (path cited); "**New**" means it must be built; "**Extend**"
means a real component exists but must grow.

---

## 1. The reframe — stop thinking in "Stages", think in Intelligence Domains + Missions

The architecture is mature enough to be treated as an **operating system**, not a research
app. We adopt the operator's model:

```
                        Atlas Kernel
                             │
                    Core Services Layer
   (Scheduler, Resource Mgr, Jobs, Memory, LLM lane, Security/Auth,
    Monitoring, Clock, Decision Engine, Capability Registry)
                             │
   ┌───────────────── Storage Manager ─────────────────┐
   │  PostgreSQL · Workspace · Backups · Files · Cache  │
   │  · Models   (quotas, versioning, checksums,        │
   │              archive; tiering later)               │
   └────────────────────────────────────────────────────┘
        │                     │                    │
   Asset Store  →  Knowledge Extraction  →  Knowledge OS + Learning OS
   (raw files)                              (extracted understanding)
                             │
              ┌──────────── Mission Manager ────────────┐
              │  (long-lived objectives; priority,       │
              │   criticality, budget, deadline;         │
              │   templates + journal)                   │
              │                 │                        │
              │        Persistent Workers                │
              │                 │                        │
              │               Jobs                       │
              └──────────────────────────────────────────┘
                             │
      ┌──────────────┬───────────────┬───────────────┐
   Research       Engineering      Personal
 Intelligence     Intelligence    Intelligence
      └──────────────┴───────────────┴───────────────┘
              (three permanent producers of understanding)
```

**Rules that keep Atlas elegant instead of sprawling:**

1. **Intelligence Domains are few and permanent** — exactly three producers of
   understanding: **Research**, **Engineering**, **Personal**. We never add a "Trading
   Intelligence", "Medical Intelligence", etc.
2. **The Decision Engine is a Kernel Service, not an Intelligence** (R2). Every Mission
   eventually asks *"what should I do next?"* — that belongs to Atlas itself, not to
   Trading or Research. It consumes the three intelligences + the Mission's config.
3. **Everything a user "wants Atlas to do over time" is a Mission**, not a new
   intelligence. Paper trading, job hunting, patent monitoring, solar-plant optimization,
   Atlas self-improvement — all Missions. A Mission *composes* the three intelligences +
   the Decision Engine + configuration + workers.
4. **Assets ≠ Knowledge** (R2). Raw files (Git repos, DWG drawings, MATLAB projects, PDFs,
   images) live in the **Asset Store**; **Knowledge is extracted from them** into the
   Knowledge OS. This makes re-parsing (e.g. a new AutoCAD reader) a re-extraction, not a
   re-ingestion.
5. **All durable data flows through the Storage Manager** (R2) — one subsystem owns
   PostgreSQL, workspaces, backups, files, cache and models, plus quotas, versioning,
   checksums and archival. (Hot/warm/cold **tiering is deferred** until a second disk is
   added — single disk today.)

**Knowledge Domains, by contrast, are unlimited** — `research`, `engineering`, `personal`,
`finance`, `markets`, `electrical`, `control-systems`, `solar`, … They are just tags in
the Knowledge OS (knowledge-domain tagging already exists, migration `0013`). New field →
new knowledge domain, **never** a new subsystem.

> **The single most important structural addition: a Mission layer above Jobs.** Today
> Atlas thinks only in finite **Jobs**. Missions are long-lived objectives that own Jobs,
> Persistent Workers, Configuration, Knowledge scope, Experience, Progress and Success
> Criteria. This one addition ties together every future feature without a bespoke
> architecture per use case.

---

## 2. Honest current state (grounded)

### 2.1 Core services that already exist (reusable foundation)

| Capability | Status | Where (real code) |
|---|---|---|
| Microkernel + DI + capability registry | **Exists** | `atlas/kernel/` (`ServiceContainer`, `ServiceRegistry`, `CapabilityRegistry`, `ToolRegistry`, `EventDispatcher`, `LifecycleManager`), `bootstrap.py` |
| Resource Manager (worker pools, LLM lane, admission) | **Exists** | `atlas/core/resources/` (`ResourceManager`, profiles, monitor) |
| Execution planner (ordered, admission-gated) | **Exists** | `atlas/core/execution/` |
| Durable task **queue** (retries, backoff, crash recovery) | **Exists** | `atlas/scheduler/` (`SchedulerService`, `scheduler.tasks/task_runs`) |
| Jobs (multi-step, DAG-lite, HITL block/resume, crash re-scan) | **Exists** | `atlas/jobs/`, `job.jobs/job.steps` (migration `0010`) |
| Knowledge OS (documents/chunks/embeddings/**findings** + lifecycle + provenance + domains) | **Exists** | `atlas/knowledge/`, migrations `0006/0013/0014/0015/0016` |
| Learning OS (governed propose→apply→revert ledger, experiences, component observations, **source advice**) | **Exists** | `atlas/services/learning_service.py`, `atlas/learning/`, migrations `0011/0017` |
| Engineering Intelligence L2–L5 over a Code store | **Exists (narrow)** | `atlas/intelligence/service.py`, migration `0012` |
| Research Intelligence (search→acquire→read→extract→verify→findings→reasoning) | **Exists** | `atlas/research/` |
| Memory (working/episodic/semantic) | **Exists** | `atlas/services/memory_service.py`, `memory.items` |
| LLM access with a single global CPU inference lane | **Exists** | `atlas/llm/`, RM `llm_lane()` |
| Headless server + web console + API-key auth (localhost) | **Exists** | `atlas/api/`, `atlas/web/`, `atlas/api/auth.py` |
| Full-DB backup (daily `pg_dump -Fc`) | **Exists** | `atlas/ops/backup.py` |
| Config (Pydantic, YAML + env, validated) | **Exists** | `atlas/config/manager.py` |

### 2.2 What is absent (must be built for this vision)

| Needed | Status | Note |
|---|---|---|
| **Mission layer** above Jobs | **Absent** | Only finite Jobs exist today. |
| **Persistent Worker** framework (forever-running, checkpointed) | **Absent** | Emulated today by self-re-enqueuing scheduler tasks; no first-class worker lifecycle/checkpoints. |
| **Recurring/interval/cron scheduling** with a schedule table | **Absent** | Scheduler is a queue; recurrence is hand-rolled `delay_seconds` self-re-enqueue. |
| **Recovery Manager** (unified startup recovery) + **Mission Journal** | **Absent** | Recovery is decentralized per-subsystem `start()`; no journal. |
| **Configuration Manager** (per-mission, versioned, DB-persisted, validated, editable) | **Absent** | Global config is in-memory YAML/env; no versioning, no per-mission config. |
| **Decision Engine** (Kernel Service; consumes the 3 intelligences → next action) | **Absent** | R2: a kernel service, not an intelligence. |
| **Storage Manager** (one subsystem for DB/workspace/backups/files/cache/models; quotas, versioning, checksums, archive — **tiering deferred: single disk today**) | **Absent** | Storage is scattered: DB pool, on-disk workspaces (`atlas/jobs/workspace.py`), `pg_dump` backup — no unifying manager, quotas, or tiering. |
| **Asset Store** (raw ingested files, separate from extracted knowledge) | **Absent** | Knowledge OS conflates source files and extracted knowledge; no asset/versioned-file store. |
| **Capability Registry enrichment** (per-capability version/enabled/healthy/metrics/dependencies) | **Partial** | A `CapabilityRegistry` exists (contract lookup + `verify()`), but it does not expose per-capability version/health/metrics/deps for self-inspection. |
| **Mission priority/criticality/budget/deadline** (resource arbitration across missions) | **Absent** | No mission layer yet; RM allocates per-task, not per-mission. |
| **Mission Templates** (instantiate → customize → run) | **Absent** | — |
| **Operations Dashboard** (mobile-first single-screen ops view) | **Absent** | Web console has Chat/Jobs/System only; no ops dashboard. |
| **Durable event bus + notification channels** (email/Telegram/web push/SSE) | **Absent** | Event bus is in-process, synchronous, non-durable; `audit.events` table unused by it; web is poll-based. |
| **Clock/Time service** (NTP, UTC-internal, drift monitor, monotonic timers) | **Absent** | Timestamps created ad hoc (`datetime.now(timezone.utc)` + SQL `now()`), two unreconciled clocks. |
| **Personal Intelligence** (profile/career/resume/portfolio/publications/patents) | **Absent (greenfield)** | "personal" today is only a governance policy label. |
| **Real component/model/embedding version stamping** on artifacts | **Partial/weak** | Provenance exists but versions are hardcoded `"v1"`/`"@1"` string literals, not the real model/reader build. |
| **Model-switch orchestration** (background re-embed, dim change → migration) | **Absent** | Embedding dim `768` hardcoded in DDL; no automated re-embed job. |
| **Checkpoint/resume *within* a job step** | **Absent** | Steps are atomic; interrupted step restarts from scratch. |
| **Remote access hardening** (VPN), dashboards | **Deferred (R2)** | Headless + web console + auth exist; remote access is **out of scope for this implementation** — done later via **Tailscale** (never public). Dashboards are in scope (localhost-first). |

---

## 3. Locked principles (P1–P9)

These are proposed as **non-negotiable architectural rules**. P1–P3 answer the operator's
three questions (durability, model-independence, remote access); P4–P9 lock in
design-for-failure, the intelligence/mission split, versioning, the Architecture
Constitution, storage discipline, and explainability. Confirmed in §11.

### P1 — State durability: every long-lived object is durable

The database (+ workspaces) *is* the system. Only transient runtime objects may be lost.

| Durable (survives reboot / migration) | Transient (may be lost/rebuilt) |
|---|---|
| Knowledge, Findings, Experience, Learning ledger | LLM context window |
| Engineering graph, Personal profile | In-memory caches |
| **Missions, Workers, Schedules, Configurations** | Temporary/partial downloads |
| Checkpoints, Job queue, Benchmarks, Provenance | Active network connections |

Design consequence: moving to a new machine = **move DB + config + workspaces, point at a
model, regenerate model-specific artifacts in background, resume**. A *recovery* exercise,
never a *rebuild* exercise.

### P2 — Model independence: the LLM is a reasoning engine, not the knowledge

> **LLM → reasons → produces Knowledge → Knowledge Database.** The database is the
> knowledge. Swapping Qwen3 → Llama/DeepSeek/GPT-8 must change *nothing* in Findings,
> Experiences, Reports, Graphs, Provenance, Memory.

Only two things may need regeneration on a model swap, both **background, non-destructive**:

1. **Embeddings** — if the *embedding* model changes, re-embed chunks/memory in the
   background under the new model name (rows are namespaced by `(chunk_id, model)`; old
   vectors are simply not matched). If the new model's dimension ≠ 768, a schema migration
   adds a new `vector(N)` space (see §7). Documents/findings do **not** change.
2. **Cached LLM responses** — discardable; not knowledge.

To make this real we must **version artifacts by the components that produced them**
(today these are hardcoded `"v1"`): stamp each Finding/Experience with
`llm_id`, `embedding_id`, `reader_version`, `extractor_version`, `verifier_version`,
`knowledge_schema_version`. Then years later Atlas can say *"this finding was produced with
Reader 2.4, Extractor 5.1, Qwen3, embedding-model-X"* — and re-derivation is scoped and
auditable.

### P3 — Remote access: headless server + web console, never exposed directly

Atlas is already a headless server + API-key-gated web console bound to `127.0.0.1`.

- **Never** bind Atlas to a public interface, ever. Keep `127.0.0.1` + API keys.
- **Remote access is deferred out of this implementation (R2).** We build the dashboards
  now (localhost-first, mobile-friendly), and add remote reach **later**.
- **When we do add it, the chosen approach is Tailscale** (R2): a mesh VPN with almost-zero
  config, no port forwarding, no public endpoint, device authentication, works behind CGNAT,
  strong mobile support. Target shape:

```
Ubuntu Server → Atlas (localhost only) → Nginx (localhost) → Tailscale → Phone
                                          → https://atlas.<tailnet>  (MagicDNS)
```

  WireGuard is the fallback (more admin, full control); Cloudflare Tunnel is explicitly
  **not** chosen — Atlas is an operating system, not a public website, so we connect to the
  *machine* over a private network rather than exposing Atlas through a public tunnel.
- Dashboards must let the operator **view any Mission's results/outcomes on demand** (R1/Q2)
  and default to a single mobile-first **Operations Dashboard** (see §5.11).

### P4 — Design for failure (power / internet / disk / kill)

Assume unclean shutdown *always*. Every worker is a **checkpoint → work → checkpoint** loop;
on boot the Recovery Manager resumes exactly where it stopped. Downloads are
resumable + checksummed. Internet loss = pause → retry → continue, never fail. (Detailed in
§5.4 Recovery Manager & §5.2 Worker framework.)

### P5 — Few intelligences, unlimited knowledge domains, everything else is a Mission

Restated for emphasis (see §1). This is the rule that prevents 20–30 duplicated
"intelligences".

### P6 — Everything configurable and versioned

Every Mission is configured, not hardcoded. Configurations are **versioned**, and every
recommendation/decision references the configuration + knowledge + experience versions that
produced it → full reproducibility and explainability (see §5.3 & §5.5).

### P7 — Architecture Constitution: the four-questions test (R2)

Once this roadmap is frozen, treat it as Atlas's **architecture constitution**. Do not let
future features bypass it. Before **any** new capability is added, it must answer *yes* to
exactly one of:

1. Is it a **Knowledge Domain**? → a tag in the Knowledge OS (unlimited, free).
2. Is it a **Mission**? → an operator-created objective composing existing pieces.
3. Is it a **Persistent Worker**? → a checkpointed, scheduled worker owned by a Mission.
4. Is it a **Kernel Service**? → a small, shared, permanent service in the Core layer.

If it fits none of these, that is a **design smell** — revisit the design rather than adding
another top-level subsystem. This discipline is what keeps Atlas coherent after years of
growth (it is why "trading" is a Mission + Knowledge Domain, never a new intelligence).

### P8 — Storage discipline: one Storage Manager, and Assets ≠ Knowledge (R2)

All durable data flows through a single **Storage Manager** (§5.8): PostgreSQL, workspaces,
backups, files, cache, models — plus quotas, file versioning, checksums and archival.
(Hot/warm/cold **tiering is deferred** until a second disk is added — single disk today.)
And **raw files are Assets, not Knowledge**: they live in the **Asset
Store** (§5.9) and Knowledge is *extracted* from them. This separation makes re-parsing
(e.g. a better CAD/code reader) a background re-extraction, never a re-download.

### P9 — Everything is explainable (R3)

Every action Atlas performs must be answerable, after the fact, with a complete
**explanation record**. This is the operator-facing complement to P6 (versioning) and the
Decision Engine (§5.5): versioning makes results *reproducible*; P9 makes them
*interrogable*. For any recommendation, decision, finding, or worker action, Atlas can
answer:

| Question | Backed by |
|---|---|
| **Why?** | the decision rule / objective that triggered it |
| **Evidence?** | source refs (findings, claims, provenance) |
| **Knowledge used?** | Knowledge OS rows + domain(s) + KB version |
| **Experience used?** | Learning-OS experience set(s) + component observations |
| **Configuration used?** | Mission config **version** (§5.3) |
| **Decision rule?** | the deterministic rule/scoring path (§5.5) |
| **Model version?** | `llm_id` / `embedding_id` + component versions (P2 stamps) |
| **Confidence?** | verifier confidence + convergence |
| **Alternatives rejected?** | the options considered and why they lost |

Design consequence: every `decision.decisions` row (and every Mission Journal entry) carries
these fields; the Decision Engine returns them as a first-class part of its output, and the
Operations Dashboard / Mission views can render an **"Explain this"** panel for any action.
This is invaluable later for Engineering, Paper Trading, Job/Career recommendations,
Research, and any future autonomous behavior — nothing is a black box.

---

## 4. Target architecture (frozen top level)

```
Atlas Kernel
│
├── Core Services  (Scheduler, Resource Manager, LLM lane, Security/Auth, Monitoring, Clock,
│                   Decision Engine ← NEW, Capability Registry ← EXTEND)
├── Storage Manager        ← NEW  (DB · workspace · backups · files · cache · models;
│                                  quotas, versioning, checksums, archive; tiering later)
├── Asset Store            ← NEW  (raw files: repos, DWG, MATLAB, PDF, images)
│        └── Knowledge Extraction → Knowledge OS
├── Knowledge OS   (extracted: documents, chunks, embeddings, findings, provenance, domains)
├── Learning OS    (governed ledger, experiences, component observations, advice)
├── Mission Manager        ← NEW  (+ priority/criticality/budget/deadline; templates; journal)
├── Worker Manager         ← NEW
├── Configuration Manager  ← NEW
├── Recovery Manager       ← NEW  (+ storage integrity checks)
└── Notification/Event Bus ← NEW  (upgrade existing dispatcher)

Intelligence plane (producers, permanent — exactly three):
    Research Intelligence · Engineering Intelligence · Personal Intelligence

Above that:
    Missions → Persistent Workers → Jobs → Knowledge & Experience
```

**Why the Decision Engine is a *Kernel Service*, not an intelligence (R2):** Research
discovers facts, Engineering understands systems, Personal understands *you*. The Decision
Engine *consumes* all three plus the active Mission's configuration to choose the next
action — and **every** Mission needs it, so it belongs to Atlas itself, not to Trading or
Research. One engine later powers job hunting, patent prioritization, digital-twin
optimization — no per-domain intelligence needed.

---

## 5. New subsystems (design sketches for discussion)

Each subsystem below is a proposal. Data-model details are collected in §8.

### 5.1 Mission Manager (+ priorities, templates, Mission Journal)

- **Purpose:** own long-lived objectives. A Mission has: configuration, knowledge scope
  (which domains), owned Jobs, owned Persistent Workers, progress, success criteria,
  lifecycle (`draft → active → paused → completed → archived`), and a **Mission Journal**
  (append-only record of every important action: timestamp, action, reason, outcome).
- **What exists:** Jobs (`atlas/jobs/`) and the durable scheduler give us the execution
  substrate. Nothing above Jobs exists.
- **Proposed shape:** `atlas/missions/` — `MissionService` (registered service),
  `MissionRepository`, models `Mission`, `MissionObjective`, `MissionJournalEntry`. Missions
  reference config versions (§5.3) and spawn Jobs/Workers.
- **Mission priorities (R2):** because Paper Trading, Job Search, Atlas Development,
  Research and Engineering Analysis may run **simultaneously**, the Mission Manager carries
  arbitration fields — **`priority`, `criticality`, `budget`, `deadline`, `importance`** —
  that the Resource Manager consults to allocate CPU / RAM / LLM lane / disk / network across
  competing missions. (The RM already does per-task admission; this raises arbitration to the
  per-mission level.)
- **Mission Templates (R2):** Atlas ships with reusable templates — **Research Mission,
  Paper Trading, Job Hunting, Patent Watch, Repository Learning, Technology Watch, Security
  Monitoring**. Flow is *instantiate template → customize configuration → run* (conceptually
  like Docker Compose): a template declares the workers, default config schema, knowledge
  domains and success criteria; instantiation produces a concrete Mission + config v1.
- **Mission Journal** doubles as the forensic log for Recovery ("reconstruct exactly what
  happened") and for explainability ("why did Atlas do X").
- **Decided (R1):** Missions are **always operator-created** — the user decides which
  Missions/Jobs to run and keep alive in the background; Atlas does **not** auto-create
  Missions (it may *suggest* later, still operator-approved). A Mission **may create and own
  Jobs** as needed, and the operator can **view a Mission's study results and outcomes on
  demand at any time** (dashboard + on-demand report; see §5.6 / P3).
- **Open questions:** resolved (Q1, Q2).

### 5.2 Persistent Worker framework

- **Purpose:** first-class **forever-running** workers (Job Watcher, Research Watcher,
  Paper-Trading Worker, Technology/Security Watcher, Self-Improvement Watcher). Each: a
  lifecycle (`start/pause/resume/stop`), a schedule (interval/cron/continuous), periodic
  **checkpoints** (current item/page/claim/progress/state), cancellation, and resource
  leases from the RM.
- **What exists:** the pattern is *emulated* today (`advance_job` re-enqueues itself;
  `BackupManager`/`FilesystemSource` self-re-enqueue with `delay_seconds`). No worker
  lifecycle, checkpoint store, or supervision.
- **Proposed shape:** `atlas/workers/` — `WorkerManager` (supervises workers, restarts on
  crash, enforces RM admission), a `PersistentWorker` base (checkpoint hooks), a durable
  `worker.workers` + `worker.checkpoints` table. Workers are owned by Missions and honor
  the Mission's Configuration. Workers accept **live operator input/constraints** (reusing
  the durable `inputs.jsonl` HITL pattern already in `atlas/jobs/workspace.py`, promoted to
  a table).
- **Design-for-failure:** checkpoint → work → checkpoint; on boot, Recovery Manager resumes
  from the last checkpoint. Downloads resumable + checksummed (extend `atlas/research/acquire.py`).
- **Open questions:** §9 Q3, Q4.

### 5.3 Configuration Manager (versioned, per-mission)

- **Purpose:** every Mission/Worker is configured, validated, and **versioned**. Example
  (Paper Trading): markets, virtual capital, max risk %, max trades/day, trading hours,
  strategies, news weight, learning on/off, notification channels, review frequency. Editing
  produces a **new version** (`v7 → v8`, with change + date). Workers never hardcode
  assumptions — they read the active config version.
- **What exists:** global app config only (`atlas/config/manager.py`, Pydantic, in-memory,
  **not** versioned, **not** per-mission, **not** DB-persisted).
- **Proposed shape:** `atlas/configuration/` — `ConfigurationService`, `ConfigRepository`,
  a `config.mission_configs` table storing versioned JSON documents + a Pydantic schema per
  mission type for validation. Every recommendation/decision stamps the config version used.
- **Reproducibility:** *"Why did Atlas recommend BUY ABC? → Trading Config v7 (risk 2%,
  momentum+news+RSI+MACD) + Research KB v12 + Experience set #245 (78% success)."*
- **Open questions:** §9 Q5.

### 5.4 Recovery Manager (+ startup integrity)

- **Purpose:** one component that runs **before Atlas accepts new work**: startup recovery,
  checkpoint recovery, job recovery, mission recovery, DB integrity check, workspace
  recovery, queue recovery, backup verification.
- **What exists:** decentralized recovery (scheduler resets `claimed/running`→`pending`;
  jobs reset `running`→`pending` and re-scan unfinished). No unifying coordinator, no
  integrity check, no backup verification.
- **Proposed shape:** `atlas/recovery/` — `RecoveryManager` invoked in `bootstrap.py`
  after DB connect, before `LifecycleManager.start_all()` completes accepting work. It
  orchestrates the existing per-subsystem recovery + new mission/worker/checkpoint recovery
  and writes a recovery report to the Mission Journal.
- **Decided (R1):** startup latency for recovery is acceptable, **but recovery must itself
  be crash-safe**: if a boot is interrupted (power/internet loss mid-recovery), the next
  boot must re-run recovery cleanly. Recovery is therefore **idempotent and re-entrant** —
  it records its own progress (a recovery journal entry with `started/completed`), and on
  the next boot re-runs from the beginning (or last safe point) until it completes without
  error before Atlas accepts new work. No half-recovered state is ever treated as "done".
- **Open questions:** resolved (Q6).

### 5.5 Decision Engine (Kernel Service — R2)

- **Classification (R2):** a **Kernel/Core Service**, *not* an intelligence. Every Mission
  asks "what should I do next?", so the engine belongs to Atlas itself and is shared by all
  Missions.
- **Purpose:** the consumer. Given a Mission + its config, combine **Research**
  (facts/literature/news), **Engineering** (models/simulations/software), and **Personal**
  (preferences/constraints/risk/goals) to choose the **next action**. Powers trading, job
  hunting, patent prioritization, digital-twin optimization, project planning — one engine,
  many missions.
- **What exists:** nothing unified. Research/verification produce findings; the job planner
  decomposes objectives; but there's no cross-intelligence decision layer.
- **Proposed shape:** `atlas/decision/` — `DecisionEngine` that takes a typed
  `DecisionRequest(mission, config_version, context)` and returns a `Decision` carrying the
  full **P9 explanation record**: `action, why (rule), evidence_refs, knowledge_refs,
  experience_refs, config_ref, decision_rule, model_versions, confidence,
  alternatives_rejected`. Every decision is journaled and explainable. It **recommends**;
  behavior changes stay human-gated (consistent with the Learning OS stance).
- **Explainability (P9):** the `Decision` record is the canonical "Explain this" payload
  surfaced by the dashboard/Mission views; nothing the engine outputs is a black box.
- **Open questions:** §9 Q7 (how much reasoning is deterministic vs LLM).

### 5.6 Notification / Event bus upgrade (durable + channels + live UI)

- **Purpose:** durable events + real notification channels (email, Telegram, web push) +
  live web console (SSE) so you're notified when a Mission finds something.
- **What exists:** `EventDispatcher` (in-process, synchronous, non-durable);
  `audit.events` table exists but is **unused** by the bus; web console **polls**
  `activity.jsonl`.
- **Proposed shape:** persist events to `audit.events` (durable, replayable), add a
  `Notifier` with pluggable channels, and an SSE endpoint in `atlas/api/` so dashboards
  update live instead of polling.
- **Decided (R1):** **web (SSE) + email first**; Telegram/other channels later. Channel
  **secrets (SMTP creds) live in env only** — never DB/YAML (consistent with existing
  `ATLAS_*` secret handling). The exact rollout *order* between web and email is still open
  (Q8 partial).
- **Open questions:** channel ordering within web+email (minor, Q8).

### 5.7 Clock / Time service (Priority 0)

- **Purpose:** one trustworthy time source. UTC internally, local tz for display, NTP sync
  status, drift monitoring, monotonic timers for durations, timestamp validation. Every
  experience/finding/benchmark/schedule/journal entry depends on good time.
- **What exists:** ad-hoc `datetime.now(timezone.utc)` + SQL `now()` (two unreconciled
  clocks); `time.monotonic()` used only for elapsed durations.
- **Proposed shape:** `atlas/system/time.py` — `ClockService` (`now_utc()`,
  `monotonic()`, `to_local()`, `ntp_status()`, `drift_seconds()`), injected where
  timestamps are minted; a lightweight NTP/drift monitor surfaced in health. Low-risk,
  one-time investment; do it first so all later durable objects are correctly stamped.
- **Open questions:** §9 Q9 (strict NTP dependency vs best-effort monitor).

### 5.8 Storage Manager (Priority 0 — R2)

- **Purpose:** one first-class subsystem through which **all durable data flows** —
  PostgreSQL, workspaces, backups, files, cache, models. Responsibilities **now**: workspace
  lifecycle, **file versioning**, **backup scheduling**, **storage quotas**, **checksum
  validation**, **archive management**. Becomes critical once Engineering Intelligence
  ingests repositories and CAD projects.
- **Deferred — hot/warm/cold tiering (hardware-gated):** the machine currently has **a single
  disk**, so **hot/warm/cold data movement is deferred until extra storage is added**.
  Everything lives on the one volume for now; tiering (moving warm/cold data to a second
  disk) is a **later, additive** capability — the API and data model are designed so it can
  be switched on without reworking anything (see below). We do **not** build tier-movement
  logic yet.
- **What exists:** storage is scattered — the DB connection pool, on-disk job workspaces
  (`atlas/jobs/workspace.py`), and a daily `pg_dump -Fc` (`atlas/ops/backup.py`). No
  unifying manager, no quotas, no tiering, no per-file versioning or checksums.
- **Proposed shape:** `atlas/storage/` — `StorageManager` (registered service) exposing a
  small API for workspace allocation, versioned file put/get, checksum verify,
  quota checks, and backup orchestration; a `storage.files` / `storage.quotas` table. A
  `tier` column exists from day one (default `hot`), but **tier-move operations are a no-op /
  unimplemented until a second disk is present**. Other subsystems stop touching disk
  directly and go through it.
- **Recovery tie-in:** the Recovery Manager (§5.4) runs **storage integrity checks**
  (checksums, orphaned/partial files, quota state) at boot.
- **Open questions:** §9 Q12 (which subsystems migrate to it first; quota policy).

### 5.9 Asset Store (Assets ≠ Knowledge — R2)

- **Purpose:** hold the **raw ingested files** (Git repos, DWG drawings, MATLAB projects,
  PDFs, images) as **versioned, checksummed assets** — distinct from the *extracted*
  knowledge. Pipeline: **Asset Store → Knowledge Extraction → Knowledge OS**. Re-parsing an
  asset with a better reader (e.g. a new AutoCAD reader) becomes a background re-extraction,
  not a re-download.
- **What exists:** the Knowledge OS conflates source documents with extracted knowledge;
  there is no versioned asset layer.
- **Proposed shape:** `atlas/assets/` — `AssetStore` (backed by the Storage Manager) with an
  `asset.assets` table (id, type, source_uri, checksum, version, tier, mission/domain refs)
  and `asset.versions`. Knowledge/provenance rows reference the **asset id + version** they
  were extracted from, so a re-extraction is fully auditable.
- **Open questions:** §9 Q13 (retention/tiering of large binary assets).

### 5.10 Capability Registry (enrichment — R2)

- **Purpose:** let Atlas **inspect itself**. For every capability (e.g. Python Reader,
  Extractor, Verifier, each Intelligence, each Reader) expose **version, enabled, healthy,
  metrics, dependencies** — the basis for health dashboards, self-diagnosis, and
  artifact-version stamping (P2).
- **What exists:** `CapabilityRegistry` in `atlas/kernel/` does contract lookup + `verify()`,
  but does **not** carry per-capability version/health/metrics/dependency records.
- **Proposed shape:** extend the existing registry with a `CapabilityInfo`
  (`name, version, enabled, healthy, metrics, dependencies`) surfaced via `/health` and the
  Operations Dashboard, and used as the source of the real component versions that stamp
  Findings/Experiences (replacing hardcoded `"v1"`).
- **Open questions:** §9 Q14 (push vs pull for health/metrics).

### 5.11 Operations Dashboard (mobile-first — R2)

- **Purpose:** the **first screen** the operator sees (later from a phone). A single
  **Operations** view — not a generic "Atlas dashboard" — that answers *"is Atlas healthy
  right now?"* at a glance:

```
Atlas: ✔ Running        Knowledge: 2.3M findings     Workers: 12 running
Missions: 5 active      Jobs: 18 queued              CPU 41% · RAM 38% · Disk 71%
Temperature: 52°C       UPS: not present             Internet: disconnected
Last backup: 02:00      Last checkpoint: 11s ago
```

- **What exists:** the web console has Chat / Jobs / System panes and polls `activity.jsonl`;
  there is no consolidated ops view, and host metrics (temp/UPS/internet/disk) aren't
  surfaced.
- **Proposed shape:** a dashboard route in `atlas/web/` fed by the Capability Registry
  (§5.10) + Monitoring + Storage Manager, live over **SSE** (§5.6). **Localhost-first now**;
  it becomes the phone home screen once remote access (Tailscale, deferred) is added.
- **Open questions:** §9 Q15 (which host metrics are in scope for v1 — e.g. temp/UPS sensors).

---

## 6. Phase roadmap

Renamed from "Stages" to a product roadmap. Each phase lists its **new** subsystems,
**dependencies**, and **acceptance criteria**. Phases 0 and A are foundational and gate the
rest.

### Phase 0 — Infrastructure & Durability (≈1–2 weeks)  ·  *do first*
- **Clock/Time service** (§5.7) — UTC-internal, NTP status, drift monitor, monotonic timers.
- **Storage Manager** (§5.8) — unify DB/workspace/backups/files/cache/models behind one
  service; checksums + backup scheduling + quotas. **Hot/warm/cold tiering is deferred**
  (single disk today) — the `tier` column ships but tier-move logic is added later when a
  second disk is bought.
- **Asset Store** (§5.9) — thin versioned/checksummed asset layer + the Assets≠Knowledge
  split (fully exercised in Phase B).
- **Capability Registry enrichment** (§5.10) — per-capability version/enabled/healthy/
  metrics/dependencies (also feeds artifact versioning below).
- **Durable event bus + Notifier + SSE** (§5.6).
- **Operations Dashboard** (§5.11) — mobile-first single-screen ops view, localhost, live
  over SSE.
- **Recovery Manager** (§5.4) — unify + extend existing recovery; **storage integrity
  checks** + backup verification.
- **Artifact versioning** (§3 P2) — real `llm_id`/`embedding_id`/`reader_version`/
  `extractor_version`/`verifier_version`/`knowledge_schema_version` on findings/experiences
  (sourced from the Capability Registry).
- **Resumable + checksummed downloads** and **intra-step checkpoint hooks** (foundation for §5.2).
- *Remote access is **out of scope** here (deferred, R2); dashboards are localhost-only for now.*
- **Acceptance:** kill -9 mid-research → reboot → Recovery Manager resumes the job from its
  last checkpoint (not from scratch); events survive restart; drift + capability health are
  visible in `/health` and on the Operations Dashboard.
  **Also:** kill -9 *during* recovery → next reboot re-runs recovery cleanly to completion
  before accepting new work (idempotent, re-entrant recovery — R1/Q6).

### Phase A — Mission & Worker Foundation (≈1–2 weeks)
- **Mission Manager + Mission Journal** (§5.1), including **priority/criticality/budget/
  deadline/importance** arbitration fields consumed by the Resource Manager.
- **Mission Templates** (§5.1) — ship the initial set (Research, Paper Trading, Job Hunting,
  Patent Watch, Repository Learning, Technology Watch, Security Monitoring) as instantiable
  templates.
- **Persistent Worker framework + Worker Manager** (§5.2).
- **Recurring/interval scheduling** (schedule table; promote self-re-enqueue to first-class).
- **Configuration Manager** (§5.3) — versioned per-mission config.
- **Acceptance:** instantiate a Mission **from a template** with a versioned config that owns
  a trivial Persistent Worker (e.g. a heartbeat/"hello watcher"); it checkpoints, survives
  reboot, is pausable/resumable, editable config bumps a version, priority influences
  scheduling under contention, and every action is journaled.

### Phase B — Engineering Intelligence expansion (≈4–8 weeks)
> Name is **final: "Engineering Intelligence"** (R2 — the "Engineering Knowledge System"
> rename was considered and declined).
- **Extend** the existing L2–L5 Code store intelligence (`atlas/intelligence/`) toward:
  repository ingestion → code understanding → **architecture graph** → design reasoning →
  engineering findings → engineering memory. Multi-language (Python first; then SQL,
  JS/TS, …). Later document types (docs, UML, SQL, Docker, CAD, MATLAB, PLC, LabVIEW,
  PSpice, mechanical drawings, networking, …) are just new **Readers** feeding the same
  pipeline — *not* new intelligences.
- **Assets flow through the Asset Store** (§5.9): repos/CAD/etc. are stored as versioned
  assets; Engineering knowledge is *extracted* from them, so a better reader later re-parses
  the stored asset rather than re-cloning/re-downloading.
- **Acceptance:** ingest a real repo → architecture graph + design findings retrievable and
  versioned; a second language supported through the same pipeline.

### Phase C — Personal & Professional Intelligence (≈2–4 weeks)
- **New** `atlas/personal/`: a **model of you**, not a memory dump. Personal profile +
  Professional profile (career planner, publication manager, patent manager, resume/
  LinkedIn/portfolio managers). Fed *indirectly* (Research + Engineering + Experience +
  operator interaction), never by scraping everything.
- **Acceptance:** a durable, editable personal/professional profile that Missions can read
  (e.g. job-search constraints), with provenance for how each fact was learned.

### Phase D — Persistent Workers / Missions (ongoing)
Each is a **Mission** composing the three intelligences + Decision Engine + config + workers:
- **Job Watcher** (LinkedIn/Naukri/company sites → ranked matches → notify).
- **Research Watcher** (IEEE/arXiv/Scholar → summarize → Knowledge Base).
- **Paper-Trading Worker** (market data → indicators → strategy → **simulation only, no real
  money** → virtual portfolio → learning). Operator-configurable + operator inputs/constraints.
- **Technology / Security Watcher** (breaking changes, CVEs).
- **Atlas Self-Improvement Watcher** (benchmarks, regressions, performance).
- **Decision Engine** (§5.5) lands here as the shared brain for all of the above.
- **Acceptance:** at least one end-to-end Mission (proposed: Paper Trading, simulation-only)
  running for days across reboots, configurable live, notifying, and journaling explainable
  decisions.

---

## 7. Model-migration playbook (P2 in practice)

When switching the reasoning LLM (e.g. Qwen3 → Llama/DeepSeek/GPT-8):

1. **Point config at the new model.** Findings/Experiences/Reports/Graphs/Memory are
   unchanged (they are data, not model state).
2. **If the embedding model is unchanged:** nothing to rebuild.
3. **If the embedding model changed (same dimension):** run a **background re-embed** job —
   re-embed chunks + `memory.items` under the new model name; reset
   `knowledge.documents.status` from `embedded` to trigger re-embedding; old vectors remain
   (never matched). *(This orchestration job is currently absent — build in Phase 0.)*
4. **If the embedding dimension changed (≠768):** add a schema migration for a new
   `vector(N)` embedding space; re-embed into it; retire the old space when done. (Dim 768
   is currently hardcoded in DDL — migration `0006`.)
5. **Discard caches.** Cached LLM responses are transient.
6. **Verify** via benchmarks (`atlas/eval/`) that retrieval/quality hold under the new model.

**Machine migration** is the same story: move DB + `config/` + workspaces → point at a model
→ background-regenerate embeddings if needed → Recovery Manager resumes Missions/Workers/Jobs.

---

## 8. Proposed data-model additions (high level, for discussion)

New Postgres schemas/tables (names provisional). All `TIMESTAMPTZ` via the Clock service;
all long-lived (P1).

- `mission.missions` — id, title, objective, status, success_criteria, knowledge_domains[],
  active_config_id, **priority, criticality, budget, deadline, importance** (R2 arbitration),
  template_id, created/updated.
- `mission.templates` — id, name, worker_specs JSONB, default_config_schema, knowledge_domains[],
  success_criteria (R2; instantiate → customize → run).
- `mission.journal` — id, mission_id, ts, action, reason, outcome, refs (append-only).
- `asset.assets` — id, type, source_uri, checksum, version, tier (hot/warm/cold),
  mission_id/domain refs, created/updated (R2; raw files, separate from knowledge).
- `asset.versions` — id, asset_id, version, checksum, ts (versioned re-ingest).
- `storage.files` / `storage.quotas` — versioned/checksummed file registry + per-scope quota
  and tiering state, owned by the Storage Manager (R2).
- `system.capabilities` — name, version, enabled, healthy, metrics JSONB, dependencies[]
  (R2; Capability Registry self-inspection; also source of artifact version stamps).
- `worker.workers` — id, mission_id, type, status, schedule (interval/cron/continuous),
  last_checkpoint_id, created/updated.
- `worker.checkpoints` — id, worker_id, ts, state JSONB, progress.
- `worker.inputs` — durable operator inputs/constraints queue (promote `inputs.jsonl`).
- `config.mission_configs` — id, mission_id, version, schema_type, document JSONB,
  change_note, created_at (versioned; never mutated in place).
- `decision.decisions` — id, mission_id, config_id, action, **why** (rule/objective),
  evidence_refs, **knowledge_refs**, **experience_refs**, **decision_rule**,
  **model_versions**, confidence, **alternatives_rejected** JSONB, ts (the full **P9**
  explanation record; explainable + journaled).
- **Versioning columns** added to `knowledge.findings` / `learning.experiences`:
  `llm_id`, `embedding_id`, `reader_version`, `extractor_version`, `verifier_version`,
  `knowledge_schema_version` (replace hardcoded `"v1"`).
- Event durability: start persisting to existing `audit.events`.
- Personal (Phase C): `personal.profile`, `personal.professional`, `personal.goals`,
  `personal.publications`, `personal.patents` (shapes TBD in Phase C plan).

---

## 9. Open questions for discussion (decide before building)

> Status legend: ✅ decided · ⏳ open (deferred, revisit before the dependent phase).

1. **Mission granularity.** Is a Mission always operator-created, or can the Decision Engine
   propose new Missions (subject to approval)? Recommendation: operator-created first;
   Atlas may *suggest* Missions later.
   - ✅ **Decided:** Missions are **always operator/user-created**. The user decides which
     Missions and Jobs are taken up and kept running in the backend. (Atlas-suggested
     Missions are out of scope for now.)
2. **Mission ↔ Job ownership.** Do Missions own Jobs directly, or only via Workers?
   Recommendation: Missions own both Workers (continuous) and one-off Jobs (finite).
   - ✅ **Decided:** Agreed. Missions own both Workers (continuous) and one-off Jobs
     (finite); a Mission **may create and own a Job when needed**. Requirement: the user
     must be able to view a Mission's **study results and outcomes on demand, at any time**.
3. **Worker execution model.** Reuse the scheduler's self-re-enqueue "many short tasks"
   model (survives restart cleanly), or long-lived threads with checkpoints? Recommendation:
   short-task + checkpoint model (durability-first), supervised by Worker Manager.
   - ✅ **Decided:** Agreed — short-task + checkpoint model (durability-first), supervised
     by the Worker Manager.
4. **Live operator input to running workers.** Promote the existing durable `inputs.jsonl`
   HITL queue to a `worker.inputs` table — agreed? (This directly answers "I should be able
   to give inputs/constraints to paper trading while it runs.")
   - ✅ **Decided:** Agreed — promote the durable `inputs.jsonl` HITL queue to a
     `worker.inputs` table.
5. **Configuration storage.** DB-persisted versioned JSON validated by per-mission Pydantic
   schemas — agreed? Should global app config (`config/manager.py`) also move to DB, or stay
   file/env? Recommendation: keep global config file/env; Mission configs in DB.
   - ✅ **Decided:** Agreed — keep global app config in file/env; Mission configs are
     DB-persisted versioned JSON validated by per-mission Pydantic schemas.
6. **Recovery ordering.** Recovery Manager runs before accepting new work — acceptable
   startup latency? Any integrity checks that are too slow to run every boot (make optional)?
   - ✅ **Decided:** Startup latency is acceptable. Additional requirement: if startup itself
     **fails mid-way (power or internet outage)**, recovery must be **idempotent and safely
     re-runnable** so the next boot can retry from a clean state without corruption.
7. **Decision Engine reasoning.** How much is deterministic (rules/scoring) vs LLM? For
   trading especially, deterministic + explainable is safer. Recommendation: deterministic
   core, LLM for narrative/explanation only.
   - ✅ **Decided:** Agreed — deterministic core (rules/scoring); LLM used for
     narrative/explanation only.
8. **Notification channels + secrets.** Which first — web/SSE + email, or Telegram? Where do
   SMTP/Telegram secrets live (env only, never DB/YAML)?
   - ✅ **Channels decided:** **Web + email** first (Telegram deferred).
   - ⏳ **Open:** exact secrets handling still to finalize; default stance is **env-only,
     never DB/YAML**.
9. **Time/NTP.** Hard dependency on NTP sync, or best-effort drift monitor that only warns?
   Recommendation: best-effort monitor + health warning (don't block on network time).
   - ✅ **Decided:** Agreed — best-effort drift monitor + health warning; do not block on
     network time.
10. **Remote access.** WireGuard/Tailscale VPN vs Cloudflare Tunnel — operator preference?
    (Affects docs + a small amount of ops config, not core code.)
    - ✅ **Direction decided (R2):** **Tailscale** (WireGuard fallback; Cloudflare Tunnel
      declined — Atlas is an OS, not a public site). **Implementation deferred** out of this
      roadmap's build scope; done later. Dashboards ship localhost-first meanwhile.
11. **Sequencing.** Confirm Phase 0 → A before B/C/D. Which Phase-D Mission is the first
    end-to-end target? (Recommendation: Paper Trading, simulation-only.)
    - ✅ **Decided:** Agreed — Phase 0 → A before B/C/D; first end-to-end Mission is
      **Paper Trading (simulation-only)**.
12. **Storage Manager migration order (R2).** Which subsystems move behind the Storage
    Manager first (workspaces? backups? model files?), and what is the initial quota policy?
    - ⏳ **Open:** decide at Phase 0 design; recommendation: workspaces + backups first,
      quotas advisory (warn) before enforcing.
13. **Asset retention/tiering (R2).** How long are large binary assets (repos, CAD, PDFs)
    kept hot vs archived, and what triggers cold movement?
    - ✅ **Decided (R2):** **tiering is deferred — single disk today.** All assets stay on the
      one volume (`hot`); warm/cold movement is designed for but **not built until a second
      disk is bought**. Revisit retention/cold-movement policy at that point.
14. **Capability health model (R2).** Push (capabilities report health) vs pull (registry
    probes) for version/health/metrics?
    - ⏳ **Open:** recommendation — pull/probe on `/health` request + cache; revisit if noisy.
15. **Operations Dashboard host metrics (R2).** Which host signals are in v1 scope — CPU/RAM/
    disk are trivial; temperature/UPS/internet require sensors/agents. Include which now?
    - ⏳ **Open:** recommendation — CPU/RAM/disk/internet in v1; temperature/UPS best-effort
      (show "not present" when unavailable, as in the mock-up).

---

## 10. Non-goals (explicit)

- **No real-money trading.** Paper trading is **simulation-only**; no brokerage/live orders
  in this roadmap.
- **No new "Intelligence" per field.** Trading/medical/legal/CAD/etc. are Missions +
  Knowledge Domains, never new intelligences (P5).
- **No autonomous behavior change without a human gate.** Learning and the Decision Engine
  **recommend**; applying a behavior change stays operator-approved (consistent with the
  Stage 3B Learning OS stance).
- **No public exposure of Atlas.** Always localhost-bound; remote reach only ever via a
  private mesh VPN (Tailscale) — and **remote access is deferred out of this implementation**
  (R2), so nothing here binds beyond `127.0.0.1`.
- **No new top-level "Intelligence" or subsystem that fails the four-questions test (P7).**
- **No breaking of the microkernel.** New subsystems are services/managers wired in
  `bootstrap.py`; the kernel stays small and stable.

---

## 11. Decision log (append-only — to be filled during discussion)

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-07-18 | Draft created; reframe to Intelligence Domains + Missions proposed | Architecture matured to OS level | **Proposed — awaiting review** |
| 2026-07-18 | Q1: Missions are always operator/user-created; user selects which Missions/Jobs run in the backend | Operator stays in control; Atlas-suggested Missions out of scope for now | **Accepted** |
| 2026-07-18 | Q2: Missions own both Workers (continuous) and Jobs (finite); a Mission may create/own a Job as needed; results & outcomes viewable on demand | Matches ownership model; operator needs anytime visibility into study results | **Accepted** |
| 2026-07-18 | Q3: Short-task + checkpoint worker model, supervised by Worker Manager | Durability-first; survives restarts cleanly | **Accepted** |
| 2026-07-18 | Q4: Promote durable `inputs.jsonl` HITL queue to `worker.inputs` table | Enables live operator input/constraints to running workers | **Accepted** |
| 2026-07-18 | Q5: Global config stays file/env; Mission configs are DB-persisted versioned JSON validated by Pydantic | Keeps kernel config simple; per-mission config versioned & validated | **Accepted** |
| 2026-07-18 | Q6: Accept recovery startup latency; recovery must be idempotent and safely re-runnable after a failed boot (power/internet outage) | Guarantees safe restart with no corruption after interrupted startup | **Accepted** |
| 2026-07-18 | Q7: Decision Engine is deterministic core (rules/scoring); LLM for narrative/explanation only | Explainable and safer, especially for trading | **Accepted** |
| 2026-07-18 | Q8: Notification channels = web + email first (Telegram deferred); secrets env-only stance retained | Simplest reliable channels for now; secrets handling to finalize | **Accepted (channels); secrets open)** |
| 2026-07-18 | Q9: Best-effort NTP drift monitor + health warning; do not block on network time | Avoids hard network-time dependency | **Accepted** |
| 2026-07-18 | Q11: Phase 0 → A before B/C/D; first end-to-end Mission = Paper Trading (simulation-only) | Confirms sequencing and first target | **Accepted** |
| 2026-07-18 (R2) | Add **Storage Manager** as a first-class kernel subsystem (all durable data flows through it: DB, workspace, backups, files, cache, models; quotas, versioning, checksums, archive) | Storage was scattered; needed before repo/CAD ingestion | **Accepted** |
| 2026-07-18 (R2) | **Defer hot/warm/cold tiering** — single disk today; build tier-movement later when extra disk is bought. `tier` column ships now (default `hot`); tier-moves are a no-op until a second disk exists | No second volume to tier onto yet; keep design forward-compatible without building unused machinery | **Accepted (deferred, hardware-gated)** |
| 2026-07-18 (R2) | Separate **Assets from Knowledge** — add an **Asset Store** (raw files) feeding Knowledge Extraction → Knowledge OS | Makes re-parsing (e.g. new CAD reader) a re-extraction, not a re-download | **Accepted** |
| 2026-07-18 (R2) | **Enrich the Capability Registry** — per-capability version/enabled/healthy/metrics/dependencies for self-inspection | Enables self-diagnosis, health dashboard, real artifact version stamps | **Accepted** |
| 2026-07-18 (R2) | **Decision Engine is a Kernel Service**, not an intelligence | Every Mission needs "what next?"; belongs to Atlas itself | **Accepted** |
| 2026-07-18 (R2) | Extend **Mission Manager** with priority/criticality/budget/deadline/importance | Arbitrate CPU/RAM/LLM/disk/network across simultaneous missions | **Accepted** |
| 2026-07-18 (R2) | Ship **Mission Templates** (Research, Paper Trading, Job Hunting, Patent Watch, Repository Learning, Technology Watch, Security Monitoring) | Instantiate → customize → run (Docker-Compose-like) | **Accepted** |
| 2026-07-18 (R2) | Keep the name **"Engineering Intelligence"** (decline "Engineering Knowledge System") | Operator's final call | **Accepted (name final)** |
| 2026-07-18 (R2) | Add an **Operations Dashboard** (mobile-first, single-screen ops view) before Phase-0 build-out | First screen the operator sees; immediate health visibility | **Accepted** |
| 2026-07-18 (R2) | Q10 revisited: chosen remote-access approach is **Tailscale** (WireGuard fallback; Cloudflare Tunnel declined) but **implementation deferred** out of this roadmap | Best simplicity/security for a personal AI server; not built now | **Accepted (deferred)** |
| 2026-07-18 (R2) | Adopt the **Architecture Constitution** (P7): every new capability must be a Knowledge Domain, Mission, Persistent Worker, or Kernel Service | Keeps Atlas coherent long-term | **Accepted** |
| 2026-07-18 (R3) | Add **P9 — Everything is Explainable**: every decision/action carries why, evidence, knowledge, experience, config, rule, model version, confidence, alternatives-rejected | Reproducible + interrogable results across Engineering, trading, jobs, career, research | **Accepted** |
| 2026-07-18 (R3) | **Freeze the roadmap for implementation**; architecture + P1–P9 locked; remaining items are per-phase design details (§12) | Ready to spin out phase plans and start Phase 0 | **Accepted (frozen)** |

---

## 12. Implementation readiness & remaining ambiguities

**The plan is frozen.** The top-level architecture, the four planes, the subsystem set, the
phase order (0 → A → B → C → D), and principles **P1–P9** are locked and should not be
reopened without a new decision-log entry.

**What is fully decided (no ambiguity):** the reframe to Intelligence Domains + Missions;
Missions as first-class operator-created objects above Jobs; three permanent intelligences;
Decision Engine as a Kernel Service; Storage Manager + Asset Store (Assets ≠ Knowledge);
Capability Registry enrichment; Mission priorities + templates; durable event bus (web + SSE
+ email first); Clock service; Recovery Manager (idempotent/re-entrant); model-independence +
artifact versioning; design-for-failure; explainability (P9). Deferred by explicit decision:
**remote access** (Tailscale when built) and **hot/warm/cold tiering** (single disk today).

**Remaining ambiguities — all non-blocking, resolved at each phase's design step:**

| # | Ambiguity | Where it bites | Recommended default (confirm at design time) |
|---|---|---|---|
| A1 (Q8) | **Notification secrets** handling — env-only vs a secrets store; web-vs-email rollout order | Phase 0 (event bus) | Env-only secrets; ship web/SSE first, email right after |
| A2 (Q12) | **Storage Manager migration order** — which subsystems move behind it first; quota enforcement vs advisory | Phase 0 (Storage) | Workspaces + backups first; quotas **advisory (warn)** before enforcing |
| A3 (Q14) | **Capability health model** — push (self-report) vs pull (registry probes) | Phase 0 (Capability Registry) | Pull/probe on `/health` + short cache |
| A4 (Q15) | **Operations Dashboard host metrics** — which host signals in v1 (temp/UPS need sensors) | Phase 0 (Dashboard) | CPU/RAM/disk/internet in v1; temp/UPS best-effort ("not present" when absent) |
| A5 (Q7) | **Decision Engine determinism split** — exact boundary of rules/scoring vs LLM narrative | Phase D (Decision Engine) | Deterministic core for choices; LLM only for explanation prose |
| A6 (Q13) | **Asset retention/cold policy** — revisit only when a second disk exists | Post-Phase-B / hardware | Keep all `hot` now; define cold policy when tiering is switched on |
| A7 | **Mission priority arbitration formula** — how priority/criticality/budget/deadline combine into an RM allocation | Phase A (Mission Manager ↔ RM) | Start with a simple weighted priority + hard budget cap; refine empirically |
| A8 | **P9 explanation storage cost/retention** — full explanation records per action can grow large | Phase A/D | Store structured refs (ids), not copies; prune/roll up old records |
| A9 | **Personal Intelligence sourcing** — exactly how facts about the operator are elicited/confirmed | Phase C (greenfield) | Operator-curated + provenance per fact; no silent scraping (defer detail to Phase C plan) |

None of A1–A9 block starting Phase 0. Each becomes a small decision recorded in the relevant
`docs/PHASE_*_PLAN.md`.

> **Next step:** spin out `docs/PHASE_0_PLAN.md` (Clock, Storage Manager, Asset Store,
> Capability Registry enrichment, durable event bus + SSE, Operations Dashboard, Recovery
> Manager, artifact versioning, resumable downloads/checkpoint hooks) in the style of the
> Stage plans, resolving A1–A4 there, then begin implementation.
