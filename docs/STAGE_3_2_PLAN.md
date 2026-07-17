# Atlas — Stage 3.2 Plan (Robust Readers + Resource-Aware Execution)

> **Status:** ✅ **3.2a–3.2e shipped** (async Job Planner + create visibility).
> Gating decisions **D32.1–D32.18** are locked.
> Implementation defaults **A32.*** are locked in §12.
>
> **Build progress:** **3.2a–3.2e** are in the tree.
> Stage 4 may later learn/tune machine-specific costs and broaden planner coverage.
>
> **2026-07-17 architecture-review alignment:** external review rated the Stage 3.2
> architecture very highly and asked for one strategic direction —
> **evolve the Resource Manager from reactive to predictive** — plus four refinements:
> adaptive worker pools, an explicit **task cost model**, **LLM capacity as a first-class
> resource**, and a dedicated **Execution Planner** layer. Folded in as **D32.9–D32.14** /
> **3.2d**. See §3, §4h–§4k, §6, §7.
>
> **2026-07-17 live-create diagnosis → 3.2e (implemented):** `POST /v1/jobs` no longer
> blocks on LLM JobPlanner decompose. Planning runs as background `plan_job` with visible
> `phase` + activity; bounded planner timeout; deterministic fallback kept. See §4l,
> **D32.15–D32.18**.

---

## 0. How to use this document

| Section | Role |
|---------|------|
| §1–§3 | Context, diagnosis, philosophy |
| §4 | Architecture (target) |
| §5 | Non-goals |
| §6 | Committed phases 3.2a → 3.2e → Stage 4 |
| §7 | Locked product decisions D32.* |
| §8 | Success criteria |
| §9 | Operator answers |
| §10 | Decision log |
| **§11** | **Implementation blueprint (files, order, acceptance)** |
| **§12** | **Locked implementation defaults (A32.***)** |
| **§13** | **Resolved clarifications / no remaining ambiguities** |

---

## 1. Where we are (honest progress)

The latest run is a **significant improvement** over the “0 claims everywhere” failure.

### Before (Stage 3.0 live failure)

| Signal | Reality |
|--------|---------|
| Verified claims | ~0 |
| Extraction | Failed on almost every paper |
| Research engine | Working |
| Extraction engine | Broken |

### After (Stage 3.1 live run)

| Signal | Reality |
|--------|---------|
| Extracted claims | ~14–15 (real facts: SVR, 5% MAPE, 15‑min data, 7 years, cleaning events, …) |
| Relevance filter | Dropped off-topic sources (e.g. 5) |
| Gap-driven search | Working |
| Acquisition / workspace stats | Visible |
| Report | Meaningful conclusions instead of “No evidence” |
| Confidence | Still **LOW** — **correct and preferred** over confident hallucination |

**Verdict:** Stage 3 research *logic* is moving in the right direction. Remaining weakness is
no longer primarily “does Atlas know how to research?” — it is **how Atlas executes reading
and work across formats and hardware**.

### Live-run scorecard (evolution)

| Component | Previous | Current | Notes |
|-----------|----------|---------|-------|
| Search relevance | 4/10 | 8/10 | Relevance gate landed |
| Source classification | 5/10 | 8/10 | Evidence levels useful |
| Document acquisition | 5/10 | 8/10 | Real acquire stats |
| Reading pipeline | 3/10 | 6/10 | **Next bottleneck** |
| Claim extraction | 2/10 | 6.5/10 | Works on a **subset** of formats |
| Verification | 8/10 | 8.5/10 | Keep honesty |
| Reporting | 5/10 | 8/10 | Real numbers in report |
| Resource utilization | 2/10 | 2/10 | Pipeline-bound, not compute-bound |

---

## 2. Diagnosis — the next two bottlenecks

### 2a. Extractor works only on a subset of formats

The critical log pattern:

```
Acquired 4 documents
Read 2
3 blocked
…
Extracted 15 claims   ← from one paper
Extracted 0 claims    ← from almost everything else
```

**Interpretation:** we shifted from “extractor completely broken” → “extractor works on some
document shapes (e.g. good HTML/ar5iv text) and fails on others.” That is progress — and it
points at **reading / normalization**, not claim logic alone.

Related symptom:

```
Read 29945 chars
Read 4773 chars
No extractable text
```

The **Reader** is becoming the bottleneck: download succeeds, but usable normalized text does
not.

### 2b. Suspected current shape vs needed shape

**Likely today (oversimplified):**

```
Download → Read → Extract
```

**Needed:**

```
Download → Identify type → Choose reader → Normalize → Extract
```

Many formats, **one normalized document contract** into the extractor.

### 2c. CPU idle = pipeline-bound, not compute-bound

Observation: CPU and RAM barely moved during the run.

Atlas is not saturating hardware. It is doing roughly:

```
Search (wait) → Download (wait) → Read (wait) → Extract (wait) → Verify
```

Only one stage advances at a time. A human research team would overlap: A downloads while B
reads paper 1 while C extracts paper 2. Atlas should evolve toward that **without** becoming
nondeterministic or “max CPU at all costs.”

---

## 3. Design philosophy (the north star for Stage 3.2+)

### Resource-aware, not speed-aware

Most cloud AI systems optimize for:

```
Fastest answer → max CPU/GPU → max parallelism → good-enough answer
```

That is **not** Atlas’s problem. Atlas serves one operator on owned hardware.

**Atlas objective:**

```
Given available hardware
  → use every resource intelligently
  → never deadlock
  → never crash
  → never lose progress
  → eventually reach the best answer possible
```

“Deterministic” here means: **slow is acceptable; unreliable is not.** Same inputs + same
machine profile + same workload → same allocation decisions and same research outcomes
(ordering of merges / verification / report stays stable). Deterministic ≠ single-threaded.

> Prefer **pipeline utilization** over **maximizing CPU percentage**. Blind “use all cores”
> can *reduce* throughput (RAM thrash, LLM OOM, disk queue storms).

### The real optimization target (D32.14)

Atlas does **not** optimize CPU%. When Atlas is waiting on Postgres to commit, a website to
respond, or the LLM to generate, forcing more CPU work can *reduce* throughput. The true
objective is:

```
maximize  verified research work completed per hour
subject to  never crash / deadlock / lose progress / violate operator caps
```

CPU%, RAM%, and worker counts are **inputs to a decision**, never goals. A run that keeps the
box at 40% CPU but finishes more verified claims per hour is **better** than one that pins all
cores. Stage 3.2d surfaces a coarse “verified claims / hour” signal so this target is
measurable rather than aspirational.

---

## 4. Architecture (target)

### 4a. Multi-reader family (same normalized output)

Build (incrementally) specialized readers that all emit the **same** extended `Document`
(D32.2 — improve the existing type; do not invent a parallel `NormalizedDocument` each time
we harden):

| Reader | Role |
|--------|------|
| PDF text reader | Embedded text layer |
| HTML reader | Generic HTML / publisher pages |
| OCR reader | Scanned / image-only PDFs |
| LaTeX / ar5iv reader | arXiv HTML / TeX-derived |
| Publisher-aware (IEEE, Springer, Elsevier, …) | Only when generic path proves insufficient |

**Contract (extend existing `Document`):**

- Existing fields: `source_id`, `title`, `url`, `text`, `sections[]`, …
- **Add:** `reader_id`, `format`, `quality` (`full` / `partial` / `empty` / `blocked`)
- **Bibliographic when easy (D32.7):** `doi`, `citation` / cite-string, and other cheap
  metadata (authors, year, venue) when present in HTML/PDF/meta — store even if full text
  fails, so inventory and reports stay useful
- `chars`, `warnings[]`, **`error` / `failure_reason`** when anything goes wrong (D32.8 —
  never silent)

Extractor stays format-agnostic: it only sees the extended `Document`.

### 4b. Concurrent stages, deterministic merge

Conceptual layout (still **deterministic** — concurrency of independent work, fixed merge order):

```
                    Coordinator
                         │
     ┌───────────────────┼───────────────────┐
     │                   │                   │
 Searcher            Downloader         Knowledge Graph
     │                   │
     ▼                   ▼
   Queue               Queue
     │                   │
     ├───────────┬───────┘
     ▼           ▼
  Reader pool   Reader pool
     │           │
     ▼           ▼
  Extractor pool
     │
     ▼
  Verification  (synchronized)
     │
     ▼
  Report / Learning  (sequential)
```

**Safe to parallelize early:** search, download, read, OCR, HTML/PDF parse, chunking, claim
extraction, embeddings, checksums, dedup.

**Semi-parallel (need sync):** verification, knowledge-graph merge, claim grouping.

**Stay sequential:** final confidence, final report, learning / promotion / experience.

### 4c. Finer unit of work (document-level first)

Today: one research **job step** runs a serial Acquire→Read→Extract loop inside
`ResearchService._research_deep`.

**Stage 3.2b (locked default A32.1):** keep **one** research JobStep, but run **document-level
work items** inside it via capped worker pools (download / read / extract). Merge order is
always `source_id` (D32.4).

**Not in 3.2:** fan-out as separate `JobStep` rows per document, or section/claim tasks.
Those remain a later option once in-process document concurrency is proven.

```
Research Job (1 step)
  → Document work items (parallel under caps)
    → Section / Claim tasks   ← deferred after 3.2
```

### 4d. Resource Manager (kernel-facing; Stage 3.2 foundation, Stage 4 learning/tuning)

Today (simplified):

```
Scheduler → Workers
```

Proposed:

```
Job → Scheduler → Resource Manager → Workers
```

The Resource Manager continuously observes:

- CPU / RAM / disk I/O / network idle?
- LLM busy? downloader / reader / extractor idle?
- (later) GPU, temperature, power

Then allocates, e.g.:

- spare CPU → start another reader
- RAM high → do **not** start another LLM extract
- network idle → download more papers

Loop:

```
Observe → Evaluate → Allocate → Measure → Repeat
```

Same machine + same workload → same decisions (**deterministic scheduling**).

Workers request capacity instead of starting blindly:

```text
resource_manager.request(cpu=2, ram="1GB", gpu=False)
```

**Do not** create “24 workers because there are 24 threads.” Create workers as a *consequence*
of resource **targets**.

### 4e. Resource profiles (policies, not one mode)

| Profile | CPU target | RAM target | Intent |
|---------|------------|------------|--------|
| **Conservative** | ~40% | ~50% | Laptop / background |
| **Balanced** | ~70% | ~70% | Default daily research |
| **Maximum throughput** | ~95% | ~90% | Dedicated box, aggressive pools |
| **Overnight research** | ~95% | ~90% | Human sleeping — finish by morning; duration OK |

**What Overnight means:** it is a resource policy, not a different research method. It keeps
the same evidence rules, deterministic `source_id` merge, retries, checkpoints, and final
report. Compared with Balanced it may prefer **one or two more workers** when capacity exists,
use higher CPU/RAM *targets*, process longer queues, and continue until normal research stop
criteria are met. It must **never** weaken verification or invent evidence.

**Hard rule — profiles never break jobs on capacity:**

- Operator `max_worker_threads` / pool caps in env/config are **absolute ceilings**.
- Overnight (or Maximum) may *ask* for +1/+2 workers only **inside** that ceiling.
- If the ceiling is already fully used, or no free worker slots remain, Atlas **waits / queues /
  runs slower** — it does **not** fail the job, error out, or ignore the env cap.
- “No free threads” and “user already set max threads” are **normal operating conditions**,
  not failure modes.

Overnight is selectable via env (`ATLAS_RESOURCES_PROFILE`) and optionally per-job
(`resource_profile` on create). Per-job is safer for daily use: Atlas stays Balanced globally
while one long job is marked Overnight.

Overnight is a first-class Atlas mode: **time is cheap; unfinished research is not.**

**Resource protection — aware, not pretend-safe:**

- Worker/env caps limit how many workers Atlas starts. That reduces load; it does **not**
  alone equal a guarantee of safe temperature or electrical draw.
- Atlas must be **honest about protection state**: e.g. “caps enforced; thermal sensors
  readable” or “thermal sensors unavailable — not monitored.” Never imply the machine is
  fully protected when it is not.
- **When thermal or power pressure *is* detected:** Atlas must **slow down to protect the
  system** — reduce active workers / pause admitting new heavy work, keep existing work
  checkpointed, resume only after pressure eases (hysteresis). This is **not** a job failure:
  the research job waits or proceeds more slowly until it is safe to continue.
- **Stage 3.2c:** wire basic detect → throttle (CPU%/RSS always; thermal/power sensors when
  the OS exposes them). If sensors are missing, say so clearly and rely on caps only.
- **Stage 4:** richer sensor coverage, tuned thresholds, predictive back-off.

### 4f. Tuned worker pools + **user-owned caps (config / env)**

Pools are tuned independently. Hard concurrency caps are operator-configured (D32.3).

Atlas already uses `config/defaults.yaml` + `ATLAS_<SECTION>_<KEY>` env overrides
(`atlas/config/manager.py`). Stage 3.2 adds a **`resources`** section (final keys):

```yaml
# config/defaults.yaml
resources:
  profile: balanced              # conservative | balanced | maximum | overnight
  max_worker_threads: 4          # global ceiling (user-owned)
  max_download_workers: 4
  max_reader_workers: 4
  max_ocr_workers: 2
  max_extract_workers: 2         # also capped by llm.max_concurrency
  ocr_max_pages: 50              # per-document OCR safety bound (raise later for large docs)
  ocr_max_minutes: 15
  ocr_dpi: 300
```

```text
# .env overrides (examples)
ATLAS_RESOURCES_PROFILE=balanced
ATLAS_RESOURCES_MAX_WORKER_THREADS=4
ATLAS_RESOURCES_MAX_DOWNLOAD_WORKERS=4
ATLAS_RESOURCES_MAX_READER_WORKERS=4
ATLAS_RESOURCES_MAX_OCR_WORKERS=2
ATLAS_RESOURCES_MAX_EXTRACT_WORKERS=2
ATLAS_RESOURCES_OCR_MAX_PAGES=50
ATLAS_RESOURCES_OCR_MAX_MINUTES=15
ATLAS_RESOURCES_OCR_DPI=300
```
If only `max_worker_threads` is set, Atlas allocates pool sizes under that global ceiling.
Profiles further throttle toward CPU/RAM **targets**; env/config caps are the hard ceiling.
**3.2d refinement (D32.12):** pool sizes are additionally clamped **down** to the actual work
count / queue depth (§4h), so Atlas never starts more threads than there is work.

**Interaction with LLM lane:** today `llm.max_concurrency` defaults to **1**. Effective extract
parallelism = `min(max_extract_workers, llm.max_concurrency)`. Raising extract workers without
raising the LLM lane does nothing useful — document that in `.env.example`.

| Pool | Bound | Default (within global max) |
|------|-------|-------------------------------|
| Downloads | Network | ≤ 4 |
| Readers | CPU | ≤ 4 |
| OCR | Heavy CPU | ≤ 2 |
| LLM extraction | Memory + LLM lane | ≤ 2 ∧ `llm.max_concurrency` |
| Verifier | Sync | 1 |
| Report | Sequential | 1 |

### 4g. Predictive learning of the machine (later)

After weeks of runs, Atlas can learn costs:

- PDF extract ≈ 300 MB
- Ollama inference ≈ 2.2 GB
- OCR ≈ 900 MB
- Embedding ≈ 700 MB

Scheduling becomes **predictive**, not only reactive. Same idea scales later to whole-machine
/ digital-twin control — **same architecture**, wider scope.

### 4h. Adaptive worker pools (D32.12 — 3.2d refinement)

Today a pool size is `min(configured_limit, resource_limit)`. That can start 4 reader threads
for 2 documents — wasted threads and context switching. Make pool sizing **demand-aware**:

```
effective_pool = min(
    configured_limit,      # operator ceiling (env/config)
    resource_limit,        # what the Resource Manager currently allows
    queue_depth,           # work actually waiting
    work_item_count        # e.g. number of documents this round
)
```

Examples:

```
2 documents   → need only 2 readers → don't start 4 threads
100 documents → start the full 4 (still under caps)
```

This stays **deterministic**: given the same work count + same caps + same RM allowance, the
pool size is identical. It only ever sizes **down** from the ceiling, never above it.

### 4i. LLM capacity as a first-class resource (D32.11 — 3.2d refinement)

The LLM is a **scarce resource independent of CPU and RAM**. A 4B model on CPU can be the
single busiest lane while CPU% still looks modest. Today this is implicit
(`min(max_extract_workers, llm.max_concurrency)`). Make it **explicit**: the Resource Manager
owns an **LLM-lane token/semaphore** that heavy LLM tasks (planner, extract, summarize) must
acquire.

That unlocks smarter admission:

```
Qwen lane busy
  → do NOT admit another extraction
  → admit an OCR / download / HTML-read task instead (different resource)
```

- The lane count defaults to `llm.max_concurrency` (still **1** on this box), but this is not
  merely documentary: **all LLM-heavy work routes through the RM lane globally**.
- 3.2d intentionally changes default behavior: if the LLM lane is occupied, Atlas should
  avoid admitting another LLM task and should prefer eligible non-LLM work when available.
- When multiple local models exist later, each model family can be its own lane.
- Acquiring/releasing the lane through the RM is what lets non-LLM work (OCR, downloads,
  HTML reads) keep flowing while the model is saturated — smoother utilization, same
  determinism.

### 4j. Task cost model + budget admission (D32.10 — 3.2d foundation, Stage 4 learning)

Counting workers treats a cheap HTML read and an expensive LLM extraction as equal. Give each
task class a **typed cost** and admit by **budget**, not headcount:

| Task | Cost (illustrative) | Dominant resource |
|------|---------------------|-------------------|
| Download PDF | 1 | Network |
| Read HTML | 2 | CPU (light) |
| Embedding | 6 | CPU + RAM |
| OCR PDF | 8 | Heavy CPU + RAM |
| LLM extraction | 15 | LLM lane + RAM |

Admission becomes:

```
current_budget = profile_budget − sum(cost of in-flight tasks)
admit next task  iff  cost(task) ≤ current_budget
```

```
Can I admit another cost-15 LLM task?  → No
Run three cost-2 HTML reads instead.   → Yes  (smoother utilization)
```

Costs start as **static constants** (config-tunable) in **3.2d** and later become **learned**
per-machine values (§4g). Budgets are derived from the active profile’s CPU/RAM targets.
Determinism holds because costs and budgets are fixed for a given profile + machine profile.

### 4k. Execution Planner (D32.9 — 3.2d kernel package)

Insert a thin **Execution Planner** between the Scheduler and the Resource Manager so the two
concerns stay separate as they grow. This is a **kernel package** from the start
(`atlas/core/execution/`), not a research-local coordinator, because it must eventually serve
all jobs and long-running workers:

```
            Scheduler            "I have work."
                │
        Execution Planner        "This is what should run next" (deps, priority, cost order)
                │
         Resource Manager        "You may run two more readers / no LLM slot right now"
                │
             Workers             execute
```

- **Execution Planner** decides *what* is eligible to run next — dependency order, priority,
  and cost-aware ordering (e.g. drain cheap tasks while the LLM lane is busy).
- **Resource Manager** decides *whether* enough resources exist to run it right now.

Keeping these apart prevents the Resource Manager from slowly absorbing scheduling logic (the
review’s main structural concern). The Execution Planner is **deterministic**: same ready-set +
same costs → same next-task ordering (ties broken by `source_id`, D32.4).

**3.2d scope:** build the kernel package, deterministic ready-task ordering, static cost
lookup, and admission handshake with the RM. **Stage 4 scope:** broaden task inventory across
more workers and replace/tune static costs from observed machine history.

### 4l. Async Job Planner + operator visibility (D32.15–D32.18 — 3.2e)

**Problem (observed live):** Job create currently does:

```
POST /v1/jobs
  → insert job row (status=queued)
  → synchronously call LLM JobPlanner.decompose()   ← can wait 5–15+ minutes
  → create steps + enqueue
  → return 200
```

Live evidence (2026-07-17): `POST /v1/jobs` took **~900s** while Ollama held the single LLM
lane (planner timed out after `llm.timeout`; a concurrent chat also ran ~870s). UI showed
`queued` with **no steps and no activity** — then jumped to `running` after the timeout
fallback. The planner must stay; the **blocking create path** must not.

**Target flow:**

```
POST /v1/jobs  → 200 in milliseconds
  → job exists with phase=planning (or status reflecting planning)
  → background task: wait for planner lane → LLM decompose → validate
  → on success: persist steps, enqueue work, phase=queued/running
  → on timeout/failure: deterministic fallback (unchanged), then enqueue
  → activity stream narrates every transition
```

| Principle | Detail |
|-----------|--------|
| **Keep the planner** | LLM decompose remains the preferred path; deterministic plan stays fallback only |
| **Never block create** | `POST /v1/jobs` returns as soon as the job row exists and planning is scheduled |
| **Visible phases** | Operator sees `submitted → planning_queued → planning → queued → running` (status and/or `phase` field) |
| **Activity honesty** | Emit lines for lane wait, planner start, elapsed, timeout, fallback, steps ready |
| **Bounded planner lane** | Dedicated RM LLM lane class for short planner requests (strict output tokens, shorter timeout); do **not** blindly raise global Ollama concurrency on CPU-only boxes |
| **Scheduling parallelism** | Multiple jobs may be *planning_queued* concurrently; actual generation still respects lane capacity. Prefer priority/scheduling over unrestricted parallel inference |

**Not 3.2e:** removing `jobs.llm_decompose`, skipping planner for research objectives as the
default product behavior, or assuming multi-model parallel generation is free on this host.

---

## 5. What we are *not* optimizing for

- ❌ Fastest possible answer at any quality cost
- ❌ “Maximize CPU usage” as a goal
- ❌ Random worker counts / nondeterministic merge order
- ❌ Rewriting the research *quality* loop before the *execution* model (unless a bug blocks honesty)
- ❌ Browser paywall conquest as a Stage 3.2 prerequisite (still deferred unless it blocks readers)

---

## 6. Committed build order (everything here gets built)

Phasing is **order and safety**, not scope cut. 3.2d completes the resource-aware execution
foundation; **3.2e** makes job create honest and non-blocking (shipped); Stage 4 learns/tunes costs.

### 3.2a — Reader robustness (START HERE)

**Goal:** acquired docs → usable text **or** explicit surfaced failure (never silent empty).

| Deliverable | Detail |
|-------------|--------|
| Type detect + router | Sniff path/URL/content-type → choose PDF / HTML / text / PDF-OCR |
| Extend `Document` | `reader_id`, `format`, `quality`, `failure_reason`, warnings; keep `read_method` |
| Bibliography | Propagate DOI/citation/authors/year/venue from `Paper` → `Source` + `Document.metadata` |
| arXiv prefer ar5iv | When acquiring arXiv abs/pdf, try ar5iv HTML for richer text (A32.4) |
| Full PDF OCR fallback | If PDF text is empty/insufficient: render pages → OCR each page under OCR caps → normalize/merge text → extract claims. Surface per-page and document failures |
| Surface failures | Activity + workspace manifest/notes + pipeline/result errors (D32.8) |
| Metrics | chars, reader used, empty/error counts per format in pipeline/usage |

### 3.2b — Concurrent document pipeline

**Goal:** multiple docs in flight under config caps; merge by `source_id`.

| Deliverable | Detail |
|-------------|--------|
| In-process pools | Parallel acquire/read/extract **inside** the research step (A32.1) |
| Config caps | `resources.*` + env overrides (D32.3) |
| Deterministic merge | Sort by `source_id` before group/verify/report (D32.4) |
| Progress safety | Persist docs/claims as each finishes (workspace already); don’t wait for all |

### 3.2c — Kernel Resource Manager (usable sketch)

**Goal:** kernel service exists and research asks it for pool sizes / profile.

| Deliverable | Detail |
|-------------|--------|
| Package | `atlas/core/resources/` — `manager`, `profiles`, thin `monitor` (CPU%/RSS; thermal/power when OS exposes them) |
| Profiles | conservative / balanced / maximum / overnight (D32.5) |
| API | `request` / `release` or `recommend_pool_sizes(profile, caps)`; **throttle on detected pressure** |
| Wire | Bootstrap registers `resources`; research uses it for 3.2b caps; activity notes “slowing for thermal/load” when triggered |
| Honesty | If sensors missing → report “not monitored”; still enforce env caps |

### 3.2d — Execution-aware resource refinement (SHIPPED)

**Goal:** complete the resource-aware execution foundation: Execution Planner, static task
costs, predictive admission, adaptive pools, global LLM lanes, and verified-work/hour.

| Deliverable | Detail | Decision |
|-------------|--------|----------|
| Kernel Execution Planner | New `atlas/core/execution/` package; deterministic ready-task ordering; separates *what should run next* from *may it run* (§4k) | D32.9 |
| Static task cost model | Configurable cost table for download/read/OCR/LLM/embed/report; budget admission uses costs instead of worker count alone (§4j) | D32.10 |
| Initial predictive admission | Before launching heavy work, check static expected RAM/LLM/cost budget against current RM allowance; defer if unsafe (§4j) | D32.13 |
| Adaptive worker pools | Clamp each pool to `min(caps, RM allowance, queue_depth, work_count)` (§4h) | D32.12 |
| LLM capacity as a lane | RM owns an explicit LLM-lane token; heavy LLM tasks acquire/release it; default behavior changes globally so non-LLM work can proceed while the lane is busy (§4i) | D32.11 |
| Optimization-target metric | Surface a coarse **verified claims / hour** signal in usage/activity so we optimize the right thing, not CPU% (§3, D32.14) | D32.14 |

**3.2d acceptance:** with 2 documents, ≤2 reader threads start; with the LLM lane held, another
LLM task is deferred and an eligible OCR/download/read task can still run; static costs are
visible/configurable; admission decisions are deterministic; usage reports a verified-work/hour
figure. Ordering unchanged (`source_id`).

### 3.2e — Async Job Planner + create visibility (SHIPPED)

**Goal:** keep LLM JobPlanner decompose, but stop blocking `POST /v1/jobs` and stop hiding
planning from the operator. Planning becomes a first-class, observable phase with a bounded
planner lane.

| Deliverable | Detail | Decision |
|-------------|--------|----------|
| Non-blocking create | Insert job + schedule planning; return job id immediately (ms) | D32.15 |
| Planning phase + activity | Expose planning phases; emit activity for lane wait / start / timeout / fallback / ready | D32.16 |
| Bounded planner lane | Short planner requests with strict output budget + planner-specific timeout; schedule many, generate within lane capacity | D32.17 |
| Deterministic fallback unchanged | On planner timeout/error, use existing deterministic plan; never leave a job without steps forever | D32.18 |

**3.2e acceptance:** creating a job while Ollama is busy returns in <2s with a visible
`planning`/`planning_queued` phase and activity; when the planner finishes or falls back,
steps appear and the job advances; UI never looks “frozen queued with no explanation” for
> a few seconds after submit.

### Stage 4 — Learned predictive RM depth

Stage 4 deepens what 3.2d establishes. The architecture is already predictive-capable; Stage 4
makes it smarter with broader monitors and learned machine-specific costs.

| Deliverable | Detail | Decision |
|-------------|--------|----------|
| Full monitors | disk / net / GPU / temp; richer allocator — same kernel service | (existing) |
| Learned machine costs | Replace/tune static costs from observed per-machine history (§4g) | D32.10 |
| Broader predictive admission | Use learned RAM/CPU/LLM/time estimates across all worker families; improve back-off and hysteresis | D32.13 |
| Planner breadth | Extend Execution Planner beyond research document work to all long-running job families | D32.9 |

---

## 7. Decisions (LOCKED 2026-07-17)

| ID | Locked resolution | Status |
|----|-------------------|--------|
| **D32.1** | **(B)** Readers + light concurrency in 3.2; RM starts as kernel skeleton in 3.2c, then gains execution/cost refinement in 3.2d; Stage 4 learns/tunes | ✅ |
| **D32.2** | Extend existing research `Document` (not a new parallel type) | ✅ |
| **D32.3** | In-process pools + **user caps via `resources` config/env** | ✅ |
| **D32.4** | Sort by stable **`source_id`** before group/verify/report | ✅ |
| **D32.5** | **Balanced** default; Overnight selectable (env + optional per-job); +1/+2 workers only within env max — never fail on full pools | ✅ |
| **D32.6** | Resource Manager = **kernel service** | ✅ |
| **D32.7** | Generic + ar5iv/PDF/**full OCR fallback** first; store **DOI, citation, easy meta** | ✅ |
| **D32.8** | **No silent failures** — surface every read/extract failure | ✅ |
| **D32.9** | **Execution Planner** is a distinct **kernel** layer (`atlas/core/execution/`) between Scheduler and Resource Manager (*what runs next* ≠ *may it run*). 3.2d. | ✅ |
| **D32.10** | **Task cost model**: typed per-class costs; admission by **budget**, not worker count. Static/configurable in 3.2d → learned later. | ✅ |
| **D32.11** | **LLM capacity is a first-class resource** — RM owns explicit global LLM lane/token(s); default behavior changes so non-LLM work can proceed while the model is busy. 3.2d. | ✅ |
| **D32.12** | **Adaptive worker pools** — clamp to `min(caps, RM allowance, queue_depth, work_count)`; only sizes down, stays deterministic. 3.2d. | ✅ |
| **D32.13** | **Predictive admission** — decide on *projected* static cost/RAM/LLM lane before launch, not after OOM. 3.2d foundation; learned estimates later. | ✅ |
| **D32.14** | **Optimization target = verified work / hour**, never CPU%. Never chase 100% utilization. 3.2d surfaces the metric. | ✅ |
| **D32.15** | **Async job create** — `POST /v1/jobs` must not wait on LLM decompose; schedule planning in background and return immediately. 3.2e. | ✅ |
| **D32.16** | **Planning is visible** — explicit planning phase(s) + activity lines (lane wait, start, timeout, fallback, steps ready). Never silent `queued` for minutes. 3.2e. | ✅ |
| **D32.17** | **Bounded planner lane** — short planner requests (token/timeout budget) scheduled independently of long chat/research generations; do not blindly raise global Ollama concurrency on CPU-only hosts. 3.2e. | ✅ |
| **D32.18** | **Keep planner + fallback** — LLM JobPlanner remains preferred; deterministic decompose stays the timeout/error fallback. Do not remove or bypass the planner as the product default. 3.2e. | ✅ |

**Legend:** ✅ shipped.

---

## 8. Success criteria

1. Common OA PDF/HTML/ar5iv → text; scanned/image PDF automatically attempts full PDF OCR.
   A document ends empty only with a named `failure_reason` (no silent 0-claim void).
2. Failures visible in activity feed + durable workspace/result artifacts.
3. Confidence stays honest (LOW when thin); no fabricated certainty.
4. Under Balanced + raised caps, read/extract show real CPU/RAM movement vs today’s serial waits.
5. Merge/verify/report ordered by `source_id`; fixture tests stable.
6. Cancel/crash does not wipe already-written downloads/documents/claims.
7. Config/env caps respected; mid-job input still works; profile selectable.
8. DOI/citation present on inventory when scholar/HTML provided them.
9. Kernel `resources` service registered and used for caps/profile; when pressure is detected,
   Atlas slows work and surfaces it — never pretends the system is always safe.
10. Kernel `execution` service registered; ready-task ordering deterministic and distinct from
    Resource Manager admission.
11. Static task costs are configurable and used for initial admission decisions; unsafe/heavy
    tasks are deferred, not failed.
12. LLM capacity is enforced globally through RM lane tokens; when the lane is busy, another
    LLM task waits and eligible non-LLM work can proceed.
13. Effective pool sizes never exceed actual work / queue depth.
14. Per-job usage includes verified-work/hour when claims exist.
15. Job create returns promptly even when the LLM is busy; the operator can see a planning
    phase and activity while decompose runs (or times out to deterministic fallback).

---

## 9. Your answers (resolved)

| Topic | Answer |
|-------|--------|
| D32.1 | **B** + full plan stays committed |
| D32.2 | Improve existing `Document` |
| D32.3 | User-owned caps via config/env |
| D32.4 | `source_id` |
| D32.5 | Balanced default |
| D32.6 | Kernel service |
| D32.7 | Generic first + DOI/citation/easy meta |
| D32.8 | Surface every error |
| D32.9 | Execution Planner is a **kernel package** (`atlas/core/execution/`), not research-local |
| D32.10 | Implement the cost model permanently: static/configurable now, learned per-machine later |
| D32.11 | LLM capacity is global first-class capacity; 3.2d changes default admission behavior, not just documentation |
| D32.12 | Adaptive pools size down by actual work / queue depth |
| D32.13 | Initial predictive admission belongs in 3.2d; Stage 4 deepens with learned estimates |
| D32.14 | Optimize verified work/hour, not CPU% |
| D32.15 | Job create must be async w.r.t. LLM planner (return immediately) |
| D32.16 | Planning phase + activity must be visible to the operator |
| D32.17 | Bounded planner lane / scheduling parallelism — not unrestricted Ollama concurrency |
| D32.18 | Keep LLM planner; deterministic plan remains fallback only |

---

## 10. Decision log (append-only)

- **2026-07-17 — Document opened** (discussion; no code).
- **2026-07-17 — D32.1–D32.8 LOCKED.**
- **2026-07-17 — Plan FINALIZED for implementation.** Codebase-grounded blueprint (§11),
  implementation defaults A32.* (§12), remaining ambiguities (§13). **3.2a may start** once you
  say go; §13 items do not block 3.2a unless noted.
- **2026-07-17 — Clarifications locked:** PDF OCR included in 3.2a; global worker default 4;
  stable failure codes + human messages; LLM lane remains 1 by default; operator owns the live
  soiling acceptance run.
- **2026-07-17 — Q8 locked:** OCR bounds 50 pages / 15 min / 300 DPI (env); over-limit →
  `partial` not fail. Large-document chunked/multi-pass reading is a future expansion, not abandoned.
- **2026-07-17 — Plan clear to implement.** No blocking ambiguities remain; start at 3.2a.
- **2026-07-17 — 3.2a implemented:** extended `Document`/`Source`, ar5iv preference, PDF→OCR
  fallback (`pdftoppm`+Tesseract), failure codes surfaced in activity, `resources` config,
  tests green. Next: 3.2b concurrency.
- **2026-07-17 — 3.2b implemented:** `ThreadPoolExecutor` pools inside research (acquire +
  extract) under env/config caps; deterministic `source_id` merge; job scheduler unchanged
  (no Celery). Next: 3.2c Resource Manager.
- **2026-07-17 — 3.2c implemented:** `atlas/core/resources/` ResourceManager + profiles +
  thin CPU/RAM/thermal monitor; recommend_pool_sizes / request-release; detect→slow (never
  fail); honest posture when sensors missing; wired into bootstrap + research rounds.
  Stage 3.2a–c baseline complete for operator use; 3.2d refinement remains next.
- **2026-07-17 — Architecture-review alignment (plan only, no code):** external review scored
  the Stage 3.2 architecture very highly and recommended evolving the RM **reactive →
  predictive**. Folded in as **D32.9–D32.14**: Execution Planner layer (D32.9), task cost
  model + budget admission (D32.10), LLM capacity as a first-class lane (D32.11), adaptive
  worker pools (D32.12), predictive admission (D32.13), and the explicit optimization target
  = verified-work-per-hour, never CPU% (D32.14).
- **2026-07-17 — Q9–Q12 locked; 3.2d finalized:** Execution Planner will be a kernel package
  (`atlas/core/execution/`); cost model is permanent/static-config first, learned later; verified
  work/hour is per-job first; LLM lane changes default global behavior. 3.2d now includes the
  kernel Execution Planner, static cost model, initial predictive admission, global LLM lane,
  adaptive pools, and per-job verified-work/hour. Clear to implement when operator says go.
- **2026-07-17 — 3.2d implemented:** added kernel `atlas/core/execution/` (deterministic
  planner + permanent static-first task cost model); Resource Manager projected cost/RAM/LLM
  admission and global LLM lane ownership; role-aware LLM cost accounting; nested
  `resources.costs.*` / `resources.budgets.*` config/env overrides; adaptive acquire/extract
  pools; research execution ordering/admission visibility; per-job verified-work/hour.
  Registered `resources` + `execution` as kernel services. Full suite: **917 passed**.
- **2026-07-17 — Live create delay diagnosed; 3.2e locked:** `POST /v1/jobs` blocked
  ~15 minutes on planner-role Ollama (`ReadTimeout` after lane contention with chat). Operator
  saw silent `queued` with no steps/activity. **Agreed fix (keep planner):** async create,
  visible planning phases + activity, bounded planner lane with scheduling parallelism, keep
  deterministic fallback. Locked as **D32.15–D32.18** / phase **3.2e**. Do **not** remove or
  bypass the planner as the default product behavior.
- **2026-07-17 — 3.2e implemented:** `POST /v1/jobs` returns immediately with
  `phase=planning_queued` + planning activity; background `plan_job` runs LLM decompose with
  `jobs.planner_timeout` / `planner_num_predict`; on timeout/error uses deterministic fallback;
  then enqueues `advance_job`. API/UI expose `phase`; recovery re-plans jobs without steps.
  Restart `atlas serve` to pick up.

---

## 11. Implementation blueprint (grounded in current code)

### 11.1 Current baseline (facts)

| Area | Today |
|------|--------|
| Research `Document` | `atlas/research/reader.py` — `source_id`, `title`, `url`, `content_type`, `text`, `sections`, `metadata`, `read_method`, `truncated` |
| Read path | `Reader.read_path` → `ingestion.extractors` (pypdf, BS4 HTML, …); empty → `READ_NONE` |
| Acquire | `Librarian.acquire` — **serial** `_acquire_one` (`atlas/research/acquire.py`) |
| Extract | `ClaimExtractor` — **serial** loop in `ResearchService._research_deep` |
| Jobs | One `research` **JobStep**; no per-document steps; concurrency is **across jobs** via scheduler |
| DOI | On scholarly `Paper`; **dropped** in `Paper.as_source()` — evidence `Source` has no DOI |
| OCR | Image-only capability (`atlas/ocr/`); **not** wired into research PDF path |
| Config | `defaults.yaml` + `ATLAS_<SECTION>_<KEY>`; no `resources` section yet |
| LLM lane | `llm.max_concurrency` default **1** |

### 11.2 3.2a — files & work

| Touch | Work |
|-------|------|
| `atlas/research/reader.py` | Extend `Document`; router helpers; quality / failure_reason; richer HTML/PDF paths; PDF→page→OCR fallback |
| `atlas/research/acquire.py` | Type detect; ar5iv preference; record failures; pass biblio into Document/Source |
| `atlas/ocr/` + PDF renderer | Reuse Tesseract engine; add bounded page rendering and deterministic page-order text merge |
| `atlas/search/scholarly.py` + `atlas/evidence/models.py` | Preserve DOI/citation/authors/year/venue on `Source` (extend frozen dataclass carefully) |
| `atlas/research/service.py` | Surface read/extract failures in activity + pipeline; never swallow |
| `atlas/jobs/workspace.py` | Manifest fields for reader/quality/error/doi as needed |
| Tests | Fixtures: good HTML, empty PDF, ar5iv-like HTML, failure surfacing |

**3.2a acceptance (tests + one live OA smoke):** every acquired fixture ends with either
`chars > 0` or non-empty `failure_reason` + activity line.

### 11.3 3.2b — files & work

| Touch | Work |
|-------|------|
| `atlas/research/service.py` / acquire | Parallel document work under caps; barrier before group/verify |
| `atlas/config/*` + `defaults.yaml` | `resources` section |
| `.env.example` | Document `ATLAS_RESOURCES_*` + note on `ATLAS_LLM_MAX_CONCURRENCY` |
| Determinism | Collect results → `sorted(..., key=source_id)` → group/verify/report |

**3.2b acceptance:** unit test with fake slow readers proves overlap; ordering stable by
`source_id`; caps never exceeded.

### 11.4 3.2c — files & work

| Touch | Work |
|-------|------|
| `atlas/core/resources/` | New: manager + profiles + thin CPU/RSS monitor |
| `atlas/kernel/bootstrap.py` | Register `resources` service |
| Research | Ask RM for effective pool sizes given profile + config caps |

**3.2c acceptance:** changing profile/caps changes recommended pool sizes; research honors them.

### 11.5 3.2d — files & work

| Touch | Work |
|-------|------|
| `atlas/core/execution/` | New kernel package: planner, task/cost model, deterministic ordering, admission result types |
| `atlas/core/resources/` | Add explicit LLM-lane token(s), static cost-budget admission helpers, projected-cost checks |
| `atlas/config/manager.py` + `config/defaults.yaml` | Add `resources.costs.*` / `resources.budgets.*` defaults and env overrides |
| `atlas/kernel/bootstrap.py` | Register `execution` service; wire it with `resources` and scheduler-facing services |
| `atlas/research/service.py` | Use Execution Planner + RM admission for document work; use adaptive pool sizes; do not start more workers than queued work |
| `atlas/jobs/service.py` / workspace usage | Surface verified-work/hour in result/usage where claims exist |
| `.env.example` | Document cost/budget knobs and LLM lane behavior |
| Tests | Adaptive pools, LLM lane held → LLM task deferred + non-LLM admitted, static cost admission, deterministic ordering |

**3.2d acceptance:** Execution Planner is a kernel service; static costs are configurable;
research uses adaptive pools; LLM capacity is globally enforced; admission decisions are
deterministic and visible; reports/usage include verified-work/hour when claims exist.

### 11.6 3.2e — files & work

| Touch | Work |
|-------|------|
| `atlas/jobs/service.py` | Create job row + enqueue `plan_job` (or equivalent) without awaiting LLM; persist steps after planning completes |
| `atlas/jobs/planner.py` | Keep LLM + deterministic paths; add planner-specific timeout/token options; emit progress hooks for activity |
| Job status / schemas / API | Add planning phase field and/or statuses; surface on `GET /v1/jobs/{id}` and list |
| Activity / workspace | Lines for planning_queued, planning started, lane wait, timeout, fallback, steps ready |
| RM / LLM lanes | Bounded planner lane class distinct from long research/chat generation where practical |
| Console UI | Show planning phase + latest planning activity so create never looks frozen |
| Tests | Create returns fast with busy/fake LLM; activity/phase transitions; timeout → deterministic steps |

**3.2e acceptance:** with a stuck/slow LLM stub, `POST /v1/jobs` returns in <2s; job shows
planning phase + activity; after timeout or success, steps exist and the job can run.

### 11.7 Explicitly out of 3.2 code (still in long-term plan)

- Publisher-specific scrapers (IEEE/Springer/Elsevier) unless a live gap forces one
- Per-document `JobStep` rows / section & claim task graph
- Learned per-machine cost calibration / richer thermal tuning (Stage 4) — static costs and
  first-pass predictive admission are in 3.2d
- Browser paywall conquest (unchanged deferral)
- Removing LLM JobPlanner / default-bypass for research objectives (explicitly rejected — D32.18)

---

## 12. Locked implementation defaults (A32.*)

These close “how do we build it?” without waiting. Override only if you disagree in §13.

| ID | Topic | Locked default |
|----|-------|----------------|
| **A32.1** | Document concurrency model | **In-process pools inside the research JobStep** (not per-doc JobSteps in 3.2) |
| **A32.2** | Threads vs processes | **Threads first** (`ThreadPoolExecutor`); process pool only if OCR/PDF proves GIL-bound later |
| **A32.3** | Scanned PDF / OCR | **Full implementation in 3.2a:** detect weak/empty PDF text → render pages → Tesseract OCR under caps → merge by page number → normal extraction. Surface partial/page failures. **Default safety bounds (Q8):** 50 pages / 15 min / 300 DPI via `resources` env — excess → `quality=partial` + reason, not job failure. **Later:** raise limits and/or chunked multi-pass OCR so large documents complete across sessions |
| **A32.4** | arXiv text | On acquire, **prefer ar5iv HTML** when abs/pdf identity is known; fall back to PDF/abstract with surfaced reason |
| **A32.5** | Config keys | `resources.*` / `ATLAS_RESOURCES_*` as in §4f (final) |
| **A32.6** | Profile selection | Default from `resources.profile`; override via env; **optional** `resource_profile` on `POST /v1/jobs`. Overnight may prefer +1/+2 workers only within env max; never fail the job for full/busy pools |
| **A32.7** | “≥80% OA” metric | Soft target on **fixture suite**, not a live-web SLA |
| **A32.8** | Section/claim tasks | **Deferred** after 3.2 document concurrency |
| **A32.9** | LLM interaction | `effective_extract_workers = min(resources.max_extract_workers, llm.max_concurrency)` |
| **A32.10** | Where DOI lives | Extend evidence **`Source`** + copy into **`Document.metadata`**; stop dropping in `Paper.as_source()` |
| **A32.11** | `quality` values | `full` \| `partial` \| `empty` \| `blocked` \| `error` |
| **A32.12** | 3.2c RM thinness | Profiles + caps + CPU%/RSS; thermal/power sensors when readable; **detect → slow down** (never fail job); honest “not monitored” if sensors absent |
| **A32.13** | Global worker default | **4** total worker threads; operator may override via `ATLAS_RESOURCES_MAX_WORKER_THREADS` |
| **A32.14** | Failure taxonomy | Stable machine codes + human message (`needs_ocr`, `ocr_failed`, `paywall`, `parse_error`, `empty_text`, `timeout`, …) |
| **A32.15** | Live acceptance ownership | Atlas does **not** auto-submit the soiling job. After 3.2a+b, hand control to the operator to submit, watch, and judge the run |
| **A32.16** | Capacity under profile | Full pools / env max reached → **queue or degrade**, never job failure. Profiles never override operator caps |
| **A32.17** | Protection honesty + throttle | Surface what is protected vs not. When thermal/power/CPU/RAM pressure is detected → **slow the process** (fewer workers / pause admit) until safe; never pretend always-safe |
| **A32.18** | Execution Planner location | New kernel package: `atlas/core/execution/`; registered in bootstrap as `execution` |
| **A32.19** | Static task costs | Add config defaults for task classes (`download`, `read_html`, `read_pdf`, `ocr_pdf`, `llm_extract`, `embedding`, `verify`, `report`). Values are conservative and operator-tunable |
| **A32.20** | Initial cost budgets | Budget admission uses active resource profile + caps; if a task does not fit, it is deferred/queued, never failed |
| **A32.21** | LLM lane behavior | All planner/extract/summarize LLM calls that enter worker orchestration acquire an RM LLM lane. If lane is busy, prefer eligible non-LLM work. This changes default behavior globally |
| **A32.22** | Adaptive pool sizing | Effective pool size = `min(config_cap, rm_allowance, queue_depth, work_count)`; never above operator caps |
| **A32.23** | Verified-work/hour metric | Per-job first: compute from verified/graded claim count and elapsed research duration; machine-wide rolling metric deferred |
| **A32.24** | Learned costs | Deferred to Stage 4; 3.2d stores enough observations to make learning possible later, but decisions use static costs |
| **A32.25** | Job create vs planner | **Async:** create returns after job row + planning task scheduled; never await LLM in the HTTP handler |
| **A32.26** | Planning visibility | Prefer a `phase` field (`planning_queued` / `planning` / `ready`) while keeping familiar job `status`; Console must show phase + latest activity |
| **A32.27** | Planner request shape | Strict JSON, low max tokens, no think, planner-role timeout default **60s** (config), separate from general `llm.timeout` if needed |
| **A32.28** | Planner parallelism | Many jobs may wait in planning queue; at most lane-capacity concurrent planner generations (default still 1 on this host) |
| **A32.29** | Planner failure path | Timeout/error → existing deterministic `JobPlanner` fallback → create steps → enqueue; always emit activity explaining the fallback |

---

## 13. Resolved clarifications (no remaining ambiguities)

None blocking. **3.2a–3.2e are implemented.** Stage 4 is next for learned costs / broader monitors.

| # | Ambiguity | Options | Recommendation | Blocks |
|---|-----------|---------|----------------|--------|
| *(none blocking)* | — | — | Stage 3.2 complete for operator use | — |

### Resolved in the 2026-07-17 architecture-review alignment

- **Q9:** Execution Planner lives in a new **kernel package**: `atlas/core/execution/`. This is
  better for all jobs and long-term stability than a research-local coordinator.
- **Q10:** Cost model is implemented permanently: **static/configurable costs now**, learned
  per-machine costs later. Static is not throwaway; it is the first version of the permanent
  model.
- **Q11:** verified-work/hour starts **per-job**. Machine-wide rolling metrics come later.
- **Q12:** LLM lane changes **default global behavior**. It is not just additive documentation:
  LLM-heavy work must acquire the lane, and eligible non-LLM work may proceed while the lane is
  busy.

### Resolved in the 2026-07-17 async-planner agreement (3.2e)

- **Keep the JobPlanner** (LLM decompose preferred). Do not remove or default-bypass it.
- **Create must not block** on decompose; planning runs in the background.
- **Operator must see** planning phase + activity (lane wait, start, timeout, fallback).
- **Parallelism = scheduling**, not unrestricted parallel Ollama generation on CPU-only hardware:
  bounded planner lane + queue of planning jobs.
- Deterministic fallback remains when the planner times out or errors.

### Resolved in the 2026-07-17 clarification

- **Q1:** keep `llm.max_concurrency=1` by default; operator may deliberately raise it for
  Overnight/Maximum.
- **Q2:** Overnight via **env + optional per-job field**. May use +1/+2 workers only within
  env max; if no free threads / max already hit → wait/queue/slower — **never fail the job**.
- **Q3:** PDF OCR is **part of 3.2a**, not a future follow-up.
- **Q4:** default global worker-thread ceiling is **4**, not 8.
- **Q5:** If thermal/power (or severe CPU/RAM) pressure is **detected**, Atlas **slows down**
  to protect the system — fewer workers / pause new heavy work; job does **not** fail. If
  sensors are unavailable, say so honestly and rely on env caps. Richer sensor tuning in Stage 4.
- **Q6:** stable failure codes plus a human-readable message.
- **Q7:** operator personally submits and observes the live soiling acceptance job. Atlas
  prepares the implementation and results visibility but does not start that job automatically.
- **Q8:** OCR defaults **50 pages / 15 minutes / 300 DPI** (env-configurable). Over-limit docs
  become `partial` with a clear reason — not failed. Future work: higher limits and chunked
  multi-pass reading so very large documents can finish across sessions.

### Clarifications already folded in (no longer ambiguous)

- Entire plan stays committed (not “B then drop RM”).
- Caps are user-owned via config/env.
- Errors must be surfaced (no silent failures).
- Determinism = `source_id` sort.
- Prefer extending types over inventing parallel models.
- Kernel RM (not research-only helper).
- Document concurrency in 3.2 = **in-process pools**, not per-doc JobSteps.
- Config section name = `resources` / `ATLAS_RESOURCES_*`.
- Overnight never overrides env max; capacity pressure → slower, not failed.
- Resource protection is honest: detect pressure → slow down; missing sensors → say so (no pretend-safe).

---

## 14. One-line summary

> Atlas becomes a **robust, multi-format research pipeline** with a kernel Execution Planner,
> predictive Resource Manager admission, adaptive pools, explicit LLM capacity, async visible
> job planning, and operator-owned caps — staying honest, deterministic, and optimized for
> verified work completed, not CPU burned.
