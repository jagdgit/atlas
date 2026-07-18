# Phase A — Mission & Worker Foundation (implementation plan)

> **Status:** 🟢 **FROZEN FOR IMPLEMENTATION (2026-07-18).** Derived from
> `docs/ATLAS_OS_ROADMAP.md` §5.1–5.3, §5.5 (deferred), §6 (Phase A) after Phase 0 landed
> (Clock, Storage, Asset Store, Capability Registry, durable event bus + SSE, Operations
> Dashboard, Recovery Manager + checkpoints, artifact versioning). This is the per-phase detail
> doc. **Architect review (2026-07-18) — approved; refinements folded in:** mission_id on every
> mission-generated row, worker **version** + **health** + **upgrade strategy** (B8), a
> **`waiting`** mission state, **scheduling policy**, Kubernetes-style **labels**, mission
> **metadata** (distinct from config), and finalized decisions **B1–B9** (§6). Work items A.1–A.8
> and decisions B1–B9 are **locked**; §8 shows no open ambiguities remain. First slice: **A.1
> (Mission Manager + migration `0021`)**.
>
> **Goal:** add the **Mission layer above Jobs** — the single most important structural
> addition in the roadmap. After Phase A, the operator can instantiate a **Mission** from a
> **template** with a **versioned configuration** that owns **Persistent Workers** (and Jobs);
> workers checkpoint, survive reboot, are pausable/resumable, take live operator input, and
> every action is **journaled and explainable**. Priority arbitrates resources across
> simultaneous missions.
>
> **Not in Phase A:** the **Decision Engine** (§5.5) is **Phase D** — Phase A ships the mission/
> worker/config substrate it will later consume. Engineering/Personal intelligence are Phases
> B/C. No real-money anything (P10 non-goals).

---

## 0. Guiding constraints (from the constitution, §3)

- **P1 durability / P4 design-for-failure:** Missions, Workers, Schedules, Configs, Checkpoints
  are **durable** (survive `kill -9` + reboot). Workers are **short-task + checkpoint** loops
  (Q3), never long-lived threads holding state in memory. The Phase-0 Recovery Manager +
  `CheckpointStore` are reused verbatim.
- **P5 few-intelligences:** Mission Manager, Worker Manager, Configuration Manager are **Kernel
  Services** — not new intelligences. A "mission type" (paper trading, job hunting) is a
  **template + knowledge domains + config schema**, never a new subsystem (P7 four-questions).
- **P6 everything configurable + versioned:** every Mission runs off a **versioned** config;
  editing bumps a version; nothing is hardcoded in a worker.
- **P9 explainability:** every Mission action writes a **Journal** entry carrying *why /
  refs / config version*; journal entries store **structured refs (ids), not copies** (A8).
- **Provenance everywhere (architect R2):** every row Atlas creates *because of* a mission
  carries a **`mission_id`** (findings, experiences, assets, events, jobs, workers). "Show me
  everything Mission X produced" is then a filter, not a join graph. The mission is *provenance*
  — archiving/deleting a mission **never** deletes the knowledge/assets it produced (B9).
- **Constitution check (P7):** Mission = operator objective (Q2); Worker = persistent worker;
  Mission/Worker/Config Managers = kernel services. All four questions answered — no smell.
- **Discipline reminder (P5):** no new "Intelligence" per field (Trading/Finance/CAD/Security/
  Market). Those stay Knowledge Domains + Missions + Workers. Do not reopen this.

---

## 1. Resolved ambiguities (defaults locked for Phase A)

| # | Ambiguity | **Decision for Phase A** |
|---|---|---|
| A7 | **Mission priority arbitration formula** (how priority/criticality/budget/deadline combine into a Resource-Manager allocation) | **Policy-first, explainable, refine-later.** The **operator-facing knob is a `scheduling_policy`** enum (`realtime`/`background`/`batch`/`idle`/`exclusive`) — one field that stays stable instead of accumulating knobs (architect R5). It maps to a numeric base priority band; a mission also has fine-grain **`priority`** (int 0–100) + **`criticality`** enum (`low`/`normal`/`high`/`critical`). The effective task priority = `policy_band + priority + criticality_weight` (critical=+40, high=+20, normal=0, low=−20), written onto `scheduler.tasks.priority`. **Claim ordering = `priority DESC, scheduled_at ASC, id ASC`** (B2 — `id ASC` is the deterministic tie-breaker for same-µs rows). **`budget`** is a hard cap; **Phase A implements only `max_concurrent_tasks`** (B1) — the JSONB shape is extensible to `llm_units_per_window`/`cpu_percent`/`ram_mb`/`network_mb_per_hour`/`runtime` later. **`deadline`**/**`importance`** recorded + surfaced, advisory in v1. |
| A8 | **P9 explanation / journal storage cost + retention** | **Refs, not copies.** `mission.journal` and (Phase-D) `decision.decisions` store **ids/refs** (finding ids, config version, task id, knowledge/experience refs) + a short human `reason`, never full payloads. Journal is append-only; a later **roll-up/prune** job (interval, off by default) compacts entries older than N days into summaries. Not built in Phase A — schema leaves room. |
| A-new1 | **Worker execution model** (Q3, already decided in roadmap) | **Short-task + checkpoint**, supervised by the Worker Manager. A worker "tick" is one scheduler task (`worker_tick`) that: loads checkpoint → does a bounded unit of work → saves checkpoint → re-enqueues the next tick per its schedule. Survives restart cleanly; no long-lived thread owns state. |
| A-new2 | **Worker checkpoints storage** | **Reuse the Phase-0 `CheckpointStore`** (`system.checkpoints`, `owner_type='worker'`, `owner_id=worker_id`). Do **not** add a separate `worker.checkpoints` table (roadmap §8 `worker.checkpoints` is satisfied by the generic store). One checkpoint primitive, less schema. |
| A-new3 | **Mission ↔ Job ownership** (Q2) | Add a nullable **`mission_id`** column to `job.jobs` (soft link, no hard FK across the mission/job boundary so a job can outlive a mission cleanup). A Mission may create/own Jobs; the Mission view aggregates its Jobs + Workers for on-demand results (Q2). |
| A-new4 | **Global vs mission config** (Q5) | Global app config stays **file/env** (`config/manager.py`). **Mission configs are DB-persisted, versioned JSON** validated by a **per-mission-type Pydantic schema** registered in the Configuration Manager. |
| A-new5 | **Mission state model** (architect R3) | `draft → active → **waiting** → paused → completed → archived`. **`waiting`** (distinct from `paused`) = *ready but blocked on an external condition* (market open, internet, next schedule); the Worker/Mission manager sets it automatically. `paused` = *operator-halted*. Only `waiting`/`active` self-transition; `paused`/`archived` need the operator. |
| A-new6 | **Worker state + health model** (architect R2/R4/B4) | Worker lifecycle states: `running → recovering → paused → failed → stopped`. Separately, a **health** tier for the dashboard: `healthy / degraded / blocked / recovering / failed`. A crashing tick does **not** flip straight to `failed`: it goes `recovering` with **exponential backoff** (10s → 30s → 60s → 5m), journaling each retry; after the **5th** consecutive failure → `paused` (never a crash loop). |
| A-new7 | **Worker identity carries a version** (architect R2/B8) | Every worker row + checkpoint records the **`worker_version`** that produced it. **Upgrade strategy (B8):** a running worker is never hot-swapped mid-tick — it **finishes the current tick → checkpoints → the next tick loads the new worker version → resumes**. Recovery reports "resumed using worker vN". |
| A-new8 | **Labels + metadata** (architect: add now) | Missions carry **`labels`** (free-form tags, K8s-style — `finance`, `simulation`, `long_running`, …) for `list?label=finance` filtering, and **`metadata`** (created_by, description, owner, notes) kept **separate from configuration** (config changes often; metadata rarely). |

---

## 2. Work items (ordered) & acceptance

Order is chosen so each item lands, tests, and commits independently, mirroring Phase 0. Each
item is a kernel service wired in `bootstrap.py` with hermetic (fake-repo) unit tests plus a
DB migration where noted.

### A.1 Mission Manager + Mission Journal  ·  *first (the spine)*
- **Build** `atlas/missions/` — `MissionService` (registered service), `MissionRepository`,
  models `Mission`, `MissionJournalEntry`. Lifecycle `draft → active → waiting → paused →
  completed → archived` (A-new5); operator-created only (Q1). Methods: `create_mission`,
  `activate`/`pause`/`resume`/`complete`/`archive`, `mark_waiting(reason)`/`clear_waiting`,
  `journal(action, reason, refs)`, `get_mission` (aggregates owned Jobs + Workers + latest
  journal for the on-demand results view, Q2), `list_missions(label=…, status=…)`.
- **Arbitration fields (R2/A7):** `scheduling_policy` (enum), `priority` (int 0–100),
  `criticality` (enum), `budget` (JSONB — **Phase A uses `max_concurrent_tasks` only**, B1;
  shape extensible), `deadline` (nullable ts), `importance` (text). Consumed in A.6.
- **Labels + metadata (architect):** `labels` (text[] — K8s-style filtering) and `metadata`
  (JSONB: created_by, description, owner, notes) — **separate from configuration**.
- **Provenance (`mission_id` everywhere):** add a nullable `mission_id` to `job.jobs`,
  `knowledge.findings`, `learning.experiences`, `asset.assets`, and `audit.events` (folded into
  `0021` — the migration runner requires an `NNNN_` numeric prefix, so a `0021b` file would be
  silently skipped; one migration per slice); the services that write those rows accept an
  optional `mission_id` (threaded from the active mission/worker context, wired in later slices).
  Back-compatible: `NULL` for all non-mission work. Enables "everything from Mission X" as a
  filter (architect R1).
- **Journal (P9/A8):** append-only `mission.journal` — `ts, action, reason, refs JSONB`
  (ids only, never copies). Every state change + worker/job spawn writes an entry. Emits
  `MissionCreated`/`MissionActivated`/`MissionWaiting`/… on the durable event bus → dashboard.
- **Archival is non-destructive (B5/B9):** `archive` sets status `archived` (schedule/worker
  disabling hooks land with A.3/A.4) — but **keeps** configs, journal, findings, experiences,
  assets, checkpoints. Hard `DELETE` is an explicit admin-only path, never the default.
- **Migration** `0021_missions.sql` — `mission.missions`, `mission.journal`, **and** the
  `mission_id` provenance `ALTER`s on `job.jobs`, `knowledge.findings`, `learning.experiences`,
  `asset.assets`, `audit.events` (all nullable). Provenance is folded into `0021` (single
  migration per slice; a `0021b` prefix is not discoverable by the runner).
- **Acceptance:** create → activate → (waiting ↔ active) → pause → resume → complete → archive;
  each transition is journaled + emits an event; `get_mission` returns owned jobs/workers +
  journal; `list_missions(label=…)` filters; invalid transitions (e.g. resume a completed
  mission) are rejected; archive keeps all produced rows (B9). ✅ **DONE (2026-07-18)** —
  `atlas/missions/` (service+repo), `atlas/models/mission.py`, migration `0021` applied,
  wired in `bootstrap.py` (container + Capability Registry + lifecycle), 13 hermetic tests +
  live-DB smoke pass; full suite green (1139).

### A.2 Configuration Manager (versioned, per-mission)  ·  *before workers read config*
- **Build** `atlas/configuration/` — `ConfigurationService`, `ConfigRepository`, a
  **schema registry** mapping `schema_type` → Pydantic model (validates the JSON document).
  Methods: `create_config(mission_id, schema_type, document)` → **v1**; `update_config(...)`
  → **new version** (never mutate in place) with a `change_note`; `get_active`/`get_version`/
  `list_versions`; `set_active(mission_id, version)`.
- **Validation:** documents are validated against the registered Pydantic schema at write time;
  invalid configs are rejected (never stored). Ship an initial `hello_watcher` schema + the
  template schemas from A.5.
- **Explicit schema versioning (B6):** each config row records `schema_type` **and**
  `schema_version` (e.g. `paper_trading` / `3`). Old config rows are **immutable** and keep the
  `schema_version` they were written under. A schema change is a **new `schema_version`**; a
  later opt-in migration tool may transform `v2 → v3` documents — **never automatically**.
- **Reproducibility (P6):** `Mission.active_config_id` points at the active version; every
  worker tick + journal entry records the **config version + schema_version** it used.
- **Migration** `0022_mission_configs.sql` — `config.mission_configs` (id, mission_id, version,
  schema_type, **schema_version**, document JSONB, change_note, created_at;
  `UNIQUE(mission_id, version)`).
- **Acceptance:** create config v1 → edit → v2 (v1 immutable, retained); invalid document
  rejected with a clear error; `set_active` flips the mission's active version; a worker reads
  the active version by number and sees its `schema_version`.

### A.3 Recurring / interval scheduling (schedule table)  ·  *worker substrate*
- **Build** promote the hand-rolled `delay_seconds` self-re-enqueue to a first-class
  **`scheduler.schedules`** table + `ScheduleRepository`, driven by the existing
  `SchedulerService`. A schedule row: `task_type, payload, interval_seconds, next_run_at,
  enabled, mission_id, worker_id`. A lightweight scheduler tick (`schedule_tick`, itself a
  durable task) enqueues due schedules and advances `next_run_at`. **Continuous** = tiny
  interval; **interval** = N seconds; **cron** deferred (documented, not built).
- **Why:** workers (A.4), backups, and ingestion all currently re-enqueue themselves ad hoc;
  this centralizes recurrence so it is durable, inspectable, and pausable per mission.
- **Migration** `0023_schedules.sql` — `scheduler.schedules`.
- **Acceptance:** register an interval schedule → it fires on cadence across restarts (survives
  `kill -9` — `next_run_at` is durable); disabling a schedule stops it; deleting a mission
  cascades/disables its schedules.

### A.4 Persistent Worker framework + Worker Manager  ·  *the payoff*
- **Build** `atlas/workers/` — `WorkerManager` (registered service; supervises workers,
  enforces RM/budget admission), a `PersistentWorker` base with **checkpoint hooks**
  (`load_checkpoint`/`save_checkpoint` over the Phase-0 `CheckpointStore`, `owner_type='worker'`),
  and a `WorkerRepository`. Execution = **short-task + checkpoint** (A-new1): `worker_tick`
  handler loads checkpoint → drains inputs → does one bounded unit → saves checkpoint →
  schedules next tick (A.3). Lifecycle `start/pause/resume/stop`; owned by a Mission; honors the
  Mission's active config version.
- **Worker identity + version (A-new7/B8):** each worker row + checkpoint stores
  `worker_version`. **Upgrade = finish tick → checkpoint → next tick loads new version → resume**
  (never hot-swap mid-tick). The base compares the running code's version to the row's version at
  tick start and journals `worker upgraded vN→vM` when it changes.
- **States + health + crash policy (A-new6/B4):** lifecycle `running → recovering → paused →
  failed → stopped`; health tier `healthy/degraded/blocked/recovering/failed` for the dashboard.
  A failing tick → `recovering` with **exponential backoff (10s→30s→60s→5m)**, journaling each
  retry; **5th** consecutive failure → `paused` (no crash loop).
- **Live operator input (Q4):** promote the durable `inputs.jsonl` HITL queue to a
  **`worker.inputs`** table — `enqueue_input(worker_id, payload)` / `drain_inputs(worker_id)`;
  workers consume pending inputs at the **top of each tick** (this is "give paper trading a
  constraint while it runs").
- **Ship a trivial worker:** `HelloWatcher` (a heartbeat that increments a counter in its
  checkpoint and journals a tick) — the Phase-A acceptance vehicle, and the reference impl for
  Phase-D workers.
- **Migration** `0024_workers.sql` — `worker.workers` (id, mission_id, type, **worker_version**,
  status, **health**, schedule_id, config_version, restart_count, next_retry_at,
  created/updated), `worker.inputs` (durable operator input queue). Checkpoints reuse
  `system.checkpoints` (A-new2).
- **Acceptance:** a `HelloWatcher` owned by a mission ticks on a schedule, **checkpoints each
  tick**, **survives reboot** (resumes from last checkpoint count, not zero), is
  **pausable/resumable/stoppable**, **consumes a live operator input**, records its
  **`worker_version`** and resumes on that version after a simulated upgrade, transitions
  `recovering→paused` after repeated forced failures (backoff), and journals each tick.

### A.5 Mission Templates (instantiate → customize → run)
- **Build** a **template registry** in `atlas/missions/templates/` — a `MissionTemplate`
  declares: `name`, `worker_specs` (types + default schedules), `config_schema_type` +
  `default_config`, `knowledge_domains[]`, `success_criteria`. `MissionService.instantiate(
  template_name, overrides)` produces a concrete **Mission + config v1 + worker rows**
  (Docker-Compose-like). Ship the initial set as **stubs** (real behavior lands in Phase B/C/D):
  **Research, Paper Trading, Job Hunting, Patent Watch, Repository Learning, Technology Watch,
  Security Monitoring** — plus a fully-working **Hello Watcher** template for acceptance.
- **Template versioning (B7):** templates carry a **`template_version`**; a mission records the
  `template_id + template_version` it was instantiated from. Built-ins are **upserted by name**
  on boot (bumping `template_version`), but **existing operator missions are never auto-updated**
  — an upgrade is an explicit operator choice (upgrade vs leave-alone).
- **Migration** `0025_mission_templates.sql` — `mission.templates` (id, name UNIQUE,
  **template_version**, worker_specs JSONB, config_schema_type, **config_schema_version**,
  default_config JSONB, knowledge_domains[], success_criteria JSONB) — built-ins seeded
  idempotently on boot so the DB is the source of truth.
- **Acceptance:** `instantiate("hello_watcher")` yields an active mission with a versioned
  config and a running `HelloWatcher`, stamped with `template_version`; overrides customize the
  config at instantiation; a built-in template bump does not mutate existing missions.

### A.6 Priority arbitration (Mission ↔ Resource Manager)  ·  *A7*
- **Wire** mission `scheduling_policy` + `priority` + `criticality` into task enqueue:
  mission-owned tasks (job advance, worker ticks) get
  `scheduler.tasks.priority = policy_band + priority + criticality_weight`. Update
  `TaskRepository.claim_next` ordering to **`priority DESC, scheduled_at ASC, id ASC`** (B2 —
  deterministic tie-break; today it's FIFO by `scheduled_at`). This changes ordering for **all**
  task types; existing callers use `priority=0`, so equal-priority FIFO is preserved — add a
  regression test on non-mission tasks.
- **Budget (B1):** enforce **`max_concurrent_tasks` only** in Phase A at enqueue via the
  Worker/Mission manager (skip/delay a tick when the mission is at its cap). `llm_units_per_window`
  and host-resource caps are deferred (extensible JSONB). `deadline`/`importance` advisory.
- **Acceptance:** under contention (two active missions, limited workers), the higher-policy/
  priority mission's ticks are claimed first (deterministic with `id ASC`); a mission at its
  `max_concurrent_tasks` cap is throttled (extra ticks wait) while a within-budget mission
  proceeds; the choice is visible/explainable in the journal + dashboard.

### A.7 API + Operations Dashboard surfacing
- **API** (`atlas/api/routes.py`): `GET /v1/missions`, `GET /v1/missions/{id}` (aggregated
  results/outcomes on demand — Q2), `POST /v1/missions` (create/instantiate from template),
  mission lifecycle actions, `GET /v1/missions/{id}/journal`, `GET /v1/workers`,
  `POST /v1/workers/{id}/input` (live operator input). All API-key gated; events over the
  existing SSE stream.
- **Dashboard** (`atlas/web/static/`): the Overview `counts` gain **real** `missions` +
  `workers` (currently 0); a **Missions** view lists missions with status/priority + a journal
  ("Explain this" foundation, P9). Mobile-first, consistent with Phase 0.
- **Acceptance:** the operator can create/instantiate a mission, watch its workers tick live,
  read its journal, and push an input — all from the console; `GET /v1/ops` shows non-zero
  mission/worker counts.

### A.8 End-to-end acceptance (the Phase-A gate)
Instantiate the **Hello Watcher** mission **from a template** with a versioned config → it owns
a Persistent Worker that ticks on a schedule, **checkpoints**, **survives a `kill -9` + reboot**
(resumes mid-count), is **pausable/resumable**, an **edited config bumps a version** (worker
picks it up next tick), **priority influences scheduling under contention**, a **live input** is
consumed, and **every action is journaled + explainable**. Covered by hermetic unit tests per
item + one integration test exercising the full lifecycle against the live DB.

---

## 3. Data-model additions (Phase A)

All `TIMESTAMPTZ` minted via the Clock service; all long-lived (P1). New schemas created
`AUTHORIZATION atlas` (same pattern as Phase 0), so `atlas-db migrate` owns them.

| Migration | Objects |
|---|---|
| `0021_missions.sql` | `mission.missions` (id, title, objective, status [`draft/active/waiting/paused/completed/archived`], success_criteria JSONB, knowledge_domains[], active_config_id, **scheduling_policy, priority, criticality, budget JSONB, deadline, importance**, **labels text[]**, **metadata JSONB**, template_id, template_version, created/updated); `mission.journal` (id, mission_id, ts, action, reason, refs JSONB — append-only, ids-only); **plus** nullable **`mission_id`** added to `job.jobs`, `knowledge.findings`, `learning.experiences`, `asset.assets`, `audit.events` (provenance-everywhere; `NULL` for non-mission work). *Provenance folded into `0021` — a `0021b` prefix isn't discoverable by the migration runner (`^\d+_`).* |
| `0022_mission_configs.sql` | `config.mission_configs` (id, mission_id, version, schema_type, **schema_version**, document JSONB, change_note, created_at; `UNIQUE(mission_id, version)`; never mutated in place) |
| `0023_schedules.sql` | `scheduler.schedules` (id, task_type, payload JSONB, interval_seconds, next_run_at, enabled, mission_id, worker_id, created/updated) |
| `0024_workers.sql` | `worker.workers` (id, mission_id, type, **worker_version**, status [`running/recovering/paused/failed/stopped`], **health**, schedule_id, config_version, restart_count, next_retry_at, created/updated); `worker.inputs` (id, worker_id, payload JSONB, status, created_at — durable operator input queue) |
| `0025_mission_templates.sql` | `mission.templates` (id, name UNIQUE, **template_version**, worker_specs JSONB, config_schema_type, **config_schema_version**, default_config JSONB, knowledge_domains[], success_criteria JSONB) — built-ins upserted by name idempotently on boot |

**Checkpoints:** no new table — reuse Phase-0 `system.checkpoints` (`owner_type='worker'`), and
each checkpoint state carries the `worker_version` that wrote it (B8 resume).

---

## 4. Dependencies & sequencing

```
A.1 Mission Manager ──┬─> A.2 Configuration Manager ──┐
                      │                                 ├─> A.4 Worker framework ─> A.6 Priority ─> A.7 API/UI ─> A.8 E2E
                      └─> A.3 Schedule table ──────────┘
                                    A.5 Templates (needs A.1+A.2+A.4)
```

- Reuses Phase 0: `CheckpointStore`/`RecoveryManager` (worker resume), durable event bus + SSE
  (mission/worker events), Operations Dashboard (counts), Clock (timestamps), Capability
  Registry (register the three new kernel services).
- Extends existing code: `SchedulerService`/`TaskRepository` (priority claim ordering `priority
  DESC, scheduled_at ASC, id ASC` + schedule tick), `JobService`/`job.jobs` (`mission_id`),
  `ResourceManager` (mission-level budget hint), and the writers of `knowledge.findings` /
  `learning.experiences` / `asset.assets` / `audit.events` (accept an optional `mission_id` for
  provenance — back-compatible `NULL`).

---

## 5. Progress checklist

- [x] A.1 Mission Manager + Journal (+ labels/metadata/`waiting`) — migration `0021` (mission schema + `mission_id` provenance folded in) ✅ 2026-07-18
- [ ] A.2 Configuration Manager (versioned per-mission + schema_version) — migration `0022`
- [ ] A.3 Recurring/interval schedule table — migration `0023`
- [ ] A.4 Persistent Worker framework + Worker Manager (+ `worker.inputs`) — migration `0024`
- [ ] A.5 Mission Templates (instantiate → customize → run) — migration `0025`
- [ ] A.6 Priority arbitration (scheduler claim ordering + budget)
- [ ] A.7 API + Operations Dashboard surfacing (missions/workers/journal/input)
- [ ] A.8 End-to-end: Hello Watcher mission from template (checkpoint/reboot/pause/priority/input)

---

## 6. Decisions locked at freeze

| # | Decision | Status |
|---|---|---|
| D-A7 | **Arbitration:** `scheduling_policy` (operator knob) → priority band; effective task priority = `policy_band + priority + criticality_weight`; hard `budget` cap; deadline/importance advisory. | **Accepted** |
| D-A8 | **Explanation/journal storage:** store **refs (ids) + short reason**, never full payloads; roll-up/prune deferred. | **Accepted** |
| D-CK | **Checkpoints:** reuse Phase-0 `system.checkpoints` (`owner_type='worker'`) — no separate table; state carries `worker_version`. | **Accepted** |
| D-TPL | **Templates:** 7 domain templates as **stubs**; **Hello Watcher** fully working. | **Accepted** |
| D-DE | **Decision Engine stays Phase D.** | **Accepted** |
| D-M1 | **First real Mission** (end-to-end) is **Paper Trading, simulation-only** (Phase D). | **Accepted** |
| **B1** | **`budget`:** implement **`max_concurrent_tasks` only** in Phase A; JSONB shape extensible to LLM/CPU/RAM/network/runtime later. | **Accepted** |
| **B2** | **Claim ordering:** `priority DESC, scheduled_at ASC, id ASC` (deterministic tie-break) + a regression test on non-mission tasks. | **Accepted** |
| **B3** | **Schedules:** `scheduler.schedules` for **workers only** in Phase A; backup/ingestion self-re-enqueue untouched (migrate in a later phase). | **Accepted** |
| **B4** | **Worker crash policy:** `recovering` + **exponential backoff (10s→30s→60s→5m)**, journal each retry, → `paused` after the 5th consecutive failure. | **Accepted** |
| **B5** | **Mission deletion:** **soft-archive only** by default (disable schedules, stop workers; keep everything); hard `DELETE` is admin-only. | **Accepted** |
| **B6** | **Config schema evolution:** explicit `schema_version`; old configs immutable; opt-in transform tool later, never automatic. | **Accepted** |
| **B7** | **Templates:** versioned (`template_version`); upsert built-ins by name on boot; **never auto-update operator missions**. | **Accepted** |
| **B8** | **Worker upgrade:** finish current tick → checkpoint → next tick loads new `worker_version` → resume (no mid-tick hot-swap). | **Accepted** |
| **B9** | **Archival never deletes knowledge/assets/experiences/findings/checkpoints** — the mission is provenance only. | **Accepted** |
| D-LBL | **Labels + metadata** added now (K8s-style labels for filtering; metadata separate from config). | **Accepted** |
| D-PROV | **`mission_id` on every mission-generated row** (jobs, findings, experiences, assets, events) for one-filter provenance. | **Accepted** |
| D-WAIT | **`waiting`** mission state (external-condition block, distinct from operator `paused`). | **Accepted** |

---

## 7. Implementation readiness

**The plan is frozen.** Work items **A.1–A.8**, their order/dependencies (§4), the data model
(§3), and the locked decisions (§6) should not be reopened without a note here. Every slice
follows the Phase-0 rhythm: **land → hermetic (fake-repo) unit tests → migration (where noted)
→ apply → commit-ready → update the §5 checklist**. Each new service is registered in
`bootstrap.py` (container + Capability Registry + lifecycle) and emits durable events.

**Execution discipline (architect):** freeze this doc and build it exactly as written; resist
adding new concepts until **Hello Watcher** survives create → schedule → checkpoint → `kill -9`
recovery → config update → journal → API control end to end (A.8). That validates the execution
model every future Mission relies on; Phase B then becomes *capability expansion*, not redesign.

---

## 8. Ambiguities — status

All Phase-A ambiguities are now **resolved** (A7, A8, A-new1–8, B1–B9; see §1 and §6). **No open
items block implementation.** Two design questions are intentionally **deferred to later phases**
(not Phase A): the LLM-units/host-resource budget dimensions (B1, Phase D when concurrency exists)
and cron scheduling (A.3, later phase). Both have forward-compatible schemas so enabling them is
additive.

---

## 9. Architectural debt (tracked, not hidden)

Per architect guidance, every phase records the temporary compromises it ships so shortcuts stay
visible instead of becoming permanent.

| Compromise (Phase A) | Reason | Removal plan |
|---|---|---|
| **Budget = `max_concurrent_tasks` only** | No concurrent-worker pressure yet; keep it deterministic | Extend JSONB to LLM/CPU/RAM/network/runtime in Phase D when missions run simultaneously |
| **Cron not implemented** (interval/continuous only) | Interval covers every Phase-A/D need | Add cron parsing to `scheduler.schedules` in a later phase |
| **Domain templates are stubs** | Real behavior needs Engineering/Personal/Decision (Phases B/C/D) | Fill in per template as its phase lands (config schema already versioned) |
| **`scheduler.schedules` used by workers only** | Migrating backup/ingestion now widens Phase A unnecessarily | Migrate remaining self-re-enqueue producers onto it in a later phase |
| **No config `v2→v3` transform tool** | Rarely needed early; old configs are immutable | Ship an opt-in migration tool when a schema first needs a breaking change |
| **Priority formula is linear (`policy+priority+criticality`)** | Explainable and sufficient; deadline/importance advisory | Fold deadline/importance into the score empirically once observed under load |

---

## 10. Future-proofing (NOT Phase A — noted for coherence)

- **Workflow Engine (≈ Phase E):** the architecture is trending toward
  `Mission → Workflow → Worker A → Worker B → Decision → Worker C` instead of each worker
  manually spawning the next. **Not built now** — but the Mission/Worker/Schedule/Journal
  substrate is deliberately shaped so a workflow orchestrator can sit on top later without
  redesign. Recorded here so it isn't "invented" ad hoc.
- **Explicitly not added (P5 discipline):** no Trading/Finance/CAD/Security/Market
  "Intelligence" — those remain Knowledge Domains + Missions + Workers, forever.

> **Next step:** A.1 ✅ landed (2026-07-18). Proceed to **A.2 — Configuration Manager (versioned,
> per-mission; migration `0022`)**, then continue down §5 in order.
