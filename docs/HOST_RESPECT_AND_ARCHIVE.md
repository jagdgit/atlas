# Host Respect & Archive Learning

> **Audience:** operators and maintainers  
> **Status:** implemented (2026-07-26) — **reactive** Host Guard layer  
> **Policy:** *slow but reliable* — accept work, queue/defer under pressure, never drop jobs to protect the host  
> **Platform principle & target architecture:** [`RESOURCE_OS.md`](RESOURCE_OS.md) (**locked**; architecture frozen)  
> **Execute next:** [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md)  
> **Related:** [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md), [`STAGE_3_2_PLAN.md`](STAGE_3_2_PLAN.md) (detect→slow), Phase A workers / Phase D arbiter

This document describes **what is shipped today**: keeping Atlas from overwhelming a 16 GB (or similar) host, plus the Archive / Owner Knowledge path for years-of-work dumps.

**Elevate the policy to a platform principle** (see Resource OS):

> The host computer is Atlas's first dependency. Completing work more slowly is always preferable to destabilizing the host.

```text
Shipped (reactive):     Host → Host Guard → Mission Arbiter → Workers
Target  (proactive):    Goal → Planner → Resource Planner → Queue → Host Guard → Arbiter → Worker
```

Host Guard answers *“Can I admit another tick?”*  
Resource Planner (target) answers *“What will this cost, and what is a safe plan?”* before spawning work.

---

## 1. Problem we solved

| Symptom | Root cause |
|---------|------------|
| Ops showed **~25 workers** while `.env` said `MAX_WORKER_THREADS=4` | Env cap only limited **research/I/O thread pools**, not Persistent Mission Workers |
| Host froze / thrashing under Atlas load | Many always-on workers (Programs + leftover `hello_watcher`) could tick without a **global tick ceiling** or **host RAM gate** |
| Large USB archives needed learning | Engineering ingest is for single repos; years of mixed files belong on **Owner Knowledge / Archive** with progress + resume |

**Design intent (locked):** Atlas may be slow. Work must be **accepted**, **kept durable**, and **executed when capacity allows** so the job finishes without taking down the machine. **Never optimize for maximum host utilization.**

---

## 2. Architecture (high level)

### 2.1 Shipped execution path

```text
Operator / UI / API
        │
        ├─ Archive ingest ──► mission + owner_knowledge worker
        │                         │
        │                         ├─ free archive slot + host OK → RUNNING
        │                         └─ else → PAUSED (queued_for_capacity)
        │
        └─ Schedules fire worker_tick
                  │
                  ▼
           HostGuard.can_run_tick()     ← RAM reserve, CPU/thermal pressure
                  │
                  ▼
           MissionArbiter.try_admit()   ← global tick slots + per-mission caps
                  │
                  ▼
           PersistentWorker.do_tick()   ← bounded work (e.g. files_per_tick)
                  │
                  ▼
           checkpoint saved → next schedule (or HostGuard resumes queued)
```

**Never fail for capacity.** Under pressure Atlas returns `skipped: host_pressure` / `budget` and leaves the schedule enabled (or keeps the worker paused in the capacity queue until HostGuard resumes it).

### 2.2 Target path (Resource OS — not fully shipped)

```text
Goal → Planner → Resource Planner → Mission Queue → Host Guard → Arbiter → Worker
```

See [`RESOURCE_OS.md`](RESOURCE_OS.md) for Resource Profiles, Work Admission Policy (*Can?* ∧ *Should now?*), first-class queue states, cost estimates before start, and dynamic budgets.

---

## 3. Host Guard (slow-but-reliable)

### 3.1 Service

| Item | Value |
|------|--------|
| Module | `atlas/core/resources/host_guard.py` |
| Class | `HostGuardService` |
| Version | `hg.1` |
| Container | `host_guard` |
| Schedule | `host_guard_tick` every **60s** (seeded once at boot) |

### 3.2 Responsibilities

1. **`can_run_tick()`** — before a Persistent Worker tick: ask Resource Manager if the host is safe.
2. **`should_queue_archive_start()`** — if archive slots are full, new archive jobs are accepted but paused.
3. **`tick()` / `host_guard_tick`** — when safe, resume the oldest worker with `metadata.queued_for_capacity=true` (one per guard tick — gentle ramp).
4. **`status()`** — operator snapshot for Ops / Archive / API.

### 3.3 Resource Manager gates

Extended in `atlas/core/resources/manager.py`:

| Method | Purpose |
|--------|---------|
| `can_admit_tick(expected_ram_mb, reserve_mb)` | Defer when available RAM &lt; reserve, or projected tick RAM won’t fit above reserve, or CPU/RAM/thermal **pressure** |
| `host_guard_status(...)` | Ops-facing posture (throttled?, would admit?, snapshot) |

Pressure thresholds (configurable):

- `ram_used_high` (default **0.85**)
- `load_pressure_high` (default **0.90**)
- thermal hold with hysteresis (existing Stage 3.2c behaviour)

### 3.4 Mission Arbiter — global tick slots

Boot wiring in `atlas/kernel/bootstrap.py`:

```text
MissionArbiter(global_max_concurrent = max_concurrent_ticks or max_worker_threads)
```

So at most **N** Persistent Worker ticks run at once across all missions (default **N = 4**). Excess ticks are deferred with anti-starvation aging (existing arbiter behaviour) — not dropped.

### 3.5 Worker Manager admission

In `atlas/workers/manager.py` `worker_tick`:

1. HostGuard `can_run_tick` → if denied → `skipped: host_pressure` (event `WorkerDeferred`)
2. Arbiter `try_admit` → if denied → `skipped: budget` (event `WorkerThrottled`)
3. Else run `do_tick`, checkpoint, release slot

Default demand when mission has no budget:

- `max_concurrent_tasks = 1` (one tick per mission at a time)
- `ram_mb = tick_ram_mb` (default **512**)

### 3.6 Queued worker lifecycle

| Step | Behaviour |
|------|-----------|
| Create with `autostart=False` | Status **paused**, schedule **registered but disabled**, `metadata.queued_for_capacity=true` |
| HostGuard resume | `WorkerManager.resume` enables schedule, clears queue metadata |
| Operator pause later | Queue flag already cleared → HostGuard will **not** auto-resume operator pauses |

`create_worker` always registers a schedule so a queued worker can be resumed later (`atlas/workers/manager.py`).

---

## 4. Configuration & environment

### 4.1 Defaults (`config/defaults.yaml` → `resources`)

| Key | Default | Meaning |
|-----|---------|---------|
| `profile` | `balanced` | conservative \| balanced \| maximum \| overnight |
| `max_worker_threads` | `4` | Research/I/O pool ceiling |
| `max_concurrent_ticks` | `0` | `0` ⇒ same as `max_worker_threads` (Persistent Worker tick slots) |
| `max_archive_workers` | `1` | Parallel **running** Owner Knowledge archive jobs |
| `host_ram_reserve_mb` | `2048` | Keep free for OS / desktop / Ollama |
| `tick_ram_mb` | `512` | Default projected RAM for one worker tick |
| `ram_used_high` | `0.85` | Defer when used fraction ≥ this |
| `load_pressure_high` | `0.90` | Defer when load/cpu ≥ this |

Also still in force: download/reader/OCR/extract pool caps, LLM `max_concurrency`, task cost budgets (Stage 3.2d).

### 4.2 Env overrides (`.env` / `.env.example`)

```bash
ATLAS_RESOURCES_PROFILE=balanced
ATLAS_RESOURCES_MAX_WORKER_THREADS=4
ATLAS_RESOURCES_MAX_CONCURRENT_TICKS=4
ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS=1
ATLAS_RESOURCES_HOST_RAM_RESERVE_MB=2048
ATLAS_RESOURCES_TICK_RAM_MB=512
ATLAS_RESOURCES_RAM_USED_HIGH=0.85
ATLAS_RESOURCES_LOAD_PRESSURE_HIGH=0.90
```

**Important:** `MAX_WORKER_THREADS` alone does **not** limit the Ops “workers” count (running Persistent Workers). Use **`MAX_CONCURRENT_TICKS`** for simultaneous tick execution, and stop unused missions (e.g. leftover `hello_watcher`) to reduce schedule noise.

Config model: `atlas/config/manager.py` → `ResourcesConfig`.

---

## 5. Archive learning (years of work)

### 5.1 Service

| Item | Value |
|------|--------|
| Module | `atlas/missions/archive.py` |
| Class | `ArchiveIngestService` |
| Version | `archive.2` |
| Container | `archive_ingest` |
| Template | `owner_knowledge` |
| Program | `personal_intelligence` |

### 5.2 Start modes

| Mode | When | Behaviour |
|------|------|-----------|
| `parallel_mission` | Default (`parallel=true`) + capacity free | New mission + running `owner_knowledge` worker |
| `queued_for_capacity` | Archive slots full **or** host not safe | Same mission/worker created **paused**; HostGuard starts it later |
| `shared_mission` | `parallel=false` | Root appended via Program Materials to shared Personal Observer (sequential roots on one worker) |

Each parallel job gets:

- Own mission + worker (independent checkpoints / progress bars)
- `files_per_tick` (default **40**)
- Optional owner note + period → Personal timeline via `note_project_period`
- Budget `{ max_concurrent_tasks: 1, ram_mb: 512 }`

### 5.3 Owner Knowledge worker robustness

`atlas/workers/owner_knowledge.py` (VERSION 2 family):

- Document/conversation roots: **per-file** `files_done` checkpoint; batched `files_per_tick`
- Progress in checkpoint + journal (`progress name:done/total`)
- Light signatures (size+mtime) for completed roots; skip unchanged complete roots
- Do **not** Engineering-ingest a whole multi‑GB personal tree — use Archive / `archive_roots`

### 5.4 Operator practice for USB / One Touch

1. Prefer **selective subfolders** (Certificates, Design, code projects).
2. Skip photo dumps / marriage pics / bulk zips unless intentional.
3. Keep the disk **mounted** until progress shows complete.
4. Start **one** archive at a time by default; further starts queue until the first finishes or is stopped.
5. After power loss / reboot, document roots **resume mid-archive** from checkpoints.

---

## 6. Worker progress enrichment

`WorkerManager` (`atlas/workers/manager.py`):

| Method | Purpose |
|--------|---------|
| `checkpoint_state(worker_id)` | Load durable tick checkpoint |
| `enrich_worker(worker)` | Attach `checkpoint.roots[]` with done/total/complete/last_file |
| `list_workers_enriched(...)` | List + enrich |

API:

- `GET /v1/workers` — enriched by default (`include_checkpoint=true`)
- `GET /v1/workers/{id}` — enriched
- `GET /v1/missions/{id}` — workers enriched for Mission UI cards

---

## 7. HTTP API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/resources/guard` | Host Guard posture (slots, reserve, deferred, queued) |
| `GET` | `/v1/ops` | Ops snapshot including `host_guard` |
| `GET` | `/v1/archive/status` | Owner Knowledge workers + progress + host_guard summary |
| `POST` | `/v1/archive/ingest` | Start/queue archive learning |
| `GET` | `/v1/workers` | Workers (+ checkpoint progress) |
| `POST` | `/v1/workers/{id}/{pause\|resume\|stop}` | Operator control |

### 7.1 `POST /v1/archive/ingest` body

Schema: `ArchiveIngestRequest` in `atlas/api/schemas.py`

```json
{
  "path": "/media/.../Certificates",
  "kind": "document",
  "domain": "personal",
  "parallel": true,
  "title": null,
  "note": "work 2022–March 2025",
  "period_start": "2022",
  "period_end": "2025-03",
  "files_per_tick": 40,
  "process_now": false
}
```

`kind`: `document` | `code` | `conversation`

Response highlights: `ok`, `mode`, `queued`, `queue_reason`, `mission_id`, `worker_ids`, `note`.

---

## 8. Console UI

Cache bust: `styles.css` / `app.js` query `?v=dash9` (bump on further UI changes).

### 8.1 Archive view

- Nav: **Archive**
- Form: path, note, kind, period, **parallel job** checkbox, Start ingest
- Status line: idle / busy / ok / fail / **queued until capacity**
- List: progress bars (done/total), Pause / Resume / Stop, Open mission
- Auto-refresh ~5s while on the view
- Host guard summary under the list

### 8.2 Overview (Ops)

Extra cards:

- **host guard** — ok / throttled / deferring  
- **tick slots** — in-flight / max  
- **capacity queue** — waiting workers + deferred tick count  
- **archive slots** — running / max  

### 8.3 Missions

Worker cards show progress labels and root progress bars when checkpoint data is present.

---

## 9. Bootstrap wiring (checklist)

In `atlas/kernel/bootstrap.py`:

1. `ResourceManager` constructed with reserve + pressure thresholds from config  
2. `MissionArbiter(global_max_concurrent=tick_slots)`  
3. `WorkerManager(..., default_tick_ram_mb=...)`  
4. `HostGuardService` → `worker_manager._host_guard = host_guard`  
5. Handlers: `worker_tick`, `host_guard_tick`  
6. Schedule `host_guard_tick` if not already present  
7. `ArchiveIngestService(..., host_guard=host_guard)` registered as `archive_ingest`  
8. Container: `host_guard`, `archive_ingest`, `workers`, …

---

## 10. Monitoring & what “healthy under load” looks like

| Signal | Healthy | Concern |
|--------|---------|---------|
| Ops **host guard** | `ok` | `deferring` / `throttled` for long stretches + host RAM climbing |
| **tick slots** | ≤ max (e.g. `2/4`) | Always saturated **and** host RAM &gt; ~85% |
| **capacity queue** | 0–few | Growing without archive completions |
| Host RAM (OS) | Reserve ~2 GiB free | Available RAM near 0 → machine freeze risk |
| Archive progress | done/total advancing | Stuck + disk unmounted / path gone |

Commands / endpoints after restart:

```bash
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/v1/resources/guard
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/v1/ops
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/v1/archive/status
```

---

## 11. Operator playbook (keep the host alive)

1. **Restart** Atlas after deploying these changes (`atlas serve`).  
2. Hard-refresh the console.  
3. **Stop leftover demo workers** (especially running `hello_watcher` missions) — they inflate schedule noise even though ticks are capped.  
4. Pause Market Program missions when not needed (many short-interval workers).  
5. Archive: one selective folder at a time; let HostGuard queue extras.  
6. Prefer `ATLAS_RESOURCES_PROFILE=conservative` on a shared laptop if the desktop still feels heavy.  
7. Never point Engineering ingest at a whole multi‑GB personal tree.

---

## 12. Tests

| File | Covers |
|------|--------|
| `tests/test_host_guard.py` | Defer/admit, archive slots, resume queued worker, RAM reserve |
| `tests/test_archive_ingest.py` | Parallel start, shared materials path, status filter, enrich progress |
| `tests/test_owner_knowledge_worker.py` | Batched ingest, reboot resume checkpoints |
| `tests/test_arbiter.py` | Global concurrent cap, ram_mb deferral |
| `tests/test_resources_32c.py` | Resource Manager profiles / pools |

---

## 13. File map

| Path | Role |
|------|------|
| `atlas/core/resources/host_guard.py` | HostGuardService |
| `atlas/core/resources/manager.py` | `can_admit_tick`, `host_guard_status`, reserve |
| `atlas/core/resources/monitor.py` | CPU/RAM/thermal snapshot |
| `atlas/core/resources/arbiter.py` | Global + per-mission admission |
| `atlas/workers/manager.py` | Tick gate, enrich, create paused+scheduled, resume clears queue flag |
| `atlas/workers/owner_knowledge.py` | Archive root processing + checkpoints |
| `atlas/missions/archive.py` | ArchiveIngestService |
| `atlas/missions/templates/service.py` | Pass queue metadata / autostart into workers |
| `atlas/missions/materials.py` | Shared path share (Personal + Engineering once) |
| `atlas/repositories/worker_repo.py` | `update_metadata` |
| `atlas/ops/dashboard.py` | `host_guard` section on `/v1/ops` |
| `atlas/api/routes.py` | Archive + guard + enriched workers/missions |
| `atlas/api/schemas.py` | `ArchiveIngestRequest` |
| `atlas/config/manager.py` / `config/defaults.yaml` / `.env.example` | Caps |
| `atlas/kernel/bootstrap.py` | Wiring |
| `atlas/web/static/{index.html,app.js,styles.css}` | Archive + Ops UI |
| `docs/MISSIONS_OPERATOR_GUIDE.md` | Short operator pointer |
| `docs/HOST_RESPECT_AND_ARCHIVE.md` | This document (shipped) |
| `docs/RESOURCE_OS.md` | Platform principle + Resource OS target |

---

## 14. Explicit non-goals (preserved product rules)

- Atlas **never** posts to LinkedIn or **applies** to jobs (suggestions / recommend only).  
- Personal inferred facts stay Confirm/Reject (P9).  
- Host Guard does **not** kill running ticks mid-flight (no preemption) — it prevents *new* admissions until safe.  
- Power/battery hard-stop remains Stage 4 debt (monitor notes “power not monitored”).  
- **Do not** chase maximum hardware utilization — host stability ≻ throughput ([`RESOURCE_OS.md`](RESOURCE_OS.md) RO1/RO2).

---

## 15. Change log

| Date | Change |
|------|--------|
| 2026-07-26 | Archive UI + parallel ingest API; Owner Knowledge progress enrichment |
| 2026-07-26 | HostGuard + global tick slots + RAM reserve + archive capacity queue; Ops cards; `/v1/resources/guard` |
| 2026-07-26 | Aligned with Resource OS principle doc — reactive vs proactive; pointer to target Planner→Queue stack |

---

*End of document.*
