# Atlas Resource Management Framework (ARMF) — Ops, Capacity & Starvation Plan

> **Status:** 🔒 **FINALIZED** (operator lock 2026-07-28) — see master sprint order in [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md)  
> **Also known as:** Ops Starvation Cleanup + Reserved Capacity (supersedes narrow naming)  
> **Date:** 2026-07-28  
> **Audience:** operator + implementers  
> **Parents:** [`RESOURCE_SCHEDULING_AND_OPS_LOCK.md`](RESOURCE_SCHEDULING_AND_OPS_LOCK.md) ·
> [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md) ·
> [`HOST_UNATTENDED_AND_MARKET_RESILIENCE.md`](HOST_UNATTENDED_AND_MARKET_RESILIENCE.md) ·
> [`RESOURCE_OS.md`](RESOURCE_OS.md)  
> **Sister plans:** [`SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md`](SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md) (research lens) ·
> [`IRA_NEXT_LEAP_EVIDENCE_PLAN.md`](IRA_NEXT_LEAP_EVIDENCE_PLAN.md) (evidence quality)  
> **Open item:** `OI-OPS1` — **Sprint 2 active (Phase A)**; Evidence frozen 2026-07-28; then B; Sprint 3 = C

This document has two jobs:

1. **Explain today’s Ops symptoms** (idle ticks, starved, WAITING_HOST, UI flake).  
2. **Lock the Atlas Resource Management Framework (ARMF)** — how Atlas allocates execution
   across Market / Engineering / Personal / Knowledge / Archive **above** Host Guard.

---

## 0. Short verdict

| Feeling | Reality |
|---------|---------|
| “Atlas is idle” | Often **true for ticks** — Host Guard + tiny global budget. Inventory ≠ concurrency. |
| “Archive waiting while CPU free” | Archive is a **separate lane**; idle CPU does not free it. |
| “Starved = broken” | **Starved ≠ crashed** — no productive tick for ≥6h while eligible. Zombies + budget-blocked work both show starved. |
| “Market should research” | Missions queued; many **WAITING_HOST / budget**. Research needs **capacity policy**, not more cores alone. |
| “UI feels off” | Auth / JS / slow Ops payload — separate from kernel health. |

**Core problem (locked):** Atlas does **not** lack CPU. It lacks a **resource allocation policy**.  
Everything competes for one undifferentiated budget → important Market work can wait days.

**Design lock:**

```text
Programs / Objectives
        ↓
Mission Scheduler (urgency, aging, deadlines)
        ↓
Capacity Allocation (program % budgets + borrowing)
        ↓
Lane / Class Assignment (realtime vs background vs heavy vs LLM)
        ↓
Host Guard  ← FINAL VETO (unchanged, sacred)
        ↓
Worker tick
```

Host Guard remains the last line of defense on ~16 GB RAM + Ollama + Postgres.

---

## 0b. Why OI-OPS1 is P1 for the next decade

Reliable differentiating research (Evidence + Sector Intelligence) **does not matter** if
Market / Research workers cannot obtain ticks. ARMF is the **execution foundation** for every
Intelligence — not a cosmetic Ops cleanup.

---

## 1. Two numbers people confuse

### 1.1 Workers (inventory) — “28 on”

These are **Persistent Workers** attached to missions (always-on *identities*).

Think: Linux process table entries that exist, not “currently using CPU.”

### 1.2 Tick slots — “1 / 2” or “0 / 2”

This is the **real concurrency ceiling** (Host Guard + mission arbiter).

```text
Workers on (inventory)     ≈  how many workers exist
Tick slots in use          ≈  how many are allowed to run a tick RIGHT NOW
READY missions             ≈  admitted work that wants a slot
WAITING_HOST missions      ≈  admitted work blocked by budget / archive / host
```

**So:** Atlas can look idle (0 running ticks, low CPU) **and** show a long Mission Queue.
That is not a contradiction — it is **admission control**.

```text
                    ┌─────────────────────────────┐
  Mission created → │ Mission Queue (durable)     │
                    │  READY / WAITING_HOST / …   │
                    └──────────────┬──────────────┘
                                   │ Candidate Selector
                                   ▼
                          Host Guard + Arbiter
                          (max ~2 ticks, 1 archive)
                                   │
                    ┌──────────────┴──────────────┐
                    │ admit                       │ defer
                    ▼                             ▼
              Worker.do_tick()              stay WAITING_HOST
                    │                       (budget / archive full / pressure)
                    ▼
              release reservation → next candidate
```

---

## 2. What every Ops worker state means

| Ops state | Plain meaning |
|-----------|----------------|
| **Running ticks** | A tick is **in flight** right now. |
| **Holding reservation** | Slot reserved; about to tick or finishing bookkeeping. |
| **Ready** | Worker is **eligible** and should get a turn soon (not currently blocked by a fresh host wait). |
| **Waiting Host** | Recently deferred for **host/budget/capacity** (fresh window ~5 minutes in classifier). |
| **Waiting Schedule** | Waiting for cron / backoff (e.g. crash recovery). |
| **Waiting Dependency** | Blocked on another mission/worker. |
| **Sleeping** | Just finished a tick; resting briefly before due again. |
| **Paused** | Operator pause or failed/blocked (not host queue). |
| **Starved** | See §3 — **no productive tick for ≥ 6 hours** while still “running.” |
| **Slow** | Last tick took much longer than expected for that worker type. |
| **Completed** | Worker stopped. |

Mission Queue states (parallel vocabulary):

| Mission state | Plain meaning |
|---------------|----------------|
| **READY** | Admitted; scheduler may pick it. |
| **WAITING_HOST** | Admitted but Host Guard / budget / archive lane says “not now.” |
| **WAITING_SCHEDULE** | Time gate. |
| **RUNNING** | Actively executing. |
| **ARCHIVED** | Finished / retired from active queue. |

---

## 3. “Starved” — clear definition

### 3.1 Official meaning (code)

From `atlas/ops/worker_states.py`:

- A worker with status `running` is classified **starved** when  
  **seconds since last productive tick (or created_at if never ticked) ≥ 6 hours**  
  (`STARVE_AFTER_SECONDS = 6 * 3600`).
- The wait reason looks like `no_progress_174362s` (= ~2 days without a successful progress tick).

**Starved is a dashboard diagnosis, not a separate runtime mode.**  
The worker is still “on”; the Ops page is warning that it is **not making progress**.

### 3.2 Two kinds of starvation you are seeing

| Kind | Example on your Ops page | What to do |
|------|--------------------------|------------|
| **Zombie / leftover** | `hello_watcher` · age 8–9 days · no program | **Cleanup** — stop/archive those missions. They steal attention and sometimes compete for attention in notable lists. |
| **Blocked-by-policy** | `investment_universe` / `investment_mentor` · ~2 days · `market_intelligence` | **Not a crash** — their missions sit **WAITING_HOST / budget**. Fix admission priority or free tick slots; do not only “kill” them. |

### 3.3 Why Market workers become starved

Typical chain:

1. Market mission is created (Universe, News, Company Intelligence, …).  
2. Host Guard admits only **2 ticks** globally (conservative profile on ~15 GB RAM).  
3. Other work + reservations occupy slots; Market missions get **`budget`** → **WAITING_HOST**.  
4. Worker stays `status=running` but **never gets a productive tick**.  
5. After 6 hours, Ops paints it **starved**.

So: **starved Market worker ≈ “we wanted this research, but Host Guard kept saying not yet.”**

---

## 4. Why Archive waits while Atlas “feels free”

Archive is **not** funded from the same mental bucket as “CPU looks idle.”

| Lane | Cap (conservative default) | Your symptom |
|------|----------------------------|--------------|
| **General ticks** | `effective ticks 2 / hard 2` | Market / Eng / Personal compete here |
| **Archive workers** | **`archive slots 1 / 1`** | Second archive job → **WAITING_HOST · archive worker slots full** |

So when you see:

```text
archive slots     1 / 1
WAITING_HOST … Archive · Cursor … archive worker slots full
WAITING_HOST … Archive · personal … archive worker slots full
CPU  low, RAM low
```

Meaning:

- One archive worker is **holding the only archive slot** (or the slot is reserved).  
- Other archive missions **must wait** — by design.  
- Low CPU does **not** auto-open a second archive lane (would risk disk/IO thrash on shared host).

**Idle CPU ≠ free archive capacity.**

---

## 5. Why Market Intelligence research is not “always on”

You want: *Market Intelligence should keep researching companies, themes, docs, …*

What Atlas does today:

1. **IIP pipeline is built** (Universe → Discovery → Research → MKG → Score → Portfolio → Sim → Learn → News).  
2. **Missions exist** (Investment Universe, News, Company Intelligence, Observer, …).  
3. **Execution is gated** by Host Guard so Ollama + Postgres + desktop stay alive.

On your recent Ops snapshot:

- Many Market missions: **WAITING_HOST · budget**  
- Investment Universe / Mentor workers: **starved** (no tick for ~2 days)  
- Only a few Market missions **READY**  
- **Running ticks** often **0** right after restart or under deferral  

So the product intent (“research companies”) is **queued**, not abandoned — but **under-served** under the current tick budget + leftover zombies + archive competition for operator attention.

### What “busy → free → next job” should look like (healthy)

```text
tick N:   Market Observer runs → finishes → releases slot
tick N+1: Investment Universe admitted → ranks / discovers → releases
tick N+2: Company / News research tick → releases
…
Archive:  at most 1 archive tick interleaved when slot free
```

### What you have instead (unhealthy appearance)

```text
tick slots mostly empty or reserved
READY list small
WAITING_HOST list long (budget + archive full)
starved list long (hello_watcher zombies + blocked Market)
```

---

## 6. UI refresh “Atlas feels off”

Separate from scheduling:

| Symptom | Likely cause |
|---------|----------------|
| Blank page / login loop | JS error or both login+app hidden (recently fixed: `dash42`, login visible by default). |
| Refresh fails a few times then works | `/v1/ops` is **large** (~100KB+) and can be **slow**; browser timeout / race while Atlas is still starting (uptime 11s on one of your captures). |
| 401 then “dead” | Missing/expired API key in `localStorage`; Ops never loads. |
| 304 cache confusion | Rare now (`Cache-Control: no-cache`); hard-refresh still safest after UI deploys. |

**Plan:** treat Ops UX reliability as first-class (faster Ops summary endpoint, clearer “connecting / degraded” banner, never blank).

---

## 7. Degraded Atlas (the yellow badge)

On your host, **degraded ≠ Market broken**.

Recent health: **recovery** service severity **degraded** because storage integrity reported **many missing asset files** (old git/architecture assets). Atlas still **healthy=true** overall with 34 ok / 1 deg.

| Badge | Meaning for you |
|-------|-----------------|
| **degraded** | Something needs attention (today: recovery/missing assets). |
| **failed** | A core service is down — treat as outage. |

Cleanup of missing assets is **optional** unless you still need those archived repos/graphs.

---

## 8. Goals

1. **Honest Ops** — starved / waiting host / inventory / program health explained.  
2. **Cleanup** — retire zombie workers (`hello_watcher`, dead no_progress).  
3. **ARMF capacity policy** — allocate execution budget across programs (not one global free-for-all).  
4. **Capacity reservations (not fixed worker identities)** — Market may use many workers within its %; Eng may use one.  
5. **Resource profiles + classes** — scheduler knows CPU/RAM/disk/network/**LLM** cost.  
6. **LLM-aware scheduling** — model Ollama inference/embedding slots as first-class scarce resources.  
7. **Predictive starvation + aging + deadlines** — intervene before 6h; SLA-relative urgency.  
8. **Borrowing** — idle program capacity loans out; reclaimed when that program has READY work.  
9. **Objective-oriented scheduling** (phase later) — satisfy research objectives, not only worker names.  
10. **Host Guard unchanged as final veto**.  
11. **UI reliability** — Ops loads without feeling “Atlas off.”

---

## 8b. From fixed lanes → capacity reservations (operator refinement 2026-07-28)

### What we keep from the earlier “1 lane each” idea

Guarantee that **Market / Engineering / Personal / Archive** cannot be **totally starved** by peers.

### What we change

Reserve **capacity (budget share)**, not a single permanent worker identity.

Example default shares of **admitted tick budget** (illustrative; Host Guard still caps absolute concurrency):

| Program / pool | Share | Notes |
|----------------|-------|-------|
| Market Intelligence | **25%** | Research + observer + sim |
| Engineering Intelligence | **25%** | Repo / tech watch |
| Personal Intelligence | **15%** | Career / observer |
| Knowledge / platform | **15%** | Ingest, candidates, verification |
| Archive | **10%** | Disk-heavy; also hard archive-slot cap |
| Emergency / interactive | **10%** | API-critical, operator, recovery |

On a preferred ceiling of **4 concurrent general ticks** (archive separate):

- Market floor ≈ ability to run **at least 1** when it has work (and room to scale toward 2 when others idle via borrowing).  
- Engineering / Personal similarly protected.  
- Absolute tick count still **4 preferred / 5 hard** on this 16 GB / 28-core / no-GPU host — CPU is plentiful; **RAM + LLM** are not.

**Borrowing (locked):**

```text
Engineering idle (no READY work)
        ↓
loan unused share → Market (or whoever needs it)
        ↓
Engineering gets READY work
        ↓
reclaim share immediately (Market may defer next tick)
```

Idle reservations must not sit empty while Market research waits.

---

## 8c. Resource classes & profiles

### Work classes

| Class | Examples | Scheduling bias |
|-------|----------|-----------------|
| **Interactive** | API, chat, Ops refresh | Highest latency sensitivity; tiny budget |
| **Real-time** | Market observer ticks | Soft/hard deadlines in minutes |
| **Background** | Dossier research, mentor | Hours–days SLAs |
| **Heavy** | LLM reasoning, decision sim | Limited by LLM slots |
| **Maintenance** | Archive, prune, backup | Disk-aware; archive slot |

### Resource profile (every worker declares)

```text
cpu: low|medium|high
memory: low|medium|high
disk: none|low|high
network: low|high
llm: no|yes|heavy
embedding: no|yes
priority_class: interactive|realtime|background|heavy|maintenance
```

Examples:

| Worker | Profile sketch |
|--------|----------------|
| Market Observer | cpu low, network high, llm no |
| Investment Research | cpu medium, llm yes |
| Archive / Owner Knowledge | disk high, cpu low, llm no |
| Decision Simulation | llm heavy, memory high |

Scheduler admits work that **fits remaining resource vectors**, not only “a free tick integer.”

---

## 8d. LLM is a first-class scarce resource

On this host the real bottleneck is often:

```text
Ollama → inference / embeddings
```

not idle CPU cores.

ARMF must track:

| Resource | Meaning |
|----------|---------|
| Inference slots | Concurrent LLM generations |
| Embedding slots | Concurrent embed batches |
| Token budget (optional later) | Per window soft cap |

Heavy LLM work must not crowd out **non-LLM** Market observer ticks (network-cheap, llm=no).

---

## 8e. Starvation: reactive → predictive

| Stage | Meaning |
|-------|---------|
| **Healthy** | Ticking within expected cadence |
| **At risk** | Expected tick ≪ actual wait (e.g. expect 2m, waited 20m) |
| **Starved** | Still: ≥6h no productive progress (or SLA hard-miss) |

Ops should surface **At risk** before the 6h scarlet letter.

### Mission deadlines (SLA)

| Mission flavor | Soft | Hard |
|----------------|------|------|
| Market news / observer | ~5 min | ~30 min |
| Engineering mentor | ~1 day | ~7 days |
| Personal summary | ~12 h | ~3 days |
| Archive | none / soft only | none |

Starvation / priority uses **time relative to SLA**, not only wall-clock since last tick.

### Aging priority

```text
wait 0     → base priority
wait 30m   → +band
wait 2h    → +band
wait 6h    → high band (hard to ignore)
```

Long WAITING_HOST work bubbles up **within** its program share and then into borrowed capacity — still subject to Host Guard.

---

## 8f. Schedule objectives & program goals (Phase F — design locked)

Prefer satisfying **objectives** over worshipping worker names:

```text
Program Goal          e.g. Research NIFTY50 this week
        ↓
Objectives            5 new companies · 20 news updates · 2 thesis revisions
        ↓
Missions              admitted work units
        ↓
Workers               ticks chosen to satisfy objectives
```

v1 (Phase C) still schedules workers with capacity shares + progress signals.  
v2 (Phase F) attaches **Program Goals → Objectives** explicitly. Do not block Phase C on Goals OS.

---

## 8f2. Research Progress (schedulable input — Phase C)

Coverage / dossier progress is a **first-class scheduler input**:

```text
Company A   ~95%  →  low marginal return on more research ticks
Company B   ~12%  →  high attention
```

Prevents burning hours to push 95% → 96% while another name sits at 10%.  
Signal sources: IRA coverage, MVR remaining, strategy checklist (when SI exists).

---

## 8g. Program health & Research Velocity (Ops UX)

Replace “only starved lists” with a rollup:

```text
Atlas Health  72%
  Market       At risk (2 starved, 5 WAITING_HOST/budget)
  Engineering  Healthy
  Personal     Healthy
  Archive      Congested (slot full)
  Knowledge    Healthy
  LLM          1/1 inference in use
```

**Research Velocity** (required KPI — what we actually care about):

| Program | Example |
|---------|---------|
| Market | Dossiers advanced / day |
| Engineering | Observations / mentor lessons / day |
| Personal | Facts confirmed / day |

Primary operator question: **Did Atlas produce more knowledge today?** — not CPU%, worker count, or tick count alone.

---

## 8h. Host Guard — do not weaken

```text
… Capacity Allocation → Lane/Class Assignment → Host Guard → Worker
```

Host Guard may still say **no** under RAM/thermal/disk pressure.  
ARMF decides **who deserves the next yes**; Host Guard decides **whether any yes is safe**.

---

## 9. Workstreams (phased)

### Phase A — Explain & filter · ~2–4 days

| ID | Work | Status |
|----|------|--------|
| A1 | Glossary: Starved, At risk, Waiting Host, inventory vs ticks, program shares | ✅ |
| A2 | Filters / hide `hello_watcher`; group by program | ✅ |
| A3 | Banner: RUNNING=0 + WAITING_HOST>0 → “capacity policy / Host Guard — not off” | ✅ |
| A4 | Degraded service name on atlas card | ✅ |
| A5 | Program health strip (even if heuristic v0) | ✅ |

### Phase B — Cleanup toolkit · ~3–5 days

| ID | Work | Status |
|----|------|--------|
| B1 | `POST /v1/ops/cleanup` dry-run + apply | ✅ |
| B2 | Default: `hello_watcher` + long no_progress | ✅ |
| B3 | Ops Cleanup UI Preview → Apply | ✅ |
| B4 | Never auto-kill Market/Eng/Personal/Archive without checkbox | ✅ |

### Phase C — ARMF capacity core · ~2–3 weeks

| ID | Work | Status |
|----|------|--------|
| C1 | Program capacity shares + borrowing | ✅ v1 (MissionArbiter floors) |
| C2 | Raise preferred ticks **4** / hard **5** (16 GB profile) with Host Guard admit | ✅ (defaults: maximum / 5) |
| C3 | Archive remains separate hard slot (1; opt-in 2 later) | kept |
| C4 | Resource profiles on workers (declare llm/cpu/mem/disk/network) | ✅ v1 (`llm`/`embedding` on WorkResourceProfile) |
| C5 | LLM inference/embedding slot accounting | ✅ v1 soft `llm_tick_slots` gate |
| C6 | Work class biases (interactive / realtime / background / heavy / maintenance) | ✅ (REALTIME reserve + LLM gate) |
| C7 | Soft/hard deadlines on mission templates + aging priority | ✅ existing IR-M2/deadline |
| C8 | At-risk detection before 6h starved | ✅ (≥30m / 30× expected) |
| C9 | Next-tick preview per program | ✅ Ops `next_tick` |
| C10 | Soft focus: UI Market/Invest intel biases **borrowed** capacity toward Market | ⏸ deferred (optional polish) |
| C11 | **Research Progress** signal into Candidate Selector (prefer advancing low-% dossiers) | ✅ score boost |
| C12 | **Research Velocity** on Ops / program health (dossiers advanced / day, etc.) | ✅ Ops strip |

**Phase C status:** ✅ **FROZEN for Sprint 4** (C10 deferred). Host Guard veto unchanged.

### Phase D — Archive clarity · ~2–3 days

| Item | Status |
|------|--------|
| Archive lane card on Ops (`archive_lane`) | ✅ D1 — CPU idle ≠ archive free |
| Opt-in 2nd slot gated | ✅ D2 — `ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS≥2` (keep **1** during market hours) |
| Cleanup idempotent on already-archived | ✅ (orphan worker stop) |

**Phase D status:** ✅ **FROZEN** (2nd slot opt-in via env; default remains 1).

### Phase E — UI load resilience · ~3–5 days

| Item | Status |
|------|--------|
| `GET /v1/ops/summary` first paint | ✅ |
| Ops UI retry + summary-then-full | ✅ |
| Startup warm-up banner | ✅ |

**Phase E status:** ✅ **FROZEN**.

### Phase F — Goals → Objectives (after C stable)

Program Goal → Objectives → Mission → Worker selection. Builds on C11/C12.

---

## 10. Explicit non-goals

- Tick concurrency near **28** because of 28 cores.  
- Weakening Host Guard.  
- Fixed “exactly one named worker” forever per program (use **capacity**).  
- Auto-delete without dry-run.  
- Building full Kubernetes.  
- Blocking Evidence Plan or Sector Intelligence on perfect ARMF — but ARMF is still P1 so research can run.

---

## 11. Operator actions now

1. Keep Atlas up.  
2. Ignore/cleanup `hello_watcher` when Phase B lands (or archive those missions manually).  
3. Expect archive congestion at 1 slot.  
4. After Phase C: verify program floors + borrowing on Ops health strip.

---

## 12. Success metrics

| Metric | Target |
|--------|--------|
| Zombie hello_watcher notable | 0 after cleanup |
| Market + Eng + Personal all READY | each makes progress within cycles (floors + borrow) |
| Market starved age | ≪ days on normal uptime |
| At-risk visible | before 6h starved |
| LLM slot awareness | non-LLM realtime not blocked solely by heavy LLM when slots allow split |
| Preferred / hard ticks | 4 / 5 with Host Guard veto intact |
| False “Atlas off” | rare |

---

## 13. Decisions locked

| # | Decision |
|---|----------|
| 1 | Expand OI-OPS1 → **ARMF** (not merely cleanup) |
| 2 | Reserve **capacity %** (+ borrowing), not rigid single-worker identities |
| 3 | Default floors: Market/Eng/Personal/Archive/Knowledge/Emergency shares as in §8b |
| 4 | Tick pool this host: preferred **4**, hard **5**; archive **1** |
| 5 | Resource profiles + **LLM slots** first-class |
| 6 | At-risk + deadlines + aging before/alongside starved |
| 7 | **Research Progress** + **Research Velocity** first-class (Phase C) |
| 8 | Goal→Objectives hierarchy = Phase F (designed now) |
| 9 | Host Guard **final veto** — unchanged |
| 10 | **Global order:** Evidence freeze → ARMF A+B → ARMF C → SI.1+ ([`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md)) |
| 11 | Do **not** start SI before ARMF C; do **not** interrupt Evidence for ARMF |

---

## 14. Relationship to locked plans

| Plan | Relationship |
|------|----------------|
| Research & Execution Roadmap | **Master sprint order** |
| Resource Scheduling lock | One queue + Host Guard **kept**; ARMF is admission policy **above** Guard |
| Host Respect | Archive lane **kept** |
| Evidence Plan | Sprint 1 — finish & freeze before ARMF |
| Sector Intelligence | Sprint 4 — after ARMF C |

---

**Next action:** operate (paper trading + evening email). Phase D+E frozen. C10 + Phase F deferred. Keep `ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS=1` while out unless you explicitly want archive parallel.

---

## 15. Leave-running checklist (operator away)

1. **Restart atlas** once after pulling these fixes (cleanup idempotent, SI.1–6, Ops summary).
2. Hard-refresh UI (`?v=dash55`).
3. Ops → Cleanup Preview → Apply (safe to re-run; already-archived = stop orphans).
4. Leave **archive at 1 slot**; do not start Owner Knowledge ingest during market hours.
5. Learner paper book may stay at **0 buys** — session notes show `strategy_hold` / `mark_only` (normal until MA crossover).
6. Investor evening email explains zero fills from session notes when SMTP is configured.
7. Host profile stays **conservative**; Host Guard veto unchanged.
