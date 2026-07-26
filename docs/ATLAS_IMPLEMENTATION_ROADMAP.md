# Atlas Implementation Roadmap

> **Audience:** implementers and operators  
> **Status:** **FINALIZED execution plan** · architecture frozen · implement only  
> **Date:** 2026-07-26  
> **Architecture:** frozen — do not invent new top-level OS boxes  
> **Parents:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md), [`RESOURCE_OS.md`](RESOURCE_OS.md), [`RESOURCE_SCHEDULING_AND_OPS_LOCK.md`](RESOURCE_SCHEDULING_AND_OPS_LOCK.md)  
> **Shipped host path:** [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md)

The design set is stable. Remaining work is **ship IR-* items in order**, validate on the host, and refine — not rewrite the conceptual model.

**Stop creating new architectural documents.** Prefer tickets / OI items / PRs against this list.

---

## Design set (read as one)

| Doc | Role | Assessment |
|-----|------|------------|
| [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) | What Atlas is | Excellent — settled |
| [`RESOURCE_OS.md`](RESOURCE_OS.md) | Principles | Excellent — settled |
| [`RESOURCE_SCHEDULING_AND_OPS_LOCK.md`](RESOURCE_SCHEDULING_AND_OPS_LOCK.md) | How scheduling / admission / Ops work | Locked — implement |
| **This file** | What gets built next | Finalized |

---

## Defining principles (do not reopen)

1. **Host stability ≻ throughput** — never knowingly jeopardize the host.  
2. **Never lose accepted work** — durable, checkpointable, resumable.  
3. **Planning OS ≠ Resource OS** — *What should we do?* vs *Can we safely do it?*  
4. **Admission Contract before Mission Queue** — only accepted work enters the queue.  
5. **One Mission Queue** + service classes — not three physical queues.  
6. **Host Guard = machine protection only** — not the scheduler.  
7. **No new top-level OS** unless solar-plant test *and* cannot live in Resource / Planning / Mission OS.  
8. **Do not raise `MAX_CONCURRENT_TICKS`** until Ops metrics justify it (default stays **2**).

Layering:

```text
Thinking → Planning → Admission → Resource Management → Execution → Learning → Governance
```

Pipeline (authority: scheduling lock):

```text
Planner → Admission Contract → Mission Queue
  → Candidate Selector → Reservation Manager → Host Guard → Dispatcher
  → Worker → Checkpoint → Release
```

---

## Finalized build order

Ship in **phases**. Do not skip Phase 0/1 visibility before building a smarter scheduler — operators need to see starvation and tick duration to validate later work.

### Phase 0 — Visibility (unblock diagnosis) ✅

| ID | Item | Outcome | Depends |
|----|------|---------|---------|
| **IR-OPS1** | **Ops worker state breakdown** | Replace bare “workers: N” with: Running ticks · Holding Reservation · Ready · Waiting Host · Waiting Schedule · Waiting Dependency · Sleeping · Paused · Starved · Slow · Completed. Per-worker timings + wait reason + starvation age on `/v1/ops` → `worker_states` | — ✅ |

**Done when:** Ops answers “why isn’t Market progressing?” without reading logs.

---

### Phase 1 — Admit work correctly (proactive gate)

| ID | Item | Outcome | Depends |
|----|------|---------|---------|
| **IR-RO1** | **Resource Planner v1 + Admission Contract** | Explicit result: `Accepted` / `Deferred` / `Rejected` / `Needs Confirmation`. Archive estimate + confirm. APIs: `/v1/archive/estimate`, confirm on `/v1/archive/ingest` | Host Guard ✅ · **shipped** |
| **IR-RO3** | **Template Resource Profiles + service class** | Builtins declare REALTIME/INTERACTIVE/NORMAL/BATCH + latency/deadline/CPU/RAM/Disk IO/Storage Growth; seeded in `success_criteria.resources`; applied at instantiate | — ✅ **shipped** |

**Done when:** heavy Archive cannot enter the queue without a contract; templates declare REALTIME/… and resource shape.

---

### Phase 2 — Queue + select next work

| ID | Item | Outcome | Depends |
|----|------|---------|---------|
| **IR-RO2** | **Mission Queue states + owner** | First-class states incl. `WAITING_DEPENDENCY`; owner fields; `GET /v1/resources/queue` + Ops | IR-OPS1 · IR-RO1 · **shipped** |
| **IR-RO5** | **Resource Scheduler v1** | Candidate Selector (class → deadline → priority → aging). **Reserve ≥1 tick for REALTIME** when `MAX_CONCURRENT_TICKS≥2`. APIs: `GET /v1/resources/scheduler` | IR-RO2 · IR-RO3 · **shipped** |

**Done when:** BATCH cannot occupy both tick slots while REALTIME is READY; Market deadlines influence selection.

---

### Phase 3 — Account resources + storage decisions

| ID | Item | Outcome | Depends |
|----|------|---------|---------|
| **IR-RO7** | **Resource reservations / leases** | Acquire → renew → release; Disk IO **and** Storage Growth; vanished lease expiry; Ops Holding Reservation. APIs: `/v1/resources/reservations` | Checkpoints ✅ · IR-RO5 · **shipped** |
| **IR-RO6** | **Storage pressure** | Warn → stop new high-growth work at high watermark. Consumed by ReservationManager + Resource Planner | IR-RO5 · **shipped** |

**Done when:** embeddings cannot silently fill disk; reservations explain “why not started.”

---

### Phase 4 — Budgets, profiles, timing policy ✅

| ID | Item | Outcome | Depends |
|----|------|---------|---------|
| **IR-RO4** | **Dynamic budgets** | Pressure ↓ effective ticks/pools; idle ↑ **within** hard env ceilings + hysteresis | IR-RO3, IR-RO5 · **shipped** |
| **IR-RO8** | **Machine profile detect** | Doctor/boot suggests conservative / balanced / maximum; preferred ticks 2 / 3 / 4 under hard ceiling | — · **shipped** |
| **IR-RO10** | **Should run now?** | Schedule windows / idle-only classes (Can? ∧ Should now?) — feeds Admission Deferred | IR-RO1, IR-RO2 · **shipped** |

**Done when:** operators pick a profile instead of editing thread knobs; quiet-hours deferrals are explicit contracts.

APIs: `GET /v1/resources/budgets`, `/v1/resources/machine-profile`, `/v1/resources/work-admission`. Opt-in BATCH window: `ATLAS_RESOURCES_ENFORCE_BATCH_WINDOW=true`.

---

### Phase 5 — Mission structure & later Host ✅

| ID | Item | Outcome |
|----|------|---------|
| **IR-M1** | **Mission DAG / child missions** | Prefer Extract → Verify → Summarize as linked children over monoliths · **shipped** |
| **IR-M2** | **Mission aging** | Soft boost for long-WAITING (anti-starvation) · **shipped** |
| **IR-M3** | **Confidence-aware research time** | Low-confidence research may deserve more scheduler attention · **shipped** |
| **IR-RO9** | **Power / deeper thermals** | Stage 4; honest “not monitored” until real · **shipped** (probe + honesty) |

APIs: `POST /v1/missions/{id}/children`, `GET /v1/missions/{id}/dag`, `POST /v1/missions/{id}/research-confidence`, `GET /v1/resources/power`. Optional NUT: `ATLAS_RESOURCES_UPS_NAME`.

---

## Explicit object: Admission Contract

```text
AdmissionRequest
  program, mission_template, intent, estimated_cost?, urgency?

AdmissionContract
  status: accepted | deferred | rejected | needs_confirmation
  run_at?: datetime          # when deferred
  estimate?: { time, storage_growth, ram, risk, … }
  reason?: string
  confirmation_token?: …     # when needs_confirmation
```

Only **accepted** (including accepted-after-confirm) work is enqueued. Planning OS calls Resource Planner; it does **not** implement host math itself.

---

## Resource Planner estimate dimensions

| Dimension | Use |
|-----------|-----|
| Time | ETA / “run tonight” |
| Energy | Prefer idle/night on laptops |
| Risk | Host / data / policy |
| Benefit / knowledge gain | Expected value vs cost |
| Storage growth | Durable bytes (embeddings, extracts) |
| Disk IO | Contention during scans |
| Checkpointability | Prefer yielding work under pressure |

---

## Already shipped (do not re-litigate)

| Item | Doc |
|------|-----|
| Host Guard + tick slots + RAM reserve | `HOST_RESPECT_AND_ARCHIVE.md` |
| Archive ingest + capacity queue + progress | same |
| Mission Arbiter global / per-mission caps | Phase D |
| Resource Manager pools + pressure → slow | Stage 3.2 |
| Planning OS (what next) | PA.1 |
| Assess Resources stage in cognitive lifecycle | philosophy |

---

## Hard separation

| OS | Asks | Must not absorb |
|----|------|-----------------|
| **Planning OS** | What should we do? | Host RAM math, tick leases, disk watermarks, admission accounting |
| **Resource OS** | Can we safely? When? Admission Contract? | Domain strategy, “what knowledge to seek” |

If a feature answers both, **split the PR**.

---

## Scheduler internals (implement as modules, one façade)

Operator-facing name remains **Resource Scheduler**. Internally:

| Module | Responsibility |
|--------|----------------|
| **Candidate Selector** | Order READY by class, deadline, priority, aging, checkpoint fit |
| **Reservation Manager** | Fit / acquire / release reservations |
| **Host Guard** | Safety veto only |
| **Dispatcher** | Start tick / hand to worker |

Do not build one god-object.

---

## Environment lock (until metrics say otherwise)

| Setting | Default |
|---------|---------|
| `MAX_CONCURRENT_TICKS` | **2** |
| `LLM_MAX_CONCURRENCY` | **1** |
| `MAX_ARCHIVE_WORKERS` | **1** |
| Profile | **conservative** |

After ~1 month continuous run, measure: avg tick duration, queue depth, starvation events, CPU util, RAM pressure — then consider balanced/maximum via **IR-RO8**, not ad-hoc env edits.

---

## Validation checklist (each IR item)

- [ ] Host remains interactive under load  
- [ ] Accepted work survives reboot / pause / resume  
- [ ] Ops or API explains *why not running* (incl. Holding Reservation / Admission Deferred)  
- [ ] Hard `.env` ceilings never exceeded  
- [ ] Solar-plant test still holds (no Market-only coupling in Resource OS)  
- [ ] No new top-level OS name  
- [ ] Admission Contract logged for every heavy start  

---

## Near-term sprint sequence (copy into tickets)

1. **IR-OPS1** — Ops state breakdown + tick timings + Holding Reservation  
2. **IR-RO1** — Resource Planner v1 + Admission Contract  
3. **IR-RO3** — Profiles + service class + deadline policy on templates  
4. **IR-RO2** — Mission Queue states + owner fields  
5. **IR-RO5** — Scheduler (Candidate Selector + REALTIME reserve + deadlines)  
6. **IR-RO7** — Reservations / leases (Disk IO + Storage Growth)  
7. **IR-RO6** — Storage pressure (consumed by scheduler)  
8. **IR-RO4 / IR-RO8 / IR-RO10** — budgets, machine profile, should-run-now ✅  
9. **IR-M1 → IR-M3**, then **IR-RO9** ✅  
10. **OC-1 → OC-3** — Operator Communication (email reports → console inbox → Telegram) — see [`OPERATOR_COMMUNICATION.md`](OPERATOR_COMMUNICATION.md)  

---

## Related docs

| Doc | Role |
|-----|------|
| `RESOURCE_OS.md` | Locked principles |
| `RESOURCE_SCHEDULING_AND_OPS_LOCK.md` | Scheduling / admission / Ops design authority |
| `HOST_RESPECT_AND_ARCHIVE.md` | Shipped Host Guard + Archive |
| `ATLAS_PLATFORM_ARCHITECTURE.md` | Settled platform map |
| `ATLAS_MISSION_PHILOSOPHY.md` | Cognitive lifecycle |
| `OPEN_ITEMS.md` | Cross-cutting OIs (link IR-* as needed) |
| `.env` / `.env.example` | Hard host ceilings |

---

*End of finalized roadmap — implement IR-*; do not open another architecture redesign.*
