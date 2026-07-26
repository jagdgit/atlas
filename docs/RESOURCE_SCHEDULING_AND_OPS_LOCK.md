# Resource Scheduling & Ops Visibility — Design Lock

> **Audience:** architects / implementers  
> **Status:** **LOCKED** · architecture stable · implement only — see [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md)  
> **Date:** 2026-07-26 (finalized after architecture review)  
> **Parents:** [`RESOURCE_OS.md`](RESOURCE_OS.md), [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md), [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)  
> **Host context (assumed):** Intel i7-14700 · ~16 GB RAM · Ubuntu · Atlas + Ollama + PostgreSQL · Docker · shares machine with production apps  

This note freezes **scheduling, admission, and Ops visibility**. It supersedes the earlier “three physical queues” sketch. **Do not redesign** unless a solar-plant-test failure forces it.

**Document roles in the design set:**

| Doc | Role |
|-----|------|
| Platform Architecture | *What* Atlas is |
| Resource OS | *Principles* |
| **This file** | *How* scheduling / admission / Ops work |
| Implementation Roadmap | *What gets built next* |

---

## 1. Why we needed this lock

### Ops misleads today

Ops showing **Workers: 25** is like Linux saying only “Processes: 432.”

| Metric | Meaning |
|--------|---------|
| Workers (running status) | Inventory of Persistent Workers “on” |
| Tick slots (e.g. `0 / 2`) | True concurrency ceiling |
| Host Guard | Host safe or not |
| Capacity / archive queue | Extra work accepted but waiting |

**Problem:** fairness-oriented throttling can starve **timing-sensitive** Market work. Missing a signal makes the simulation wrong — different objective from “be fair to Archive.”

### Host-first still holds

Conservative `.env` (2 tick slots, 1 LLM lane, 1 archive worker) remains the default. Do **not** raise `MAX_CONCURRENT_TICKS` until real Ops metrics (tick duration, queue depth, starvation, CPU/RAM pressure) justify it.

---

## 2. Rejected: three physical queues

**Do not implement** separate URGENT / USER / BACKGROUND queues.

**Prefer:** **one Mission Queue** with rich attributes; the Resource Scheduler **selects**. Scales to GPU jobs, cloud workers, remote nodes later without multiplying queues.

---

## 3. Locked end-to-end pipeline

```text
Planner (Planning OS)
  ↓
Admission Request  →  Resource Planner
  ↓
Admission Contract   Accepted | Deferred | Rejected | Needs Confirmation
  ↓
Mission Queue        (only accepted work enters)
  ↓
Resource Scheduler   (internal stages — operator never sees these)
  │    Candidate Selector
  │    Reservation Manager
  │    Host Guard              ← machine protection only
  │    Dispatcher
  ↓
Worker tick
  ↓
Checkpoint
  ↓
Release Reservation
```

| Layer | Decides |
|-------|---------|
| **Planner** | What should we do? |
| **Resource Planner + Admission Contract** | Can/should this enter the queue? When? Confirm? |
| **Mission Queue** | Durable accepted work + explainable wait states |
| **Candidate Selector** | Which READY item is best-next? |
| **Reservation Manager** | Account resources before start |
| **Host Guard** | Is the host safe for *this* admission? |
| **Dispatcher** | Hand off to worker / start tick |

**Host Guard must not become the scheduler.** It only protects the machine.

**Mission Queue only receives accepted work.** Everything before that is Resource Planner / Admission.

---

## 4. Admission Contracts (required architectural piece)

Before work enters the Mission Queue, every Program negotiates with Resource OS.

```text
Admission Request
  → Resource Planner (estimate + policy)
  → Admission Contract result:
       Accepted (immediate | deferred_until)
       Rejected (reason)
       Needs Confirmation (estimate shown; operator Y/N)
```

Examples:

| Program work | Typical contract |
|--------------|------------------|
| Market tick / signal | **Accepted** · immediate |
| Archive walk | **Accepted** · deferred to quiet hours *or* Needs Confirmation |
| Large research | **Needs Confirmation** · e.g. ~9 h estimate |

The contract is an **explicit object** (API + logs), not an implicit boolean. Fits IR-RO1 Resource Planner; elevates “admission result” to first-class.

---

## 5. Queue item shape (unified)

Every work item carries:

```text
Queue Item
  ├── Owner
  │     Program · Mission · Worker · Portfolio · Operator
  ├── Service class      REALTIME | INTERACTIVE | NORMAL | BATCH
  │                      (future room: REALTIME_CRITICAL | REALTIME_STANDARD — not v1)
  ├── Priority           int / criticality
  ├── Deadline           optional but required for timing-sensitive work
  ├── Latency tolerance  e.g. 5s vs 3 days
  ├── Resource profile   CPU / RAM / Network / Disk IO / Storage growth / …
  ├── Estimated runtime
  ├── Checkpointability
  └── Reservation need
```

**Deadline > priority for Market.** Example: signal expires in 30 s vs 10 min — scheduler must know; priority alone cannot express that.

**Owner fields** exist so Ops/debug can answer “whose work is this?” without log archaeology.

---

## 6. Service classes (OS-style)

| Class | Latency tolerance (illustrative) | Examples |
|-------|----------------------------------|----------|
| **REALTIME** | seconds | Market Observer, Decision Simulation, paper-trading near signal |
| **INTERACTIVE** | seconds–minutes | Chat, UI Jobs, Archive confirm handshake |
| **NORMAL** | hours | Repository learning, news/company intel, mentors |
| **BATCH** | days | Owner Knowledge walks, bulk embeds, overnight research |

Ordering preference:

```text
REALTIME → INTERACTIVE → NORMAL → BATCH
```

**Future (do not implement yet):** split REALTIME into `REALTIME_CRITICAL` (UPS / security / plant critical failure) vs `REALTIME_STANDARD` (Market signal). Leave enum/extension room; ship four classes first.

Archive long walk = **BATCH**. UI confirm may be INTERACTIVE; the file walk remains BATCH.

---

## 7. Capacity reservation (Market protection)

With `MAX_CONCURRENT_TICKS=2`:

| Rule | Behaviour |
|------|-----------|
| **Hard intent** | While REALTIME is READY, **≥1 tick slot** reserved for REALTIME |
| **Forbidden** | Both slots held by BATCH/NORMAL while Market REALTIME waits |
| **Dynamic (target)** | No REALTIME READY → release reserve; REALTIME READY → reclaim immediately |

**Ship first:** static floor 1 REALTIME + 1 everything else.  
**Next:** dynamic release when Market idle.

---

## 8. Resource Reservations

```text
Reservation
  ├── CPU share / class
  ├── RAM MB
  ├── Network
  ├── Disk IO          ← bandwidth / contention (scan-heavy)
  └── Storage Growth   ← durable bytes added (embeddings, extracts)
```

**Disk IO ≠ Storage Growth.** Example: repo scan = high IO / low growth; embedding = medium IO / high growth.

Lifecycle: **Acquire → Run → Checkpoint → Release** (IR-RO7). A worker may be non-running yet still **Holding Reservation** — Ops must show that.

---

## 9. Ops visibility (replace “Workers: 25”)

### 9.1 State breakdown (required)

| State | Meaning |
|-------|---------|
| Running ticks | Currently executing a tick |
| Holding Reservation | Owns resources but not (yet) running |
| Ready | Eligible; waiting for a slot |
| Waiting Host | Deferred by Host Guard / pressure |
| Waiting Schedule | Should-not-run-now / cadence |
| Waiting Dependency | Blocked on another mission/artifact |
| Sleeping | Between ticks; healthy idle |
| Paused | Operator or capacity pause |
| Starved | Waiting beyond aging threshold |
| Slow | Tick duration ≫ expected |
| Completed | Finite workers done (if shown) |

### 9.2 Per-worker timing (required)

| Field | Why |
|-------|-----|
| Owner (Program / Mission / …) | Debug attribution |
| Service class | REALTIME / … |
| Deadline / latency | Timing intent |
| Last / avg / max tick | Spot spikes |
| Waiting reason | Host / schedule / dependency / reserve |
| Starvation age | Time since last productive progress |
| Checkpoint age / progress | Archive done/total |

### 9.3 Slow / starved

Expected tick ≪ actual → **Slow**. Long READY/WAITING with no progress → **Starved** (surface + optional aging boost).

---

## 10. Mission declarations (templates)

| Field | Example |
|-------|---------|
| Service class | REALTIME / INTERACTIVE / NORMAL / BATCH |
| Latency tolerance | 5 seconds / 3 days |
| Deadline policy | e.g. signal TTL |
| Criticality | critical / normal / low / very_low |
| Resource profile | CPU / RAM / Disk IO / Storage growth / Network |
| Checkpointability | per file / per tick / none |

| Mission | Class | Latency | Criticality |
|---------|-------|---------|-------------|
| Market Observer | REALTIME | ~5 s + deadline | Critical |
| Paper trading / Decision Simulation | REALTIME | seconds–minutes + deadline | Critical |
| Chat / interactive Jobs | INTERACTIVE | interactive | High |
| Repository learning | NORMAL | hours | Normal |
| Owner Knowledge archive | BATCH | days | Low |
| Self-improvement | BATCH | days | Very low |

---

## 11. Environment / profiles (locked defaults)

| Setting | Locked default | Notes |
|---------|----------------|-------|
| `ATLAS_RESOURCES_PROFILE` | `conservative` | Coexist with prod + Ollama |
| `ATLAS_RESOURCES_MAX_CONCURRENT_TICKS` | `2` | **Do not raise** until Ops metrics justify |
| `ATLAS_LLM_MAX_CONCURRENCY` | `1` | Always |
| `ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS` | `1` | Always |
| OCR / extract workers | `1` | Keep tight |

| Profile | Preferred tick slots (under hard ceiling) |
|---------|-------------------------------------------|
| Conservative | 2 |
| Balanced | 3 |
| Maximum | 4 |

---

## 12. Recommendations locked (summary)

| Item | Recommendation |
|------|----------------|
| Queues | **One** Mission Queue — not three physical queues |
| Admission | **Admission Contract** before queue entry (Accepted / Deferred / Rejected / Needs Confirmation) |
| Scheduler internals | Candidate Selector → Reservation Manager → Host Guard → Dispatcher |
| Service classes | REALTIME → INTERACTIVE → NORMAL → BATCH; leave room for REALTIME_* levels later |
| Market | Deadlines + REALTIME slot reserve (≥1 when READY) |
| Reservations | CPU / RAM / Network / **Disk IO** / **Storage Growth** |
| Queue item owner | Program · Mission · Worker · Portfolio · Operator |
| Ops | Full state breakdown incl. **Holding Reservation**; not bare worker count |
| Environment | Keep ticks=2 / LLM=1 / archive=1; scale via profiles after metrics |

---

## 13. Implementation mapping

| Design piece | Roadmap ID |
|--------------|------------|
| Admission Contract + Planner estimates | **IR-RO1** |
| Ops state breakdown + timings + Holding Reservation | **IR-OPS1** |
| Mission Queue states + owner fields | **IR-RO2** |
| Profiles + service class + deadline policy | **IR-RO3** |
| Candidate Selector + REALTIME reserve + deadlines | **IR-RO5** |
| Storage pressure (feeds scheduler) | **IR-RO6** (after IR-RO5) |
| Reservations / leases (Disk IO + Storage Growth) | **IR-RO7** |
| Dynamic budgets + hysteresis | **IR-RO4** |
| Profile-driven tick preference | **IR-RO8** |
| Should-run-now / defer windows | **IR-RO10** |
| Mission DAG / child missions | **IR-M1** |
| Mission wait-time aging | **IR-M2** |
| Confidence-aware research attention | **IR-M3** |
| Power / deeper thermals | **IR-RO9** |

---

## 14. Explicit non-goals

- Three separate queue processes or three Host Guards  
- Maximizing CPU/RAM utilization  
- Raising default tick slots without Ops evidence  
- Letting BATCH hold all slots while REALTIME is READY  
- Implementing REALTIME_CRITICAL/STANDARD in v1 (room only)  
- Replacing Planning OS with the Resource Scheduler  
- New top-level OS box  
- Coupling Resource OS to Market-only concepts (solar-plant test)

---

## 15. Architecture review provenance (2026-07-26)

Review conclusion: design set is **stable enough to stop redesigning and implement**.

Kept: one queue, service classes, Planner vs Resource OS boundary, Host Guard = protection only.  
Refined before code: scheduler internal split, Admission Contracts, deadlines, Disk IO vs Storage Growth, queue owners, Holding Reservation, IR-RO6 after IR-RO5.  
Unchanged: conservative defaults (`MAX_CONCURRENT_TICKS=2`).

---

*End of lock. Implement via the roadmap. Do not open a fifth architecture essay.*
