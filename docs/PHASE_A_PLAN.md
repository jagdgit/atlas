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
  the active version by number and sees its `schema_version`. ✅ **DONE (2026-07-18)** —
  `atlas/configuration/` (service + repo + Pydantic `SchemaRegistry`, `hello_watcher` shipped),
  `atlas/models/config.py`, migration `0022` applied, wired in `bootstrap.py` (shares the
  `MissionRepository` to flip active + journal), 13 hermetic tests + live-DB smoke pass; full
  suite green (1152). First config auto-activates; `update_config` is inactive-by-default;
  `set_active` flips explicitly (B6). Provenance/`mission_id` threading into config writers
  is deferred to the worker slices (A.4/A.6).

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
  cascades/disables its schedules. ✅ **DONE (2026-07-18)** — `scheduler.schedules` (migration
  `0023`), `atlas/repositories/schedule_repo.py` (atomic `claim_due` claim-and-advance),
  `atlas/scheduler/schedules.py` (`ScheduleService` + durable `schedule_tick` that fires due
  schedules, advances `next_run_at`, re-enqueues itself, self-heals if claiming fails), wired in
  `bootstrap.py` (handler + container + capability + lifecycle; seeds the tick on boot). Mission
  archive now disables the mission's schedules; mission delete cascades them. 10 hermetic tests +
  live-DB smoke (tick advances, no immediate re-claim, archive disables, delete cascades) pass;
  full suite green (1162). *Cron deferred (interval/continuous only, per B3); backup/ingestion
  self-re-enqueue left untouched (migrate later).*

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
  ✅ **DONE (2026-07-18)** — `worker.workers` + `worker.inputs` (migration `0024`),
  `atlas/models/worker.py`, `atlas/repositories/worker_repo.py`, `atlas/workers/`
  (`PersistentWorker` base + `TickContext/TickResult`, `HelloWatcher`, `WorkerManager`), wired in
  `bootstrap.py` (`worker_tick` handler; reuses Phase-0 `CheckpointStore` `owner_type='worker'`;
  deps: schedule/config/mission/checkpoint/clock). Crash policy = `recovering` + backoff
  10/30/60/300s, pause on the 5th failure (recovering ticks self-skip until `next_retry_at`).
  Version upgrade journals `vN→vM` at tick start (B8); active config version picked up + journaled
  next tick. Mission archive stops workers + disables schedules; mission delete cascades workers +
  inputs. 16 hermetic tests + live-DB smoke (2 ticks→count 2, **new manager instance resumes to
  3**, live input applied, config bumped + picked up, archive stopped worker, cascade) pass; full
  suite green (1178). *`WorkerManager.stop_worker` names the operator stop to avoid clashing with
  the service-lifecycle `stop`.*

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
  ✅ **DONE (2026-07-18)** — `mission.templates` (migration `0025`), `atlas/models/template.py`,
  `atlas/repositories/template_repo.py` (`upsert_by_name`), `atlas/missions/templates/`
  (`builtins.py` = HelloWatcher + 7 domain stubs; `TemplateService` seeds on boot + `instantiate`).
  A permissive `generic` config schema backs the stubs (tightened to strict schema + new
  `schema_version` when each Phase lands). Wired in `bootstrap.py` (container + capability +
  lifecycle; seeds built-ins on start). 8 hermetic tests + live-DB smoke (instantiate hello_watcher
  with overrides → active mission + config v1 + running worker → 2 ticks hit `tick_limit` → done;
  bump+re-seed leaves existing mission stamp at v1; stub creates mission+generic config, no workers)
  pass; full suite green (1186). *Deviation: instantiation is its own `TemplateService`
  (composing Mission/Config/Worker managers) rather than `MissionService.instantiate`, so the
  Mission Manager keeps no hard deps on config/worker layers.*

### A.6 Priority arbitration (Mission ↔ Resource Manager)  ·  *A7*  ✅ 2026-07-18
- **Done — wired** the owning mission's **effective priority** (`policy_band + priority +
  criticality_weight`, via `Mission.effective_priority`) into schedule-fired tasks:
  `ScheduleService` now takes an optional `mission_repo` and stamps each fired task with its
  mission's priority (`_priority_for`; non-mission schedules → `0`). Worker ticks flow through
  schedules, so this covers the worker path. **Job-advance priority** threading is deferred (no
  mission currently *owns* jobs until Phase D) — tracked in Architectural Debt.
- **Done — claim ordering (B2):** `TaskRepository.claim_next` (and `list_by_status`) now order by
  **`priority DESC, scheduled_at ASC, id ASC`** — deterministic tie-break. Equal-priority tasks
  keep FIFO-by-`scheduled_at`; `id ASC` breaks exact ties. Verified on live DB (high-priority task
  claimed first; two priority-5 tasks claimed in creation order).
- **Done — budget (B1):** `WorkerManager` enforces **`max_concurrent_tasks` only** via an
  in-memory per-mission concurrency gate (`_acquire`/`_release` under a lock). A tick whose mission
  is at its cap is skipped (`{"skipped": "budget"}`) and emits `WorkerThrottled`; the slot is
  released in a `finally`. `llm_units_per_window` and host-resource caps deferred (extensible
  JSONB); `deadline`/`importance` advisory.
- **Acceptance met:** higher-priority mission ticks are claimed first (deterministic with
  `id ASC`); a mission at its `max_concurrent_tasks` cap is throttled while a within-budget mission
  proceeds; the throttle is observable via the `WorkerThrottled` event. Unit tests:
  `tests/test_workers.py` (budget throttle + release), `tests/test_schedules.py` (mission-priority
  enqueue). Full suite **1190 passed**.
- **Debt:** the budget gate is **in-memory (single-process Phase A)** — move to a durable/shared
  counter when the scheduler runs multi-process. Job-advance priority threading pending Phase D.

### A.7 API + Operations Dashboard surfacing  ✅ 2026-07-18
- **Done — API** (`atlas/api/routes.py`, all API-key gated): `GET /v1/missions` (status/label
  filter; adds derived `effective_priority` + `max_concurrent_tasks`), `POST /v1/missions`
  (create; `activate:true` optional), `POST /v1/missions/instantiate` (from a built-in template →
  mission + config v1 + workers), `GET /v1/missions/{id}` (aggregated view: mission + job_ids +
  **workers** + journal, Q2), `GET /v1/missions/{id}/journal`, `POST /v1/missions/{id}/{action}`
  (`activate|pause|resume|complete|archive` — illegal transitions → **409**), `GET /v1/templates`,
  `GET /v1/workers` + `GET /v1/workers/{id}`, `POST /v1/workers/{id}/{action}`
  (`pause|resume|stop`), and `POST /v1/workers/{id}/input` (live operator input, Q4 — declared
  before the generic `{action}` route so `input` isn't captured). Domain errors mapped to
  404/409/400. Events flow over the existing SSE stream (mission/worker `_emit`).
- **Done — aggregated view:** `MissionService.get_mission` now populates **owned workers** (via
  the optional `worker_repo`), replacing the A.4 placeholder.
- **Done — dashboard** (`atlas/web/static/`): Overview `counts` now carry **real** `missions`,
  `missions_active`, `workers`, `workers_total` (from the Mission Manager + Worker Manager health).
  A new **Missions** view instantiates from a template, lists missions (status + effective
  priority), and a detail pane shows lifecycle actions, per-worker cards (pause/resume/stop + a
  JSON live-input box), and the **Journal** ("Explain this" foundation, P9). Mobile-first, vanilla
  SPA consistent with Phase 0; new status badge colors for mission/worker states.
- **Acceptance met:** operator can create/instantiate a mission, see its workers, read its
  journal, push a live input, and drive lifecycle — all from the console; `GET /v1/ops` shows
  non-zero mission/worker counts (verified live: `missions=1, missions_active=1, workers=1`).
  Tests: `tests/test_api.py` (+10 mission/worker/template cases). Full suite **1200 passed**.

### A.8 End-to-end acceptance (the Phase-A gate)  ✅ 2026-07-18
Instantiate the **Hello Watcher** mission **from a template** with a versioned config → it owns
a Persistent Worker that ticks on a schedule, **checkpoints**, **survives a `kill -9` + reboot**
(resumes mid-count), is **pausable/resumable**, an **edited config bumps a version** (worker
picks it up next tick), **priority influences scheduling under contention**, a **live input** is
consumed, and **every action is journaled + explainable**. Covered by hermetic unit tests per
item + one integration test exercising the full lifecycle against the live DB.

- **Done — `tests/test_phase_a_e2e.py`** (live DB; whole module skips if PostgreSQL is
  unreachable, matching `test_repositories`). Wires the **real** Mission / Configuration /
  Schedule / Worker / Template stack exactly as `bootstrap` does, minus the running scheduler so
  ticks are driven deterministically.
- **`test_hello_watcher_full_lifecycle`** walks the entire gate: instantiate → mission `active` +
  config v1 + running worker (journal has `created/config_created/activated/worker_created`);
  tick → checkpoint `count=1`; **process-restart resume** via a *fresh* `WorkerManager` over the
  same DB → `count=2` (proves the Postgres checkpoint is what survives `kill -9`); pause (tick
  `skipped: paused`) → resume → `count=3`; **config bump** to v2 (`activate=True`) → next tick
  journals `config_picked_up` and the checkpoint greeting changes; **live input** overrides the
  greeting on the next tick (Q4); `tick_limit` bump → worker reports `done` + `stopped`
  (`worker_done`); **non-destructive archive** keeps checkpoint + config v1; final journal asserts
  all ten expected actions are present (P9).
- **`test_priority_influences_scheduling_under_contention`**: two missions with a clear priority
  gap (realtime+critical vs idle+low); enqueue LOW then HIGH via the schedule layer → deterministic
  `claim_next` orders HIGH before LOW (`priority DESC, scheduled_at ASC, id ASC`).
- **Result:** both pass on the live DB; full suite **1202 passed**. *(`kill -9` resume is proven
  via the durable-checkpoint restart simulation rather than actually killing the process, which
  isn't feasible in-process.)*

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
- [x] A.2 Configuration Manager (versioned per-mission + schema_version) — migration `0022` ✅ 2026-07-18
- [x] A.3 Recurring/interval schedule table (`schedule_tick` driver, mission cascade/disable) — migration `0023` ✅ 2026-07-18
- [x] A.4 Persistent Worker framework + Worker Manager (+ `worker.inputs`, HelloWatcher, crash backoff, B8 upgrade) — migration `0024` ✅ 2026-07-18
- [x] A.5 Mission Templates (HelloWatcher + 7 stubs, versioned, instantiate → customize → run) — migration `0025` ✅ 2026-07-18
- [x] A.6 Priority arbitration (mission-priority enqueue + `priority DESC, scheduled_at ASC, id ASC` claim ordering + in-memory `max_concurrent_tasks` budget) ✅ 2026-07-18
- [x] A.7 API + Operations Dashboard surfacing (missions/workers/templates/journal/input endpoints + Missions console view + real ops counts) ✅ 2026-07-18
- [x] A.8 End-to-end: Hello Watcher mission from template (checkpoint/reboot/pause/priority/input) — `tests/test_phase_a_e2e.py` ✅ 2026-07-18

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

> **Phase A COMPLETE ✅ (2026-07-18).** A.1–A.8 all landed; the Phase-A gate
> (`tests/test_phase_a_e2e.py`) is green and the full suite is **1202 passed**. The Mission +
> Persistent-Worker foundation (Mission Manager, Configuration Manager, Schedule table, Worker
> framework, Templates, priority arbitration, API + Operations Dashboard) is in place and
> exercised end-to-end. **Next:** open **Phase B — Engineering Intelligence** (repository
> ingestion → code understanding → architecture graph), building missions/workers on this
> foundation per the roadmap.
