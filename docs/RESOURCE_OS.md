# Resource OS — Host-Aware Platform Layer

> **Audience:** architects and operators  
> **Status:** **principle locked** · **architecture frozen** · **partially shipped** (Host Guard) · gaps → [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md)  
> **Date:** 2026-07-26  
> **Parent:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)  
> **Shipped detail:** [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md)  
> **Mission cognition:** [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md)

This document elevates **host respect** from an Archive/throttling feature into a **platform OS layer**, aligned with Knowledge OS, Experience OS, Memory OS, and Planning OS.

**Architecture frozen — implement only.** Execution plan: [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) (IR-RO* / IR-OPS* / IR-M*).

**Scheduling, admission & Ops (locked):** [`RESOURCE_SCHEDULING_AND_OPS_LOCK.md`](RESOURCE_SCHEDULING_AND_OPS_LOCK.md) — one Mission Queue · service classes · **Admission Contracts** · scheduler internals (Candidate Selector → Reservation Manager → Host Guard → Dispatcher) · Ops state breakdown. Supersedes any “three physical queues” sketch.

---

## 0. Locked separation — Planning OS vs Resource OS

| OS | Question | Owns |
|----|----------|------|
| **Planning OS** | *What should we do?* | Goals, gather gaps, alternatives, domain next-step |
| **Resource OS** | *Can we safely do it?* | Admission Contracts, estimates, queue, reservations, Host Guard, budgets |

Planning OS **calls** Resource Planner and receives an **Admission Contract** (`Accepted` / `Deferred` / `Rejected` / `Needs Confirmation`). Only accepted work enters the Mission Queue. Planning must **not absorb** Resource Planner. If a change answers both questions, split it.

Platform layering:

```text
Thinking → Planning → Resource Management → Execution → Learning → Governance
```

---

## 1. Locked platform principle

**The host computer is Atlas's first dependency.**

Atlas must never knowingly jeopardize the host in pursuit of completing work. Completing work more slowly is always preferable to destabilizing the host.

**Host stability always takes precedence over throughput.** — defining principle; do not reopen.

Formal design goal:

> Atlas is a **host-aware operating system for long-running intelligence**. Every accepted task is durable, schedulable, checkpointable, resumable, and resource-aware. **The host's stability always takes precedence over throughput.**

### Optimization target (explicit)

| Aim | Atlas? |
|-----|--------|
| Maximize hardware utilization (90–100%) | ❌ No |
| Never lose accepted work | ✅ |
| Never destabilize the host | ✅ |
| Eventually complete every accepted task | ✅ |
| Prefer reliability, resumability, long-running intelligence | ✅ |

This is a different objective from typical distributed “burn the cluster” systems. Atlas is a **considerate background OS** on a personal or single host (and later clusters), not a batch farm.

---

## 2. Reactive vs proactive (the biggest gap)

### What we have today (reactive)

```text
Host
  ↓
Host Guard          ← “Can I admit another tick *right now*?”
  ↓
Mission Arbiter     ← who gets the scarce slot?
  ↓
Workers
```

This **protects execution**. It is necessary and shipped (`HostGuardService`, Resource Manager pressure, global tick slots). See [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md).

### What we need (proactive)

```text
Goal
  ↓
Planner                 (Planning OS — what work?)
  ↓
Resource Planner        (Resource OS — what will it cost? safe plan?)
  ↓
Mission Queue           (READY / WAITING_* / RUNNING / …)
  ↓
Host Guard              (admit this tick?)
  ↓
Mission Arbiter         (who among ready work?)
  ↓
Worker
```

**Host Guard is reactive. Resource Planner is proactive.**

Example — “Learn 500 YouTube videos”:

| Today (risk) | Target |
|--------------|--------|
| May spawn 500 missions; Host Guard throttles for days | Estimate work → RAM/CPU/storage → compare to host → **safe plan** |
| Operator sees mysterious slowness | “Accepted. ETA ~6 days. Max concurrent learners: 2. Remainder queued.” |

---

## 3. Resource OS — the dedicated component

If one new platform box is added, it is **Resource OS** (solar-plant test: every Program needs host-safe execution).

```text
Resource OS
├── Host Monitor          (CPU / RAM / disk / thermal / power — honest about gaps)
├── Machine Profile       (laptop → conservative; desktop → balanced; server → maximum; cluster → distributed)
├── Resource Planner      (estimate cost *before* start; propose concurrency & ETA)
├── Work Admission Policy (Can it run? + Should it run *now*?)
├── Mission Queue         (first-class states — why is this not running?)
├── Budget Manager        (dynamic caps — pressure ↓ workers; idle ↑ within hard ceilings)
├── Host Guard            (tick / lease admission — reactive)
├── Resource Scheduler    (what should run *next* among queued work?)
├── Checkpoint Manager    (bounded units of work)
├── Recovery Manager      (resume after pause / reboot / power loss)
├── Power / Thermals      (Stage 4 deepen — already partially monitored)
└── Storage Manager       (existing storage quotas — wire into estimates)
```

**Relationship to existing code:**

| Piece | Today | Resource OS role |
|-------|-------|------------------|
| `ResourceManager` + `read_snapshot` | ✅ | Host Monitor + pool advice |
| `HostGuardService` | ✅ | Host Guard (+ seed of Resource Scheduler) |
| `MissionArbiter` | ✅ | Cross-mission slot arbitration |
| `CheckpointStore` | ✅ | Checkpoint Manager (worker-owned today) |
| Planning OS (`PlanningService`) | ✅ | Planner — must call Resource Planner before heavy start |
| Mission Queue as first-class states | ✅ | `metadata.queue` + `/v1/resources/queue` + Ops |
| Resource Planner (ETA / estimate) | ❌ target | New |
| Template Resource Profiles | ❌ partial (budgets) | New schema on templates |
| Machine Profile auto-classify | ❌ target | Derive defaults; rare manual thread edits |
| Dynamic budget adaptation | ❌ partial (pressure → pool size 1) | Continuous adapt within hard env ceilings |
| Power Manager | ❌ Stage 4 | Honest “not monitored” today |

---

## 4. Work Admission Policy

Admission has **two questions** (both required):

| Question | Meaning | Example |
|----------|---------|---------|
| **Can it run?** | Host + caps allow this class of work | Enough RAM reserve; under tick ceiling |
| **Should it run now?** | Policy / courtesy / schedule | Large archive → after 23:00; model eval → only when idle; paper trading → start immediately |

```text
Paper trading     → Can? YES  Should now? YES   → start
Large archive     → Can? YES  Should now? NO    → WAITING_SCHEDULE (e.g. 23:00)
Model evaluation  → Can? YES  Should now? IDLE  → WAITING_HOST until idle
```

Today we mostly answer **Can?** (Host Guard + arbiter). **Should now?** is the Work Admission Policy target.

---

## 5. Mission Resource Profiles (every template)

Today missions have priority + optional `budget` (`max_concurrent_tasks`, `ram_mb`, …). Elevate to a declared **Resource Profile** on every template:

| Dimension | Values (example scale) |
|-----------|------------------------|
| CPU | very_low → low → medium → high |
| Memory | very_low → low → medium → high |
| Disk | none → low → medium → high |
| Network | none → low → medium → high |
| GPU | none → preferred → required |
| Temperature sensitivity | low → high |
| Interruptibility | no \| yes \| checkpoint_every_chunk |
| Latency importance | background \| normal \| interactive |

### Example profiles

**Owner Knowledge**

| | |
|--|--|
| CPU | Low |
| RAM | Medium |
| Disk | High |
| Network | None |
| Interruptible | Yes (per file / batch) |

**Research**

| | |
|--|--|
| CPU | Medium |
| RAM | High |
| Network | High |
| Interruptible | Yes |

**LLM embedding**

| | |
|--|--|
| CPU | High |
| RAM | High |
| GPU | Preferred |
| Interruptible | Checkpoint every chunk |

**Paper Trading**

| | |
|--|--|
| CPU | Very low |
| RAM | Very low |
| Latency | Important |
| Interruptible | Tick-bounded |

The Resource Planner + Scheduler use these profiles to choose **what runs next** without hand-tuning thread counts.

---

## 6. Machine profiles (derive defaults)

Rather than dozens of manual env knobs, classify the machine once:

```text
Laptop   → Conservative
Desktop  → Balanced
Server   → Maximum
Cluster  → Distributed   (future)
```

Operator still owns **hard ceilings** (never exceed `max_worker_threads` / tick slots / RAM reserve). Profiles choose *preferred* aggressiveness inside those ceilings — same rule as Stage 3.2c overnight bonus.

---

## 7. Mission Queue — first-class states

Elevate “queue” from admission metadata to a platform component with explainable states:

| State | Meaning |
|-------|---------|
| `READY` | Admitted; waiting for a tick slot / lease |
| `WAITING_HOST` | Deferred — host pressure / reserve |
| `WAITING_NETWORK` | Needs network; offline or policy |
| `WAITING_GPU` | Needs GPU; none available |
| `WAITING_SCHEDULE` | Should-not-run-now (night window, idle-only) |
| `WAITING_OPERATOR` | Needs Confirm / approval |
| `WAITING_DEPENDENCY` | Blocked on another mission/artifact (e.g. research waiting on transcription) — **not** host pressure |
| `BLOCKED` | Hard policy / missing capability |
| `RUNNING` | Active tick or lease |
| `CHECKPOINTING` | Persisting bounded progress |
| `PAUSED` | Operator or capacity pause |
| `COMPLETE` | Finite mission done |
| `ARCHIVED` | Retained, not scheduled |

`WAITING_DEPENDENCY` vs `WAITING_HOST` matter for operators: different reasons → different actions.

**Shipped:** first-class queue states via `mission.metadata.queue` + derived classification; Ops / `GET /v1/resources/queue` (IR-RO2). Host Guard resume clears `WAITING_HOST`.

---

## 8. Estimate cost before starting (operator contract)

Heavy goals must not “just start.” Example — “Learn this 2 TB archive”:

```text
Archive accepted.
Estimated files:     2,400,000
Estimated duration:  ~16 days
Estimated storage:   ~120 GB
Estimated embeddings:~18 GB (if embed on)
Recommended profile: Balanced
Max concurrent:      1
Safe to continue?    [Y/N]
```

### 8.1 Estimate dimensions (beyond RAM/CPU)

Resource Planner should estimate **value and risk**, not only machine load:

| Dimension | Example |
|-----------|---------|
| Time | 12 hours |
| CPU / RAM / Disk / Network | Medium / … |
| Energy | Prefer overnight on laptops |
| Risk | Low / medium / high (host, data, policy) |
| Benefit / knowledge gain | High |
| Checkpointability | Yields every N files / chunks |
| Recommendation | Run tonight |

Eventually Atlas prioritizes by **expected value under host constraints**, not available memory alone (IR-RO1).

This is Planning OS + Resource Planner + Work Admission, not Host Guard alone.

**Shipped today:** accept + queue under capacity; no ETA / multi-dimension estimate gate yet.

---

## 9. Dynamic budgets

| Horizon | Behaviour |
|---------|-----------|
| Config / env | Hard ceilings (never exceed) |
| Continuous | Memory pressure → reduce effective workers; long idle → increase **within** ceilings |

Stage 3.2c already shrinks pools under pressure (never to zero). Target: same idea for **tick concurrency and archive slots**, with hysteresis, surfaced in Ops.

---

## 10. Recovery lifecycle (formal)

Long-running work must move freely without losing meaningful progress:

```text
Accept → Queue → Run → Checkpoint → Pause → Resume → Complete → Archive
```

| Stage | Requirement |
|-------|-------------|
| Accept | Durable record of the goal |
| Queue | Explainable wait state |
| Run | Bounded unit of work |
| Checkpoint | Resume point after kill / reboot |
| Pause / Resume | Operator or Host Guard |
| Complete / Archive | Finite missions end; continuous missions keep observing |

Owner Knowledge document roots already checkpoint **per file** / batch. Formalize this lifecycle for all long missions.

---

## 11. Cognitive lifecycle — resource gate

Mission philosophy loop gains a **platform gate before Execute** (does not change how a mission *thinks*; changes how Atlas *survives*):

```text
Observe
  ↓
Plan
  ↓
Assess Resources     ← Resource OS (new gate)
  ↓
Execute
  ↓
Record Why
  ↓
Evaluate
  ↓
Reflect
  ↓
Improve
```

See [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md).

---

## 12. Host Guard → Resource Scheduler (evolution)

Host Guard today asks: **Can I admit another tick?**

Next ask: **What should happen next?**

```text
Queue
  → Priority (+ mission aging for long waits)
  → Estimated RAM / CPU / duration
  → Checkpoint opportunity (prefer work that can pause safely in seconds)
  → Knowledge uncertainty / confidence (research may prefer low-confidence work)
  → Deadline / operator importance
  → Resource Profile fit
  → Best next worker
```

That is a **Resource Scheduler** sitting above Host Guard, not a replacement for it (IR-RO5).

**Checkpoint-aware preemption preference:** under rising RAM pressure, prefer pausing Mission A (safe checkpoint in ~3s) over Mission B (needs ~20 min to a safe point). Never lose work; choose the safer yield.

### 12.1 Resource leases (target)

Prefer leases over “fire and forget” runs:

```text
Acquire lease → Run bounded unit → Renew → Release
```

If power loss or `kill -9` occurs, Atlas knows which lease vanished and can recover precisely (IR-RO7).

### 12.2 Storage pressure (target)

Long-running Atlas will often become **storage-bound** before RAM-bound (embeddings, vectors, archives, text, PDFs, conversations). Mirror memory pressure:

| Watermark | Action (illustrative) |
|-----------|------------------------|
| ~80% | Compress / warn |
| ~90% | Archive cold tiers |
| ~95% | Stop new embeddings / heavy ingest |

(IR-RO6)

### 12.3 Mission DAG (target)

Prefer child missions over giant workers:

```text
Learn Repository → Extract → Verify → Summarize → Update Engineering Knowledge
```

Each child completes independently; parents wait with `WAITING_DEPENDENCY` (IR-M1).

### 12.4 Mission aging & confidence (shipped)

- **Aging:** soft priority boost for work queued for a long time (IR-M2) — same spirit as Linux CFS / arbiter starvation aging.
- **Confidence-aware:** low-confidence / high-uncertainty research may deserve more scheduler attention (IR-M3).

### 12.5 Three layers of memory protection (locked)

| Layer | Owner | Answers | Status |
|-------|--------|---------|--------|
| **1 — Admission** | Host Guard + Planner + Arbiter | *Can we start this work?* | ✅ Shipped |
| **2 — Runtime enforcement** | Runtime Watchdog + budgets + cooperative ticks | *May this work keep growing?* | ❌ Missing → **IR-RO11** |
| **3 — OS backstop** | systemd `MemoryMax` / `Restart=` | *Emergency stop if Atlas fails Layer 2* | Deploy unit; **not** primary policy |

Layer 1 alone is insufficient: an admitted tick can still grow unboundedly inside one Python process until the kernel OOM-kills Atlas. Layer 3 must remain rare.

### 12.6 Runtime Memory Enforcement (IR-RO11 — target)

```text
Mission / template profile
  → Memory budget (MB)
  → Worker tick (bounded batch)
  → Checkpoint + release + GC
  → Watchdog measures RSS vs budget + host watermarks
  → Continue | Pause + requeue (durable; never drop)
```

Reservations (IR-RO7) become **enforceable** against measured usage, not advisory. Process isolation (separate Archive vs Market processes) is a **later** hardening step after cooperative ticks exist.

---

## 13. Shipped vs target (honest scorecard)

| Capability | Status | Roadmap |
|------------|--------|---------|
| Host-first principle | ✅ Locked | — |
| Host Guard tick admission | ✅ Shipped | — |
| Global concurrent tick slots | ✅ Shipped | — |
| RAM reserve / pressure defer | ✅ Shipped | — |
| Archive capacity queue | ✅ Shipped | — |
| Checkpoint + reboot resume (Owner Knowledge docs) | ✅ Shipped | — |
| Ops / `/v1/resources/guard` visibility | ✅ Shipped | — |
| Ops worker state breakdown (+ Holding Reservation) | ✅ Shipped (IR-OPS1) | IR-OPS1 |
| Resource Planner + **Admission Contract** | ✅ Shipped (IR-RO1 v1) | IR-RO1 |
| First-class Mission Queue (+ owner + `WAITING_DEPENDENCY`) | ✅ Shipped (IR-RO2) | IR-RO2 |
| Template Resource Profiles + service class + deadlines | ✅ Shipped (IR-RO3) | IR-RO3 |
| Dynamic budgets + hysteresis | ✅ Shipped (IR-RO4) | IR-RO4 |
| Resource Scheduler (Candidate Selector + REALTIME reserve) | ✅ Shipped (IR-RO5) | IR-RO5 |
| Storage pressure (after scheduler) | ✅ Shipped (IR-RO6) | IR-RO6 |
| Resource leases (Disk IO + Storage Growth) | ✅ Shipped (IR-RO7) | IR-RO7 |
| Machine auto-profile | ✅ Shipped (IR-RO8) | IR-RO8 |
| Power Manager | ✅ Shipped (IR-RO9 honesty + probe) | IR-RO9 |
| Work Admission “should run now?” | ✅ Shipped (IR-RO10) | IR-RO10 |
| Mission DAG | ✅ Shipped (IR-M1) | IR-M1 |
| Mission wait-time aging | ✅ Shipped (IR-M2) | IR-M2 |
| Confidence-aware research attention | ✅ Shipped (IR-M3) | IR-M3 |
| **Runtime Memory Enforcement (Layer 2)** | 🟡 v0 shipped (watchdog + archive cooperative yield) | **IR-RO11** |
| systemd MemoryMax backstop (Layer 3) | ✅ Deploy artifact | ops / not IR-* |

---

## 14. Frozen decisions (Resource OS)

| # | Decision |
|---|----------|
| **RO1** | Host stability ≻ throughput; slow-but-complete is correct (**do not reopen**) |
| **RO2** | Do not chase max utilization |
| **RO3** | Host Guard (reactive) remains; Resource Planner (proactive) is required next |
| **RO4** | Resource OS is a platform OS layer (solar-plant test), not a Market/Personal feature |
| **RO5** | Every accepted task is durable, schedulable, checkpointable, resumable, resource-aware |
| **RO6** | Admission = **Can run?** ∧ **Should run now?** → explicit **Admission Contract** before Mission Queue |
| **RO7** | Hard env ceilings always win over profile aggressiveness |
| **RO8** | Assess Resources is a cognitive-lifecycle gate before Execute |
| **RO9** | Planning OS asks *what*; Resource OS asks *can safely* — keep separate |
| **RO10** | No new top-level OS; implement via [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) |
| **RO11** | Resource Planner estimates time/energy/risk/benefit/storage/checkpointability, not only RAM/CPU |
| **RO12** | Memory has three layers: **admission** (Layer 1) → **runtime enforcement** (Layer 2 / IR-RO11) → **OS backstop** (Layer 3). systemd is never the primary memory manager |
| **RO13** | Workers must be **cooperative** under memory pressure (checkpoint → release → pause/requeue); unbounded “process everything” ticks are a Resource OS bug |

---

## 15. Build order

Tracked in [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md). Do not replace that list with new architecture essays.

Shipped through Phase 5 (IR-RO1…RO10, IR-M1…M3, IR-RO9). **Next: IR-RO11 (Runtime Memory Enforcement).**

---

## 16. Related docs

| Doc | Role |
|-----|------|
| [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) | **Execute here** — IR-* workstreams |
| [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md) | Shipped Host Guard + Archive |
| [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) | OS layer map (settled) |
| [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) | Cognitive lifecycle + host principle |
| [`STAGE_3_2_PLAN.md`](STAGE_3_2_PLAN.md) | Detect→slow, caps, never fail for capacity |
| [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md) | How to run Archive safely |
| [`deploy/systemd/atlas.service`](../deploy/systemd/atlas.service) | Layer 3 MemoryMax + Restart backstop |

---

*End of document. Architecture frozen — implement IR-RO11 next.*
