# Atlas — Stage 2 Plan & Discussion (Research, Execution & Continuous Learning System)

> **Status:** 🟢 BUILDING — **Sprints 10–19 shipped ✅**
> (Chat-Mode spine + capability contracts + **Job Engine** + **Document Reader** +
> **resilient net layer** + **Web Search + Downloader** + **Code Understanding** +
> **Verification Engine + Evidence Graph** + **Python Execution Sandbox** +
> **Non-blocking HITL & Report Generator** + **Deeper Research: Scholarly + YouTube** +
> **Learning Pipeline (Experience store, governed)** +
> **Engineering Intelligence (Code store L2–L5, Personal Coding Assistant)**;
> 573 tests).
> Plan finalized (D1–D13, R1–R4; Q1–Q10 resolved).
> Next: **S20 — Tier 2/3 tools** (browser automation, OCR, Git, DB, Email/LinkedIn — as needed).
> **Started:** 2026-07-11
> **Source vision:** `docs/stage-2.txt` (the "inflection point" discussion) +
> the Continuous-Learning extension (§1b, D11).
> **Builds on:** Stage 1 = Sprints 1–9 (see `docs/IMPLEMENTATION_PLAN.md`).
> **Purpose:** This is the *living* record for Stage 2 — the pivot from "we built an
> operating system" to "Atlas is a deterministic **research, execution & continuous
> learning** assistant" — a *Continuous Engineering Intelligence System* that gets
> more useful every month. It tracks the discussion (open decisions), the agreed
> architecture, the roadmap, and the implementation progress as it lands.

---

## 0. How to use this document

- **§4 Open Decisions** is where we discuss. Each has options + a recommendation +
  a status (`OPEN` / `LOCKED`). Nothing is built until the gating decisions are `LOCKED`.
- **§6 Roadmap** is the sprint sequence; it firms up as decisions lock.
- **§7 Decision Log** and **§8 Progress Log** are append-only history.
- Sprint numbering continues from Stage 1 (next is **Sprint 10**). Web UI (old
  "Sprint 10") is re-slotted per this plan.

---

## 1. The pivot

Stage 1 built the **operating system**: kernel, capability + tool registries, DI,
durable scheduler, services (LLM, knowledge/RAG, memory, ingestion, backup), two
agents (RAG + ReAct), plugins (filesystem, web), REST API + CLI + auth, telemetry.

`stage-2.txt` argues we're at an inflection point. Two framings appear in it, and
they are **layers of the same system**, not alternatives:

1. **Interactive Assistant** (Chat Mode) — Atlas should hold a *conversation* with
   memory, detect intent, route to a capability, execute, and explain what it did.
   The "framework → working AI OS" line is crossed when it can do 5 things
   end-to-end (see §3 acceptance).
2. **Research & Execution System** (Research / Autonomous Mode) — Atlas accepts a
   *job*, decomposes it, gathers **evidence** (web, papers, YouTube, datasets),
   runs analysis (Python), pauses for the human when blocked (login/CAPTCHA),
   verifies, and delivers a **cited report** — over minutes or hours, deterministic
   over fast. Completed jobs become knowledge for next time.
3. **Continuous Learning System** (Continuous Engineering Intelligence) — every
   completed task, codebase, document, paper, experiment, bug fix, and design
   decision **may** become part of Atlas's long-term engineering knowledge. Atlas
   doesn't just answer today's question; it continuously improves its understanding
   of *your* engineering practices, coding style, architecture, and domain. Learning
   is cumulative, governed, and reversible (see **§1b**, **§5d**). This is the layer
   that makes Atlas compound over time.

> **North star (extended):** *"You are not building an AI chatbot. You are building
> an AI Research, Execution **& Continuous Learning** System. The LLM is just one
> component."* The correct next sprint is **not** Browser — it is the **Planner + Job
> spine** that turns a bag of tools into an intelligent researcher; the layer that
> makes it *durable* is **continuous learning** — Atlas becomes more useful every
> month.

Central principle, reinforced: **Atlas revolves around capabilities, not services.**
An agent says *"I need to extract text / search / execute Python / learn from this"*;
the kernel resolves *who* provides it. Plugins are swappable implementations of
**capability contracts** (`SearchCapability`, `DocumentCapability`,
`ExecutionCapability`, `CodeCapability`, **`LearningCapability`**, …). The
`LearningCapability` sits one level higher than the rest: it doesn't *read* files —
it *learns* from whatever the other capabilities produce (see §5d).

### 1a. Operating requirements (LOCKED — apply to the whole Job Engine)

These are hard requirements from the user, not options. Every Job-Engine sprint
(S12+) must honour them, and the S10 spine must not preclude them.

- **R1 — Multiple concurrent jobs.** Atlas runs many jobs at once (queued +
  in-flight), each with its own objective/steps/progress. Jobs are isolated; a slow
  or blocked job never freezes another. (Built on the durable scheduler's worker
  pool.)
- **R2 — Capability honesty ("I can't do X → tell you why").** Atlas must never fail
  silently or fake a result. If a job/step needs a capability that is **not
  registered** (or a tool that errors unrecoverably), Atlas emits a **Capability Gap
  Report**: *what* is missing, *why* it was needed, *which* sub-task needs it, and
  *what building it would unlock*. This runs **twice**: a **pre-flight** check when a
  plan is created (list every required capability, flag the missing ones up-front),
  and at **runtime** if a step hits an unforeseen gap. The user uses this list to
  decide what to build next.
- **R3 — Non-blocking human-in-the-loop.** A blocker on one sub-task (login,
  paywall, CAPTCHA, manual download, a decision) **pauses only that sub-task**, not
  the job. Atlas marks the step `blocked` (with a clear "needs: login to IEEE" note),
  **continues every other independent step**, and finishes with the best partial
  result plus a **"blocked — needs you"** list. When the user unblocks (logs in /
  drops a file / answers), those steps **resume** and the report is updated. A job is
  only fully done when no `blocked` steps remain (or the user waives them).
- **R4 — Hardware envelope: multi-core CPU, NO GPU, RAM-bounded (16 GB now → 64 GB
  later).** Two consequences the design must respect:
  - **Parallelize I/O across cores, serialize the LLM.** Downloads, file parsing, web
    fetches, and other I/O/CPU-light steps run in parallel across cores (R1). But LLM
    inference is CPU-only and RAM-heavy, so **all LLM calls pass through a single
    "LLM lane" (semaphore, `llm.max_concurrency`, default 1)** — running two models at
    once would thrash RAM and be slower overall. Concurrency ≠ many LLMs at once.
  - **Model sizes must fit RAM, and swaps are expensive.** On 16 GB we use small
    models (4B–8B); switching models on CPU reloads weights (slow), so we lean on
    Ollama `keep_alive` and batch same-role work. Determinism/accuracy over speed
    (the stated philosophy) makes this acceptable. Bigger models (14B) unlock at 64 GB
    by editing config only (see LLM roles, D7).

### 1b. Continuous Learning (NEW — the third pillar, D11)

> **Atlas is not only a Research & Execution System. Atlas is a *Continuous
> Engineering Intelligence System*.**

Every completed task, codebase, document, research paper, experiment, bug fix,
design decision, and project **may** become part of Atlas's long-term engineering
knowledge. The goal is not merely to answer today's question but to **continuously
improve** Atlas's understanding of the user's engineering practices, coding style,
architectural decisions, research interests, and domain expertise. **Learning is
cumulative. Atlas becomes more useful every month.**

This is an **explicit architectural goal from the start**, not an implied future
feature — so the spine we build now (planner, capability registry, verification
engine, `CodeCapability`, evidence graph) is designed to *feed learning*, and every
sprint records what it contributes to the learning stores (§5d).

Two hard guarantees (elaborated in §5d):

- **Atlas never silently learns.** Every learning action is **explainable,
  reviewable, and reversible**. Promotion into long-term knowledge is *configurable*
  (see the Continuous Learning Policy, §5d.4).
- **Learning is governed.** Every learning event carries a policy — **Temporary /
  Project / Personal / Verified** (§5d.5) — so experimental ideas, outdated code, or
  unverified assumptions never silently become permanent "truth."

---

## 2. What we already have (Stage 1 → Stage 2 mapping)

We are **not starting from zero** — much of the substrate the doc asks for exists.
Honest mapping of current assets to Stage 2 needs:

| Stage 2 need (from doc) | Already have? | Gap to close |
|---|---|---|
| Capability registry | ✅ `kernel/capabilities.py` + **typed contracts** (`atlas/capabilities/`, S11): `contract`/`verify`/`missing` + catalog | Multi-provider selection still ahead |
| Tool catalog | ✅ `kernel/tools.py` `ToolRegistry` (name+callable+params) | No **ToolExecutor** (arg validation, retries, structured `ToolResult`) |
| Durable async execution | ✅ `scheduler` (crash recovery, retry/backoff, self-re-enqueue) | No **job-level** semantics (objective, steps, artifacts, `waiting_for_user`) |
| Tool-using agent | ✅ `ReActAgent` (reason→act→observe over ToolRegistry) | Single-shot; no conversation, no plan persistence, no evidence graph |
| Memory | ✅ `memory.items` (working/episodic/semantic, pgvector) | No **conversation session** wiring (working memory scoped to a chat) |
| Knowledge/RAG | ✅ ingest + chunk + embed + cited search | Ingestion limited to txt/md/pdf/html; no structured PDF understanding |
| Filesystem | ✅ `filesystem_plugin` (`fs.list`, `fs.read`, sandboxed) | Read-only; no write/copy/move/watch-as-tool, no recursive find |
| Web | ✅ `web_plugin` (`web.fetch` one URL → text) | No **web *search***, no downloader, no scholarly/YouTube |
| Evidence | ✅ RAG citations (per-answer) | No **evidence graph** (claim→sources→confidence) across a job |
| Human-in-the-loop | ⚠️ scheduler states (pending/claimed/running/…) | No `waiting_for_user` + notify + resume flow |
| Determinism | ✅ temp=0 defaults, durable ret/recovery | No cross-check / verify pass; no report pipeline |
| Conversation | ✅ `conversation.*` (S10: sessions/messages, context) | (store #5 of 5; see §5d) |
| **Code store** | ✅ `intelligence` cap (S19: `learning.repositories`/`patterns`) | Learned-repo structure + generalized patterns; graph-level connect deepens later |
| **Experience store** | ✅ `learning.experiences` (S18b) | problem→diagnosis→commands→mistakes→solution→lessons, lexical recall |
| **Learning** | ✅ `learning` + `intelligence` caps (S18b/S19, §5d) | Governed ledger + Experience & Code stores; knowledge/memory sinks land as needed |
| API/CLI/auth/telemetry | ✅ | Add job + conversation endpoints as those land |

**Takeaway:** Stage 2 is mostly **new orchestration on top of solid substrate**, not
a rewrite. The three genuinely new "brains" are: **Conversation**, **Planner**, and
the **Job Engine** — plus the **capability-contract** refactor that makes plugins
pluggable, and a set of **research plugins**.

---

## 3. Acceptance — "framework → working AI OS"

The doc's concrete bar. **Chat Mode slice** is done when Atlas does these five,
end-to-end, in one conversation, keeping context:

1. *"What documents do you know about?"* → lists knowledge base
2. *"Read this PDF."* → ingests it (extract→chunk→embed→knowledge)
3. *"What does it say?"* → answers from the just-ingested doc, with citations
4. *"Remember that I prefer PostgreSQL over Milvus."* → stores a preference
5. *"What do you remember about my preferences?"* → recalls it without a KB search

**Research Mode slice** is done when a job like *"Estimate soiling loss in solar PV
(data-driven)"* runs asynchronously: decomposes → searches/reads evidence → (pauses
for login if needed) → produces a **cited report** with confidence, and the job's
findings are ingested back into knowledge.

---

## 4. Open decisions (the discussion)

> Legend: **[REC]** = my recommendation. Update `Status` as we agree.

### D1 — Sequencing / entry point  ·  Status: ✅ LOCKED → (a) Chat-first, **Job Engine is the north star**
**Decision:** Build the Chat-Mode vertical slice first (option a), **but the final
target is the Job Engine.** Design constraint that follows: the Planner and
ToolExecutor built in S10 must be **mode-agnostic** — the same objects that drive a
synchronous chat turn must later drive an asynchronous job step. No chat-only
shortcuts that we'd have to unwind in S12.

How do we stage the work?
- **(a) Chat-Mode vertical slice first** [REC] — build the shared spine
  (Conversation + Planner v0 + ToolExecutor + ResponseBuilder) and ship the 5-test
  assistant. *Then* extend the same planner/executor into the async Job Engine.
  Fastest proof; every piece is reused by Research Mode.
- **(b) Job Engine first** — go straight for persistent async jobs + decomposition
  + HITL. More ambitious, slower to first visible payoff, higher risk.
- **(c) Pure hybrid** — build spine components generically with no "chat milestone,"
  wire jobs immediately.

*Why (a):* the Planner and ToolExecutor are shared by both modes; Chat Mode is the
cheapest way to prove them; the doc itself says "build one complete vertical slice"
before more infrastructure, *and* that the planner spine is the real next sprint —
(a) satisfies both.

### D2 — Planner v0 implementation  ·  Status: ✅ LOCKED → (a) Deterministic router first
**Decision:** Deterministic rule-based router for v0; LLM used only to compose
answers, not to route. Grow into hybrid LLM decomposition for research jobs (D2c) at S12+.
- **(a) Deterministic rule-based router first** [REC] — regex/keyword + capability
  match for common intents (list docs, ingest, ask, remember, recall, search web).
  Predictable, testable, no LLM latency. LLM used only for the *answer*, not routing.
- **(b) LLM planner** — the LLM decides the plan/tools (like ReAct today).
- **(c) Hybrid** [REC-later] — deterministic router for chat intents; LLM
  decomposition for open-ended *research* jobs (S12+). Start (a), grow into (c).

*Note:* we keep `ReActAgent` as one **execution strategy** the planner can invoke
for open-ended reasoning; the planner is the new front-of-house.

### D3 — Conversation persistence  ·  Status: ✅ LOCKED → (a) New `conversation` schema
**Decision:** First-class `conversation.sessions` + `conversation.messages` in
Postgres; working memory = `memory.items` scoped to the session id (reuse Sprint 6).
- **(a) New `conversation` schema** (`sessions`, `messages`) in Postgres [REC] —
  first-class, queryable, survives restarts; working memory = `memory.items`
  scoped to the session id (reuse Sprint 6). Clean separation of transcript vs facts.
- **(b) Reuse `memory.items` only** — store turns as memories. Simpler, but muddies
  "transcript" vs "remembered fact" and complicates recall.

### D4 — Scope/ambition to commit now  ·  Status: ✅ LOCKED → (a) Full arc (S10–S20)
**Decision:** Commit the full arc; build incrementally; revisit tail sprints
(browser/OCR/git/email) as we learn. Extended with the Continuous-Learning pillar
(D11): S18 Learning Pipeline + **S19 Engineering Intelligence**; former tools sprint → S20.
- **(a) Commit the full Research + Execution + Continuous-Learning roadmap**
  (S10–S20, §6) as the Stage 2 arc, build incrementally, revisit tail sprints as we
  learn [REC].
- **(b) Commit only Chat Mode + Job Engine core** (S10–S12); treat research plugins,
  evidence graph, HITL, reports as a *separate* Stage 3 decision.

### D5 — First research capability: Web Search provider  ·  Status: ✅ LOCKED (S13b)
- **(a) DuckDuckGo** (no API key; HTML endpoint) [CHOSEN] behind a `SearchCapability`.
- **(b) SearXNG** self-hosted meta-search (more control, an extra service to run).
- **(c) Paid API** (Brave/Serper/Bing) — best quality, needs key + budget.
**Decision (S13b):** ship **(a) DuckDuckGo** as the default keyless provider behind a
`SearchProvider` protocol + `SearchPlugin` (`web.search`). Providers are an **ordered
list** (`plugins.search.providers`): the first that returns results wins (**provider
fallback**); a `blocked`/`skipped`/`error` provider is skipped, so (b)/(c) drop in via
config without touching the planner. Every provider fetches through the shared
resilient net layer (D10), so a rate-limited/blocked backend degrades to a structured
outcome (R2/R3) instead of crashing.

### D6 — Python execution sandbox  ·  Status: ✅ LOCKED (shipped S16) — *hybrid*
**Decision (user):** **hybrid** — the executor targets a small ``SandboxBackend``
interface; the **subprocess backend is the default now** (child interpreter + `rlimit`
CPU/memory/file caps + hard wall-clock timeout that kills the process group + scratch
workdir + stripped env + **network disabled by default**), and a **Docker backend** is
swappable via config later for stronger isolation — without touching callers. Network
is **off by default** (opt-in per run); network needs go through Atlas capabilities.
Every run returns a structured outcome (`ok`/`error`/`timeout`/`blocked`), never a raw
crash (R2/R3). Computed results become **L5 evidence** in the graph (§5a.6). — §6h.

### D7 — LLM selection: roles, not a single model  ·  Status: ✅ LOCKED
**Decision (user):** Do **not** hard-wire a "research model." Configure **roles**;
callers ask `LLMService` for a *role*, never a model. `LLMService` resolves role →
(provider, model). Planning, reasoning, summarizing, coding, and vision are different
workloads and map to different models.

```yaml
llm:
  max_concurrency: 1          # R4: single LLM lane on CPU
  roles:
    chat:       { provider: ollama, model: qwen3:4b }
    planner:    { provider: ollama, model: qwen3:8b }
    researcher: { provider: ollama, model: qwen3:8b }   # 16GB now; deepseek-r1:14b / qwen3:14b at 64GB
    summarizer: { provider: ollama, model: qwen3:8b }
    code:       { provider: ollama, model: qwen3-coder }
    vision:     { provider: ollama, model: gemma3 }
```

- The Job Engine says *"I need a planner / researcher / summarizer"* — it never names
  a model. Only `LLMService` knows the mapping (swap models by editing config).
- **Current hardware (16 GB):** chat→`qwen3:4b`, everything heavier→`qwen3:8b`.
  **Later (64 GB):** researcher→`deepseek-r1:14b` or `qwen3:14b`, config-only change.
- Back-compat: today's single `llm.model`/`embedding_model` become the `chat` role +
  an `embed` role; existing call sites keep working during migration.
- **Introduced in S10** (roles registry in `LLMService`; wire `chat` + `embed`; others
  registered but unused until their sprint) so nothing downstream ever names a model.

### D8 — Verification is a first-class subsystem (evidence by *claim*)  ·  Status: ✅ LOCKED
**Decision (user):** Not "N sources per document." Atlas verifies **by claim**, using
**evidence quality + convergence**, via a dedicated **Verification Engine + Evidence
Graph** sitting between Research and the Report Generator. This is the feature meant to
distinguish Atlas: **defensible, evidence-backed conclusions over speed.** Full spec in
§5a. (Supersedes the earlier "2–3 sources" default.)

### D9 — Code understanding (how Atlas "reads code")  ·  Status: ✅ LOCKED → **Tier B**, own sprint (S14)
**Decision (user):** `CodeCapability` = **deterministic structural parsing
(tree-sitter)** + **code-aware chunking into knowledge/RAG** + **repo map** +
**symbol index** + **cross-file call graph + dependency analysis (Tier B)**, with the
**`code`-role LLM** (D7) for semantic explanation grounded on the parsed structure.
Its **own sprint (S14)**, right after the Document Reader.

> **Long-term intent (user):** Atlas should eventually become a real **coding
> assistant** that **gets better over time**. So `CodeCapability` is not one-shot: it
> feeds the **Learning pipeline** (S18) — repos read, patterns, conventions, and past
> reviews accumulate into knowledge/memory so future coding help improves. Design
> `CodeCapability` and its symbol/graph store to be *incrementally enrichable*, not a
> throwaway parse. (Full coding-assistant workflows — edits, PRs, test-running — are a
> later stage built on this foundation.)

### D10 — Resilient, polite web fetching  ·  Status: ✅ LOCKED (see §5c)
**Decision (user):** fetching must be graceful — respect each site's rules and never
let a rate-limit/block stall a job mid-way. Per-domain throttling, backoff+retry with
jitter, robots.txt + crawl-delay, response caching, provider fallback; on a hard block
the source is marked `blocked`/`skipped`, the job continues (R3), the gap is reported
(R2). Full spec in §5c.

---

## 4b. Ambiguities to resolve (finalization checklist)

Everything I could not infer unambiguously from the vision, with a **recommended
default** so the plan is buildable even before you confirm. `Gate` = the sprint by
which it must be settled. None block **S10** (chat spine); most gate the Job Engine.

| # | Ambiguity | Resolution | Gate | Status |
|---|-----------|------------|------|--------|
| **Q1** | **Job concurrency** | ✅ Many jobs at once (`jobs.max_concurrent`, default 3); steps sequential within a job in v1. **CPU-parallel I/O, single LLM lane** (R4). Fair scheduling by priority + age | S12 | ✅ Resolved |
| **Q2** | **Notification channel** | ✅ In-app first: `job.notifications` feed via API (`GET /v1/jobs`, `/v1/jobs/{id}`) + CLI (`atlas jobs`, `atlas job <id>`). Email/webhook later | S12 | ✅ Resolved |
| **Q3** | **Blocked-step resume (R3)** | ✅ Near-term: user supplies artifact/credential (watched folder / creds) → `atlas job resume <id>` re-runs blocked steps. In-browser login via Playwright at S20 | S17 | ✅ Resolved |
| **Q4** | **Artifacts storage** | ✅ `/data/atlas_data/jobs/<job_id>/artifacts/`; referenced in `job.artifacts`; retention config (default keep) | S12 | ✅ Resolved |
| **Q5** | **LLM model for research** | ✅ **Role-based selection** (D7) — not one model. `LLMService.for_role("researcher")`. 16GB→qwen3:8b; 64GB→deepseek-r1:14b (config-only). Job Engine never names a model | S10 (foundation) | ✅ Resolved |
| **Q6** | **Verification bar** | ✅ **SHIPPED (S15)** — **Verification Engine + Evidence Graph** (D8, §5a): verify by claim, evidence levels 1–5, confidence *calculated*, stop on convergence, per-job Evidence Budget. Supersedes "2–3 sources" | S15 | ✅ Resolved |
| **Q7** | **Secrets/credentials** | ✅ **Stay in `.env` / `/etc/atlas`** (existing secret pattern); never in DB or plaintext logs; per-capability config keys | S13 | ✅ Resolved |
| **Q8** | **Near-term document formats** | ✅ Base set: **pdf, docx, pptx, xlsx, csv, md, txt, html, json**. **Code files → dedicated `CodeCapability` (D9, §5b).** Engineering/CAD (LabVIEW, MATLAB, DWG/DXF, PSS/E) = later, on demand | S13/S14 | ✅ Resolved (code → D9) |
| **Q9** | **Web scraping ToS / rate limits** | ✅ **Resilient, polite fetching** (D10, §5c): per-domain throttle + backoff/retry, robots + crawl-delay, caching, provider fallback; a hard block marks that source `blocked`/`skipped` and the job **continues** (R3), gaps surfaced via R2 — **never stalls mid-job** | S13 | ✅ Resolved |
| **Q10** | **Autonomous Mode recovery** | ✅ Extend scheduler `recover_interrupted` to **re-hydrate running jobs on startup**; jobs already durable | S12 | ✅ Resolved |

> **Resolved:** Q1–Q10 (2026-07-11) — incl. CPU/no-GPU/16GB envelope (R4), role-based
> LLM (D7), verification subsystem (D8), env-only secrets (Q7), resilient fetching
> (D10, §5c), and code understanding (D9 / §5b, Tier B, S14). **No open decisions gate
> S10.** The only intentionally-deferred choices are D5 (search provider, gated S13)
> and D6 (Python sandbox, gated S16) — decided when their sprint arrives.

---

## 5. Target Stage 2 architecture

```
                            ┌──────────────────────────┐
        User (Chat / Job)──▶│         Planner          │  intent → plan (steps)
                            └────────────┬─────────────┘
                                         │ selects capabilities (not services)
                     ┌───────────────────┼────────────────────┐
                     ▼                   ▼                    ▼
             Conversation           Tool Executor         Job Engine
             (session/history/      (validate args,       (jobs/steps/artifacts,
              context, working      invoke, retry,         status incl. waiting_for_user,
              memory)               structured results)    pause/resume, progress)
                     │                   │                    │
                     └───────────────────┼────────────────────┘
                                         ▼
                              Capability Registry (contracts)
   Search │ Document │ Download │ Execution │ Memory │ Knowledge │ Code │ Learning │ Browser │ …
                                         │
                     implemented by Services + Plugins (swappable)
                                         │
   Research (gather) ─▶ Verification Engine ─▶ Evidence Graph ─▶ Report Generator ─▶ Learning
                        (convergence,           (claim → sources,   (cited, confidence,   Pipeline
                         confidence calc,        levels 1–5,          conflicting views)   (§5d)
                         evidence budget)        contradictions)                            │
                                                                                            ▼
        Five knowledge stores (governed, reversible — §5d):  Knowledge · Memory · Code · Experience · Conversation
        LearningCapability promotes activities → stores, at a Learning Level (Store→Understand→Connect→Generalize→Recommend)

   LLM lane (single, CPU): all model calls resolve a ROLE (chat/planner/researcher/summarizer/code/vision)
            through LLMService and pass a semaphore (R4) — never two models at once.

Modes:  Chat (answer now) · Research (take time, verify, report) · Autonomous (until done, across reboots)
        + Learning (governed promotion of any completed activity into long-term knowledge — §5d)
```

New building blocks (all reuse Stage 1 substrate):

- **LLM Roles** (`LLMService`, D7/R4): a role→model registry + a single concurrency
  lane. Callers use `llm.for_role("planner")`; the service resolves the model and
  serialises inference. Introduced in S10.
- **Conversation** (`atlas/conversation/`): `Session`, `History`, `Context`. Multi-turn
  state; working memory via `memory.items` scoped to the session.
- **Planner** (`atlas/planner/`): objective/message → ordered plan of capability calls.
  Deterministic first (D2a), LLM decomposition later (D2c).
- **Tool Executor** (`atlas/execution/`): wraps `ToolRegistry` — validates args against
  param hints, invokes, retries, returns a structured `ToolResult` (ok/err/data/evidence).
- **Job Engine** (`atlas/jobs/` + `job.*` schema): persistent, **concurrent** jobs
  (R1) on top of the scheduler; steps, artifacts, outputs, references; progress.
  **Step-state model:** `pending → running → done | failed | blocked | skipped`.
  `blocked` = needs the user (R3) and does **not** stop the job. Job states:
  `queued → running → completed | completed_with_blocks | failed | cancelled`.
- **Capability contracts** (`atlas/capabilities/`): typed protocols (`SearchCapability`,
  `DocumentCapability`, `DownloadCapability`, `ExecutionCapability`, `CodeCapability`,
  **`LearningCapability`**, …) registered in the existing `CapabilityRegistry`; the
  planner depends on contracts, not plugins. `LearningCapability` is the highest-level
  contract — it consumes what the others produce and promotes it into the stores (§5d).
- **Capability Gap Report** (R2): produced by the Planner at **pre-flight** (required
  vs registered capabilities) and by the executor at **runtime** (unrecoverable gap).
  Structure: `{missing_capability, needed_by_step, reason, unlocks}`. Surfaced on the
  job and via API/CLI so the user knows exactly what to build next. This is the
  system's honesty mechanism — no silent failure, no fabricated results.
- **Evidence Graph + Verification Engine** (`atlas/evidence/`, `atlas/verification/`):
  first-class subsystems — see **§5a**.
- **Report Generator**: scientific-review-style report (§5a.4).
- **Learning pipeline + `LearningCapability`** (`atlas/learning/`): governed promotion
  of any completed activity (job, repo, document, bug fix) into the **five knowledge
  stores** at a chosen **Learning Level** and **policy** — explainable, reviewable,
  reversible. First-class subsystem — see **§5d**.

---

## 5a. Verification Engine & Evidence Graph (D8 — the differentiator)  ·  ✅ SHIPPED (S15)

> *"Verify by claim, not by document. Optimize for defensible, evidence-backed
> conclusions, not speed."* A first-class subsystem between Research and Report:
> `Planner → Research → **Verification Engine** → **Evidence Graph** → Report`.

### 5a.1 The Claim (unit of truth)
Atlas never emits a raw conclusion; it emits **claims**, each an object:

```
claim:
  id:
  statement:            "Average annual soiling loss in South India ≈ 4%."
  value:                { number: 4.0, unit: "%", kind: "annual_mean" }   # when numeric
  supporting_sources:   [ {source_id, evidence_level, extracted_value, snippet, locator} ]
  contradicting_sources:[ ... ]
  confidence:           HIGH        # CALCULATED, not guessed (5a.3)
  last_verified:        2026-07-11
  verification_method:  "numeric convergence across L4/L3 sources"
  reasoning_trace:      [ step, step, ... ]   # how Atlas got here
```

Because claims are persistent objects, Atlas can **re-verify** later: a new paper
appears → re-evaluate confidence automatically.

### 5a.2 Evidence Levels (quality, not count)
| Level | Source type | Weight |
|-------|-------------|--------|
| **L5** | Measured field data / primary datasets | highest |
| **L4** | Peer-reviewed papers | high |
| **L3** | Government / national-lab reports (NREL, Fraunhofer, Sandia, PVPMC) | solid |
| **L2** | Technical blogs, manufacturer white papers | weak |
| **L1** | Forums, Reddit, LinkedIn | lowest |

### 5a.3 Confidence is *calculated*
Confidence is a function of **evidence quality + convergence + agreement**, e.g.:
- **HIGH** — multiple L3+ sources whose values **converge** within tolerance.
- **MEDIUM** — converging L2/L3, or few L4 with minor spread.
- **LOW** — sparse, low-level, or **contradicting** sources.

**Stopping rule = convergence, not a fixed paper count.**
- Converged: `3.7, 3.9, 4.0, 3.8 %` → tight cluster → **stop**.
- Diverged: `2, 11, 6, 4 %` → **keep searching** (need more/better evidence).

### 5a.4 Evidence Budget (per job, config + planner-tunable)
```yaml
research:
  min_sources: 5
  min_peer_reviewed: 3
  min_government: 1
  convergence: 0.90            # agreement threshold to stop
  max_search_iterations: 20
  max_tokens: ...
  timeout: ...
```
The Verification Engine checks the budget after each research round and tells the
planner **continue** or **stop**.

### 5a.5 Report structure (scientific-review style)
`Executive Summary → Answer → Confidence → Methodology → Evidence → References →
Conflicting Views → Limitations → Next Research`. Every numeric answer carries its
claim's confidence + supporting/contradicting sources.

### 5a.6 Responsibilities of the Verification Engine
Check numeric values across sources · detect contradictions · measure convergence ·
assign calculated confidence · enforce the Evidence Budget · decide *continue vs
finalize* before the Report Generator runs. Built in **S15**; Python-computed results
(S16) become **L5 evidence** feeding the same graph.

---

## 5b. Code Understanding (`CodeCapability`) — ✅ SHIPPED: Tier B, S14 (D9) — §6f

> Goal (from `stage-2.txt`, a *high* priority): Atlas shouldn't just read code as
> text — it should understand **functions, classes, imports, dependencies, call
> graph, and architecture**, across many languages. The winning combo is
> **deterministic structure + LLM semantics**: parse the code with a real parser
> (facts, no hallucination), then let the `code`-role LLM (D7, `qwen3-coder`) explain/
> review *grounded on those facts*.

### 5b.1 Layers
1. **Structural parse (deterministic) — [tree-sitter].** Per file → symbols
   (functions, classes, methods, imports/exports) with signatures, docstrings, and
   line ranges. One toolchain, many languages via prebuilt grammars.
2. **Repo map.** Directory tree + manifests (`pyproject.toml`, `requirements.txt`,
   `package.json`, `Cargo.toml`, `go.mod`, `Dockerfile`, `docker-compose.yml`) →
   dependencies, entry points, and inferred frameworks (Django/React from deps +
   layout) → an architecture overview.
3. **Code-aware chunking → knowledge/RAG.** Chunk at **function/class boundaries**
   (not fixed word windows), attach symbol metadata, embed → semantic **code search &
   Q&A** ("where is X defined?", "explain module Y") over the *existing* knowledge
   pipeline. This is the highest-value, lowest-risk piece.
4. **Symbol index + graph.** A symbols table (name/kind/file/line/lang) for fast
   lookup; **import graph** (file→file) **and cross-file call graph** (who calls whom)
   + **dependency analysis** — this is the **Tier B** scope locked for S14. Cross-file
   resolution is per-language and non-trivial, so it's built language-by-language
   (Python first), degrading to import-level where call resolution is unavailable.
5. **`code`-role LLM.** Explanation, review, architecture summaries — always grounded
   on the parsed structure to curb hallucination.
6. **Pattern Mining (feeds learning).** Beyond `Parse → Graph → RAG → LLM`, mine
   **recurring engineering patterns** across the user's repos: e.g. *"Jagadeshwar
   always uses the Repository pattern → service layer → UUIDs → pytest → Docker →
   structured logging → Postgres."* These become **reusable engineering patterns**
   promoted (governed) into the Code/Experience stores and surfaced by the Personal
   Coding Assistant (§5d, S19). This is what turns a code *reader* into a code
   *learner*.
7. **Fallback.** Unsupported language → plain-text ingest + LLM, flagged as shallow
   (honest per R2).

### 5b.2 Languages (v1 grammars)
Python, JavaScript, TypeScript, C, C++, Rust, Go, Java, SQL, Bash; config: Dockerfile,
YAML (compose), JSON, TOML. Django/React are *frameworks* on Python/JS — handled by
deps + layout heuristics, not separate parsers.

### 5b.3 Depth — LOCKED at **Tier B**
- ~~Tier A~~ — structural parse + repo map + code-aware RAG + symbol index + import graph.
- **Tier B [LOCKED for S14]** — Tier A **+ cross-file call graph + dependency
  analysis** (per-language, Python-first). Best for deep architecture review; the
  foundation for Atlas-as-coding-assistant that improves over time (structure feeds
  the S18 Learning Pipeline; **pattern mining** feeds S19 Engineering Intelligence).
- ~~Tier C~~ — plain-text + LLM only (kept only as the *fallback* for unsupported
  languages, per §5b.1 layer 6).

*Deps:* `tree-sitter` + a grammar pack (pure-CPU, fits R4). Contract: `CodeCapability`
(`parse`, `repo_map`, `index`, `search_symbols`, `graph`) registered in the
CapabilityRegistry. Placement: **own sprint S14**, right after the Document Reader.

---

## 5c. Resilient & polite web fetching (D10)

Every network capability (web fetch, search, downloader, scholarly) shares one
resilient HTTP layer so jobs **degrade, never crash**:

- **Per-domain rate limiting** + concurrency caps; honour `robots.txt` + `crawl-delay`.
- **Backoff + retry with jitter** on 429/503/timeouts (bounded attempts).
- **Response caching** (avoid refetch; cheaper reruns; determinism).
- **Provider fallback** (D5): if one search backend fails, try the next.
- **Polite identity:** descriptive User-Agent; obey `Retry-After`.
- **Hard block → graceful stop of *that source only*:** mark the step `blocked`
  (needs login) or `skipped` (unavailable) per **R3**, continue other sources, record
  the gap per **R2**. The job proceeds with whatever evidence it *can* gather and
  reports what it couldn't.

Built in **S13** as `atlas/net/` (a shared fetch client), used by every web-facing
plugin thereafter.

---

## 5d. Continuous Learning (D11 — the third pillar)

> *"LearningCapability doesn't read files. It learns."* Continuous learning is what
> turns Atlas from a tool that answers into a **Continuous Engineering Intelligence
> System** that compounds. It is built **on top of** everything else — the planner,
> capability registry, verification engine, `CodeCapability`, and evidence graph all
> already produce the raw material; §5d makes turning that material into durable,
> governed knowledge an explicit subsystem.

### 5d.1 `LearningCapability` (one level above the rest)
`SearchCapability` / `DocumentCapability` / `ExecutionCapability` / `CodeCapability`
*produce artifacts*. `LearningCapability` *consumes* those artifacts and **learns** —
transforming raw inputs into higher-level understanding:

```
PDF      → Knowledge (knowledge graph, concepts, citations)
Python   → Architecture  → Coding style  → Patterns
LabVIEW  → Dataflow      → DAQ design
MATLAB   → Algorithms    → Numerical methods
Job/bug  → Diagnosis     → Lessons learned
```

Every source contributes to learning. `LearningCapability` is the highest-level
contract in the registry (§5).

### 5d.2 The five knowledge stores
Stage 1 had **Knowledge / Memory / Conversation**. Stage 2 extends this to **five**:

| Store | Holds | Backed by |
|-------|-------|-----------|
| **Knowledge** | Research papers, documentation, books | `knowledge.*` (docs/chunks/embeddings) |
| **Memory** | Preferences, current projects, goals | `memory.items` (working/episodic/semantic) |
| **Code** | Everything you've ever written: structure, symbols, graphs, patterns | `CodeCapability` index (S14) + code store (S19) |
| **Experience** *(the missing one)* | Problem → diagnosis → commands → mistakes → solution → lessons learned | new experience store (S18+) |
| **Conversation** | Session transcripts + context | `conversation.*` (S10) |

The **Experience** store is the one almost every framework omits — it becomes
*invaluable after years of work*, because Atlas can recall not just facts but *how it
solved a class of problem last time and what went wrong.*

### 5d.3 What each learning capability learns from and produces
| Capability | Learns from | Produces |
|------------|-------------|----------|
| **Knowledge Learning** | PDFs, papers, docs | Knowledge graph |
| **Code Learning** | Python, React, SQL, MATLAB, LabVIEW | Architecture graph, symbol graph, coding patterns |
| **Experience Learning** | Jobs, bugs, fixes, investigations | Lessons learned |
| **Research Learning** | Completed research jobs | Verified knowledge (claims + evidence, §5a) |
| **User Learning** | Preferences and workflows | Personalized assistance |

### 5d.4 Continuous Learning Policy
Every completed activity **may** be promoted into Atlas knowledge — for example: code
repositories · research reports · design documents · engineering notebooks · LabVIEW
projects · MATLAB simulations · PSpice designs · bug investigations · architecture
reviews · meeting notes.

Two rules govern every promotion:

- **Promotion is configurable.** Nothing is learned automatically by default; the user
  (or a per-job/per-project policy) decides what gets promoted and to which store.
- **Atlas never silently learns.** **Every learning action is explainable, reviewable,
  and reversible** — you can see *what* was learned, *why*, *from where*, and undo it.

### 5d.5 Learning Governance (the policy on every learning event)
Atlas must never absorb everything it sees into permanent knowledge. Every learning
event carries **one** of these policies:

| Policy | Scope | Lifetime |
|--------|-------|----------|
| **Temporary** | Valid only for the current conversation or job | Discarded when the job/session ends |
| **Project** | Associated with a specific repository or project | Lives with that project |
| **Personal** | Reusable across your own projects and preferences | Long-term, cross-project |
| **Verified** | Promoted only after you've reviewed / approved it | Permanent "truth" |

This prevents incorrect assumptions, outdated code, or experimental ideas from
silently becoming permanent truth — the user stays in control of what Atlas retains.

### 5d.6 Learning Levels (Store → Recommend)
Learning progresses through five levels; a store can hold facts at any level:

| Level | Name | Example |
|-------|------|---------|
| **L1** | **Store** | Atlas stores 100 repositories |
| **L2** | **Understand** | Atlas understands their classes, functions, modules |
| **L3** | **Connect** | Atlas connects your Django project with your React project |
| **L4** | **Generalize** | Atlas discovers you *always* use the Repository pattern |
| **L5** | **Recommend** | Atlas recommends the Repository pattern *before you ask* |

Pattern mining (§5b.1 layer 6) is how Atlas climbs from L2 → L4/L5 for code.

### 5d.7 Where it lands
The mechanics arrive across two sprints: **S18 (Learning Pipeline)** wires completed
jobs/repos/docs into the stores with governance; **S19 (Engineering Intelligence)**
adds the higher-order learners (repository/code-style/architecture learning, pattern
extraction, project knowledge graph, cross-project search, personal coding assistant,
experience store). Every earlier sprint is designed to *feed* these (see the roadmap
"feeds learning" notes). See D11 in the decision log.

---

## 6. Proposed roadmap (recommended sequence)

| Sprint | Theme | Deliverables | Mode unlocked |
|---|---|---|---|
| **S10 ✅** | **Conversation & Planner Spine** *(done)* | **LLM Roles** (D7) + single LLM lane (R4); `conversation/` (session/history/context) + migration 0009; Planner v0 (deterministic router); ToolExecutor (`ToolResult`, validation, retry); ResponseBuilder + `AssistantService`; `POST /v1/chat` + `atlas chat`; ReAct as fallback strategy; capability-gap pre-flight (R2); **5-test acceptance passing live** | **Chat Mode ✅** |
| **S11 ✅** | **Capability Contracts** *(done)* | typed `runtime_checkable` contracts (`atlas/capabilities/`) + capability **catalog**; registry gains `contract`/`verify`/`missing`; knowledge/memory/agent/conversation/llm/filesystem/web declare contracts; planner tags steps with canonical ids; **gap pre-flight via the registry (R2)** with catalog-enriched reports; `GET /v1/capabilities` + `atlas capabilities` | (foundation) |
| **S12** ✅ | **Job Engine** | `job.*` schema, `JobService` on the scheduler, **concurrent jobs (R1)** w/ CPU-parallel I/O + single LLM lane (R4), step-state incl. `blocked`/`skipped` **(R3)**, LLM decomposition (planner role), progress, reboot recovery (Q10) — §6c | **Research Mode (core)** |
| **S13** ✅ | **Research Plugins I** | **S13a ✅** Document Reader (pdf/docx/pptx/xlsx/csv/md/txt/html/json) + **resilient fetch layer `atlas/net/`** (D10, §5c) — §6d. **S13b ✅** `SearchCapability` (D5, DuckDuckGo + provider fallback) + `web.search`/`web.download`; planner `web_search` intent; `POST /v1/search`, `atlas websearch`/`download` — §6e | evidence gathering |
| **S14** ✅ | **Code Understanding (Tier B)** | `CodeCapability` (D9, §5b): `ast`(Python)+tree-sitter parse, repo map, code-aware chunking→RAG, symbol index, **import + cross-file call graph** (Python-first), **pattern mining**; `code`-role LLM `explain`; `POST /v1/code/*`, `atlas code …` — §6f | reads/reviews code |
| **S15** ✅ | **Verification & Evidence Graph** | Claim model, Evidence Levels 1–5, calculated confidence, convergence stopping rule, Evidence Budget, **Verification Engine** (D8, §5a) | defensible conclusions |
| **S16** ✅ | **Python Execution** | Execution capability (D6, sandbox); computed results become **L5 evidence** in the graph (data-driven estimates) | analysis |
| **S17** ✅ | **Non-blocking HITL & Reports** | `blocked`-step queue (`list_blocked`/`GET /v1/jobs/blocked`/`atlas jobs --blocked`) + event notifications on block/finalize + `atlas job resume` **(R3, never stalls the job)**; **Report Generator** (scientific-review structure, §5a.5) auto-attached on job finalize; `reports` capability, `POST /v1/report`, `atlas report` | usable research jobs |
| **S18a** ✅ | **Deeper Research Sources** | **Scholarly search** (`scholar` cap: arXiv=L3 + Semantic Scholar=L4, provider fallback) producing **graded evidence Sources** for the Verification Engine (§5a); **YouTube transcripts** (`transcript` cap, L1) over the resilient net layer; planner `scholar_search`/`youtube_transcript` intents; `POST /v1/scholar` + `/v1/youtube/transcript`, `atlas scholar`/`youtube` | higher-quality evidence |
| **S18b** ✅ | **Learning Pipeline** | **Continuous Learning** (D11, §5d): governed, explainable, **reversible** learning ledger (`learning` cap) — completed jobs → *proposed* `LearningEvent`s (never silent); **Experience store** (problem→diagnosis→actions→mistakes→solution→lessons) with lexical **recall**; `propose→apply→revert` + policy/Learning-Level; migration 0011; `/v1/learning/*`, `atlas learn` | compounding knowledge |
| **S19** ✅ | **Engineering Intelligence** | `intelligence` cap over the **Code store** (migration 0012): **L2** `learn_repository` (repo map + patterns + symbols → structure, promoted through the S18b ledger via a **store sink** — governed & reversible); **L3** cross-project `search` + `connections` (shared frameworks/langs); **L4** `generalize` (patterns/frameworks/languages you *always* use, prevalence-scored materialised view); **L5** `recommend` + `profile` (the **Personal Coding Assistant**); `/v1/intelligence/*`, `atlas intel` | Atlas learns *you* (L4–L5) |
| **S20** | **Tier 2/3 tools (as needed)** | Browser automation (Playwright), OCR, Git, DB, Email/LinkedIn | full toolbelt |
| **Web UI** | **Conversational frontend** | local frontend over REST (auth/CORS ready); can be pulled forward after S10 if a visual chat surface is wanted sooner | — |

Plugin build order (from the doc, capability-first): Filesystem → Document Reader →
Web Search → Downloader → Python → YouTube → Code Analyzer → Browser → Git → DB →
OCR → Email/LinkedIn. **Browser is deliberately late** — most research is *retrieval
+ understanding*, not driving Chrome.

---

## 6a. Sprint 10 — Conversation & Planner Spine (✅ DONE)

> **Goal:** pass the §3 five-test Chat-Mode acceptance, on a spine that S12's Job
> Engine will reuse unchanged (D1). **Deterministic planner** (D2), **new
> conversation schema** (D3).

**Design contract (mode-agnostic, per D1):** the Planner produces a `Plan`
(ordered `PlanStep`s, each naming a capability/tool + args); the ToolExecutor runs a
`PlanStep` → `ToolResult`. A *chat turn* runs the plan inline and synchronously; a
*job* (S12) will persist the same `Plan`/`PlanStep`s to `job.steps` and run them via
the scheduler. Same objects, two drivers.

### Components
- **LLM Roles (D7/R4) — build first** — add a `roles` map + `max_concurrency` to
  `LLMConfig`; `LLMService.for_role(role)` resolves role→model; a single semaphore
  serialises inference. Migrate `llm.model`→`chat` role, `embedding_model`→`embed`
  role (back-compat). Wire `chat`/`embed` now; register other roles unused. Nothing
  downstream ever names a model again.
- **`atlas/conversation/`** — `Session` (id, created, metadata), `History` (ordered
  messages: role/content/tool calls/timestamps), `Context` (assembled prompt context:
  recent turns + relevant working memories). `ConversationService` + repository over
  the new `conversation.*` schema.
- **`atlas/planner/`** — `Planner` (deterministic): message → `Plan`. Intents v0:
  `list_documents`, `ingest_path`, `ask_knowledge`, `remember`, `recall`,
  `web_fetch`, `smalltalk/fallback`. Fallback intent routes to the `ReActAgent` (open
  reasoning) so we never dead-end. Rules are data-driven (easy to extend/test).
- **`atlas/execution/`** — `ToolExecutor`: validates args against the tool's param
  hints, invokes via `ToolRegistry`, retries transient failures, returns a structured
  `ToolResult(ok, data, error, evidence, elapsed_ms)`.
- **ResponseBuilder** — assembles the final reply from `ToolResult`s + knowledge +
  memory via the LLM, and can **explain what it did** (tools used) — a Chat-Mode
  acceptance requirement.
- **`AssistantService`** (the orchestrator) — ties session → planner → executor →
  response; persists the turn; updates working memory. Exposed via
  `POST /v1/chat` (+ session) and `atlas chat` (REPL).

### Schema — migration `0009_conversation_foundation.sql`
- `CREATE SCHEMA conversation` (idempotent) + **grants to the `atlas` app role**,
  matching the Sprint 5 grants/ownership pattern (migration 0005) so the least-priv
  runtime role can R/W the new tables.
- `conversation.sessions(id, title, created_at, updated_at, metadata jsonb)`
- `conversation.messages(id, session_id FK ON DELETE CASCADE, ordinal, role, content,
  tool_calls jsonb, created_at)`, unique `(session_id, ordinal)`, index on
  `(session_id, ordinal)` for fast history reads.

### Config additions (S10)
- **`llm.roles`** (map, D7) + **`llm.max_concurrency`** (default `1`, R4) in
  `AtlasConfig`/`defaults.yaml`; `llm.model`→`chat`, `llm.embedding_model`→`embed`
  back-compat shims so existing call sites keep working during migration.
- **`conversation`** block: `max_context_turns` (recent turns to include, default 10),
  `working_memory_k` (relevant memories to recall per turn, default 5).
- No **new external dependencies** for S10 — it's all orchestration over Stage-1
  substrate (`tree-sitter`, `ddgs`, etc. arrive in their own sprints).

### Build order (within S10)
1. **LLM Roles + lane** (`LLMService.for_role`, semaphore) + config + back-compat.
2. **Migration 0009** + `conversation` repo/service (session/history/context).
3. **ToolExecutor** (`ToolResult`, arg validation, retry) over `ToolRegistry`.
4. **Planner v0** (deterministic intent router → `Plan`/`PlanStep`).
5. **ResponseBuilder** + **`AssistantService`** orchestration.
6. **`POST /v1/chat`** (+ session) and **`atlas chat`** REPL.
7. Hermetic tests, then the **live 5-test** run.

### Definition of Done (S10) — ✅ all met
- [x] Callers resolve LLMs by role only; a single semaphore serialises inference (R4).
- [x] `conversation.*` persists sessions/messages; survives restart; context assembled
      from recent turns + scoped working memory.
- [x] Deterministic planner routes the v0 intents; unknown → ReAct fallback (no dead end).
- [x] ToolExecutor validates/retries and returns structured `ToolResult`s.
- [x] `POST /v1/chat` and `atlas chat` work end-to-end with a persistent session.
- [x] Hermetic unit tests green; **the five §3 interactions pass live**; full suite green (275).
- [x] `IMPLEMENTATION_PLAN.md` + this file updated (roadmap status, ADR-0056/57/58, progress log).

### Reuse (no new capability yet — that's S11)
- documents list → `KnowledgeService`/`document_repo`; ingest → `KnowledgeService.ingest_*`;
  ask → existing RAG path; remember/recall → `MemoryService` (scope = session id);
  web fetch → existing `web.fetch` tool via the executor.

### Testing / acceptance
- Hermetic unit tests: planner intent routing, ToolExecutor (validation/retry/result),
  conversation repo (ordering, context assembly), AssistantService turn flow (fakes).
- **End-to-end: the five §3 interactions pass** (live, scripted against real
  services) — the definition of done for S10.

### Out of scope for S10 (later sprints)
- Async jobs, LLM decomposition, evidence graph, research plugins, reports — S11+.

---

## 6b. Sprint 11 — Capability Contracts (✅ DONE)

> **Goal:** turn the untyped name→provider registry into **typed capability
> contracts** so the planner selects by capability, the registry can *verify* a
> provider implements its protocol, and the Capability Gap pre-flight (R2) becomes
> registry-driven and honest — the foundation the Job Engine (S12) plans against.

**What shipped**
- **`atlas/capabilities/`** — `runtime_checkable` Protocols (`LLMCapability`,
  `MemoryCapability`, `KnowledgeCapability`, `ExecutionCapability`,
  `ConversationCapability`, `FetchCapability`, `FilesystemCapability`, plus
  *planned* `DocumentCapability`/`SearchCapability` and `code`/`learning`
  placeholders), canonical **capability ids**, and a **`CAPABILITY_CATALOG`** of
  known capabilities (summary + what each *unlocks* + the sprint that adds it).
- **Registry upgrade** (`kernel/capabilities.py`): registration takes an optional
  `contract`; new `verify(name)` (isinstance against the Protocol), `contract_of`,
  and `missing(required)`; `describe()` now includes the contract name. Fully
  back-compatible (contract is optional).
- **Contracts declared** in bootstrap (llm/knowledge/agent/memory/conversation) and
  in the filesystem/web plugins.
- **Planner** tags each step with a canonical capability id (constants, no drift).
- **Gap pre-flight** in `AssistantService` now consults the **registry** (source of
  truth; sees plugin capabilities registered later) and enriches each gap with the
  catalog's `unlocks`/`since`. Falls back to dependency-inference when no registry is
  wired (keeps older callers working).
- **Introspection:** `GET /v1/capabilities` and `atlas capabilities` list every
  capability as **provided** or **missing**, with contract + what building it
  unlocks — the honest "what I can and cannot do" surface (R2).

**Definition of Done (S11)** — all met:
- [x] Typed contracts + catalog; registry `verify`/`missing`/`contract_of`.
- [x] Services + plugins declare contracts; planner uses canonical ids.
- [x] Gap pre-flight is registry-driven and catalog-enriched (R2).
- [x] `GET /v1/capabilities` + `atlas capabilities`.
- [x] Hermetic tests for registry, contracts, gap path, API, CLI. **285 tests pass** (+10).

---

## 6c. Sprint 12 — Job Engine (✅ DONE)

> **Goal:** the north star of D1. Persistent, **concurrent (R1)**, **resumable (R3)**
> jobs on top of the durable scheduler: an objective is decomposed into ordered
> steps that advance one at a time, reusing the *exact* chat dispatch (D1). A
> blocked step never stalls the job — it pauses only itself and the job finishes
> `completed_with_blocks` until resumed.

**Architecture**
- **One step per scheduler task.** `create_job` enqueues an **`advance_job`** task;
  its handler runs *one* runnable step, persists the outcome, then **re-enqueues
  itself**. Short tasks let many jobs **interleave on the worker pool (R1,
  CPU-parallel)** while steps within a job stay **sequential (Q1)**. LLM calls still
  serialise through the single LLM lane (R4) — no change needed.
- **Blocking is non-fatal (R3).** A step needing the user — missing **capability**
  (R2), missing **file** (Q3, drop-in-watched-folder), or later a login — is marked
  `blocked` with a `blocked_reason`; the loop advances past it. **Dependents cascade**:
  a dependent of a `blocked` step → `blocked`; of a `failed`/`skipped` step →
  `skipped`. Final job status: `completed_with_blocks` if any block, else `failed` if
  any hard failure, else `completed`.
- **Reuse, not reimplementation (D1).** Steps run through the new
  **`AssistantService.run_step`** — the same intent dispatch a chat turn uses,
  extended with a `blocked` outcome and a per-step runtime capability check (R2/R3).
- **Reboot recovery (Q10).** On start, steps left `running` reset to `pending` and
  unfinished (`queued`/`running`) jobs are re-enqueued — extends the scheduler's
  crash recovery to jobs.

**What shipped**
- Migration **0010** (`job` schema + grants): `job.jobs` (queued → running →
  completed | completed_with_blocks | failed | cancelled) and `job.steps` (pending →
  running → done | failed | blocked | skipped; `depends_on`, `blocked_reason`,
  `attempts`).
- Models `Job`/`JobStep` (`atlas/models/job.py`); `JobRepository` (atomic state
  transitions, `reset_blocked_steps`, `recover_interrupted_steps`,
  `list_unfinished_jobs`).
- **`JobPlanner`** (`atlas/jobs/planner.py`, D2c): deterministic fallback (reuses the
  mode-agnostic `Planner`) **+ optional planner-role LLM decomposition** into a
  validated JSON step list (invalid intents/caps dropped, `depends_on` clamped; LLM
  can only *improve* on the deterministic plan). Off by default (`jobs.llm_decompose`).
- **`JobService`** (`atlas/jobs/service.py`): create/decompose/enqueue, the
  `advance_job` handler, blocking + cascade, `resume_job`, `cancel_job`, progress,
  and startup recovery. Wired in bootstrap (repo, planner, service, `advance_job`
  handler, `jobs` capability + lifecycle).
- **Config** `jobs.*` (`max_concurrent=3`, `step_max_retries`, `retry_delay`,
  `llm_decompose`, `max_steps`); `scheduler.workers` raised to **3** so three jobs
  advance at once (R1).
- **API**: `POST /v1/jobs`, `GET /v1/jobs`, `GET /v1/jobs/{id}`,
  `POST /v1/jobs/{id}/resume`, `POST /v1/jobs/{id}/cancel`. **CLI**: `atlas jobs`,
  `atlas job start|show|resume|cancel`.

**Definition of Done (S12)** — all met:
- [x] `job.*` schema + repo with atomic transitions and recovery queries.
- [x] Concurrent jobs (R1) via self-re-enqueuing one-step tasks; sequential steps (Q1).
- [x] `blocked`/`skipped` step states + dependency cascade; non-blocking HITL (R3).
- [x] Deterministic decomposition + optional planner-role LLM (D2c); reuses chat dispatch (D1).
- [x] Reboot recovery re-hydrates jobs/steps (Q10).
- [x] API + CLI job surfaces.
- [x] Hermetic tests (planner, service loop/blocking/resume/recovery/cascade, API, CLI). **312 tests pass** (+27).

---

## 6d. Sprint 13a — Document Reader + Resilient Net Layer (✅ DONE)

> **Goal (S13, part 1):** two foundations the research plugins stand on — read the
> **full document format set** (Q8) and fetch the web **politely and resiliently**
> (D10 / §5c) so a job *degrades, never crashes*. Web **search** (D5) + **Downloader**
> are S13b (next), built on this net layer.

**Document Reader (`DocumentCapability`)**
- Expanded the shared extractors (`atlas/ingestion/extractors.py`) to the S13 set:
  **pdf, docx, pptx, xlsx, csv, md, txt, html, json** (docx tables flattened, pptx
  per-slide text, xlsx per-sheet TSV, csv dialect-sniffed, json pretty-printed). Lazy
  imports keep each parser's dependency isolated.
- New **`atlas/documents/`** `DocumentService` (the `document` capability): `extract()`
  returns an `ExtractedDocument` with an **outcome** — `ok` / `unsupported` / `empty`
  (no text layer, e.g. scanned PDF → future OCR) / `error` — so callers get an honest
  classification instead of an exception (R2). `supported()` lists formats.
- Wired everywhere the old extractors were: the filesystem **scan** and `atlas ingest`
  now handle all nine formats automatically; `ingestion.extensions` default expanded.
- Surfaced: `GET /v1/documents/formats` + `atlas formats`.

**Resilient net layer (`atlas/net/`, D10 / §5c)**
- **`FetchClient.get(url)`** returns a structured **`FetchResult`** and *never raises*
  for network/HTTP conditions — it classifies them: `ok` (2xx, cached), **`blocked`**
  (401/403 → needs login, maps to a blocked step, R3), **`skipped`** (4xx /
  robots-disallowed / retries exhausted → source unavailable, keep the job going, R3),
  `error` (bad scheme).
- Politeness/resilience: **per-domain throttle** (honours `robots.txt` allow/deny +
  `crawl-delay`), **bounded exponential backoff with jitter** on 429/503/5xx/timeouts
  (honours `Retry-After`), and an in-memory **response cache** (TTL). Injectable
  transport/sleep/clock/rand → fully hermetic tests.
- **`WebPlugin` now fetches through `FetchClient`** (throttled, robots-aware, retried,
  cached); a hard block/skip is surfaced honestly (R2). Config: new top-level `net.*`.
- *R3 through-the-tool* (turning a `blocked` fetch into a blocked **job step**
  automatically) lands with the HITL work in **S17**; today the outcome is reported.

**Definition of Done (S13a)** — all met:
- [x] Nine-format Document Reader + `DocumentService`/`DocumentCapability`; scan & ingest use it.
- [x] `atlas/net/` resilient client: throttle + robots + backoff/retry + cache + outcomes (R2/R3).
- [x] `WebPlugin` rewired onto the net layer; `net.*` config.
- [x] `GET /v1/documents/formats` + `atlas formats`.
- [x] Hermetic tests (extractors, document service, net client, web plugin, API, CLI). **343 tests pass** (+31).
- [x] **S13b:** `SearchCapability` (D5, swappable provider) + Downloader on this net layer — §6e.

---

## 6e. Sprint 13b — Web Search (D5) + Downloader (✅ DONE)

> **Goal (S13, part 2):** turn the resilient net layer into two *research* capabilities
> — **search the web** for sources and **download** files — both degrading, never
> crashing (R2/R3), both swappable (D5).

**Web Search (`SearchCapability`, D5)**
- New **`atlas/search/`**: a `SearchProvider` protocol → `SearchResponse` (outcome +
  ranked `SearchHit`s). `DuckDuckGoProvider` uses the keyless HTML endpoint, fetches
  through `FetchClient` (throttle/robots/backoff/cache), and **translates the net
  outcome** (`ok`/`blocked`/`skipped`/`error`) instead of raising.
- New **`SearchPlugin`** (`search` capability, tool **`web.search(query, max_results)`**):
  holds an **ordered provider list** and tries them in turn — first with results wins
  (**provider fallback**); SearXNG/Brave/Serper drop in via `plugins.search.providers`
  without touching the planner (D5). A raising provider is caught, not fatal.
- Planner gains a **`web_search` intent** (routes "search the web / look up / find
  sources…" to `CAP_SEARCH`, strips the trigger to a clean query); `AssistantService`
  `_do_web_search` lists results and **reports `blocked`/empty outcomes honestly** (R2).
  `JobPlanner` accepts `web_search` for job decomposition.

**Downloader**
- New **`DownloaderPlugin`** (`downloader` capability, tool **`web.download(url,
  filename?)`**): fetches via `FetchClient` (size-capped), writes to a controlled
  downloads dir (`plugins.downloader.dir` or `paths.data/downloads`) with a **sanitised,
  sandbox-confined** filename. A `blocked`/unavailable source raises with the honest
  outcome (R2); http(s) only.

**Surfaces & config**
- `POST /v1/search`; `atlas websearch "query"` + `atlas download <url>`.
- Config: `plugins.search` (providers, max_results, endpoint) + `plugins.downloader.dir`;
  both plugins enabled by default; they build their own `FetchClient` from `net.*`.

**Definition of Done (S13b)** — all met:
- [x] `SearchProvider`/`DuckDuckGoProvider` + `SearchPlugin` with provider fallback (D5), over the net layer (R2/R3).
- [x] `DownloaderPlugin` (`web.download`) with sandboxed filenames, honest block/skip.
- [x] Planner `web_search` intent + assistant handler + `JobPlanner` support.
- [x] `POST /v1/search`, `atlas websearch`/`download`; default config + enabled plugins.
- [x] Hermetic tests (providers, search plugin, downloader, planner, assistant, API, CLI). **370 tests pass** (+27).
- [x] **S14:** `CodeCapability` (Tier B code understanding, D9 / §5b) — §6f.

---

## 6f. Sprint 14 — Code Understanding (`CodeCapability`, Tier B) (✅ DONE)

> **Goal (D9 / §5b):** read code as **structure, not text**. A deterministic parse
> (facts, no hallucination) feeds a repo map, symbol index, import + **cross-file call
> graph**, and **pattern mining**; the `code`-role LLM explains/reviews *grounded on
> that structure*. All pure-CPU (R4).

**Parsing (§5b.1 layers 1 & 7) — `atlas/code/`**
- **Python → stdlib `ast`** (`pyast.py`): exact line ranges, signatures, docstrings,
  imports (incl. relative), and **call sites with their enclosing symbol** — the input
  to the cross-file call graph. This is the full-fidelity, Python-first path (D9).
- **Other languages → tree-sitter** (`treesitter.py`, `tree-sitter-language-pack`):
  symbols + imports for JS/TS/TSX, C/C++, Rust, Go, Java, Bash, SQL (§5b.2). Grammar
  missing → `shallow`; unsupported language → `unsupported` (plain-text fallback) — an
  honest per-file **outcome** (`ok`/`shallow`/`unsupported`/`error`), never a crash (R2).

**Structure (§5b.1 layers 2, 4, 6)**
- **Repo map** (`repomap.py`): walk (skipping vendored/build dirs) + manifests
  (`pyproject`/`requirements`/`package.json`/`Cargo.toml`/`go.mod`/Docker) → dependencies,
  **inferred frameworks** (Django/FastAPI/React/pytest/PostgreSQL/…), and entry points.
- **Graph** (`graph.py`, Tier B): import edges resolved via module-path mapping (incl.
  relative imports); **cross-file call graph** resolved against the repo symbol table
  with conservative heuristics (exact qualname / unique name / `self.method` in the
  caller's class). Builtins/externals are ignored (not faked); ambiguous-but-known
  names are **counted as unresolved**, never guessed.
- **Pattern mining** (`patterns.py`): evidence-backed recurring patterns (Repository /
  Service / Registry, pytest, Docker, PostgreSQL, UUIDs, dataclasses, async, framework)
  — the seed for the S19 Personal Coding Assistant / Experience store.

**Service, RAG, LLM (§5b.1 layers 3 & 5) — `CodeService` (`code` capability)**
- `parse` / `repo_map` / `index` / `search_symbols` / `graph` (the `CodeCapability`
  contract) + `patterns` / `explain`. Repo scans parse once, cached per root.
- **Code-aware chunking → knowledge** (`index(ingest=True)`): one chunk per function/
  method (not word windows) with symbol metadata → semantic code search over the
  existing RAG pipeline.
- **`explain`** uses the `code`-role LLM (D7, `qwen3-coder`) grounded on the parsed
  outline + source; degrades to the structural outline if no LLM.
- Surfaces: `POST /v1/code/{parse,repo-map,graph,symbols,patterns,explain}`; `atlas code
  {parse,map,symbols,graph,patterns,explain}`. Config `code.*`; contract `CodeCapability`
  registered (catalog `CAP_CODE` now concrete/provided).

**Definition of Done (S14)** — all met:
- [x] `ast` (Python, incl. calls) + tree-sitter (breadth) parsers with honest outcomes (R2).
- [x] Repo map (deps/frameworks/entry points) + symbol index + import & **cross-file call graph** (Tier B).
- [x] Pattern mining (evidence-backed) feeding S19.
- [x] `CodeService` + code-aware RAG ingest + `code`-role grounded `explain`.
- [x] `CodeCapability` contract concrete + registered; API `/v1/code/*` + `atlas code …`; `code.*` config.
- [x] Hermetic tests (pyast, tree-sitter, repo map, graph, patterns, service, caps, API, CLI). **421 tests pass** (+51).
- [x] **Done — S15:** Verification Engine + Evidence Graph (D8 / §5a) — §6g.

---

## 6g. Sprint 15 — Verification Engine + Evidence Graph (D8, §5a) (✅ DONE)

**The differentiator.** Between *Research* and *Report* sits a first-class subsystem
that turns gathered evidence into **defensible conclusions**: verify by *claim*, grade
evidence by *quality* (L1–L5), *calculate* confidence from quality + convergence +
contradictions, and stop on **convergence**, not a fixed paper count.

- **Evidence Graph** (`atlas/evidence/`): serialisable model — `Source`, `EvidenceItem`
  (source_id, level, extracted_value, snippet, locator, stance), `ClaimValue`, `Claim`
  (statement, value, evidence, *calculated* confidence, convergence, `last_verified`,
  `verification_method`, `reasoning_trace`), and `EvidenceGraph` (sources + claims,
  `as_dict`/`from_dict`). Claims are persistent objects → **re-verifiable** when new
  evidence appears (§5a.1).
- **Evidence Levels** (§5a.2): L5 field data → L4 peer-reviewed → L3 government/lab →
  L2 technical blog → L1 forum. Quality, not count.
- **Verification Engine** (`atlas/verification/engine.py`): pure/deterministic, no
  LLM/I/O.
  - `convergence(values)` → largest cluster within a relative tolerance, ∈ [0,1]
    (`3.7/3.9/4.0/3.8` → 1.0; `2/11/6/4` → low).
  - `verify_claim(claim)` → **calculated** confidence HIGH/MEDIUM/LOW/INSUFFICIENT
    (score = 0.6·convergence + 0.4·quality, contradiction penalty; a single or
    low-level source can never be HIGH), plus a human `reasoning_trace` (§5a.3).
  - `decide(claim, budget, iteration)` → `stop`/`continue` with the unmet criteria —
    the **Evidence Budget** (§5a.4): `min_sources`, `min_peer_reviewed`,
    `min_government`, `convergence`, `max_search_iterations`.
- **`VerificationService`** = the `verification` capability: `verify(graph, budget?)`
  verifies every claim + attaches a per-claim budget decision; serialisable in/out so a
  research job (S17/S18) can persist and re-verify the graph.
- **Config** `research:` (`ResearchConfig`) = the Evidence-Budget defaults, planner-tunable.
- **Surface:** `POST /v1/verify` + `atlas verify graph.json`.

> **Scope note:** S15 delivers the *engine + graph + budget* primitives (pure, hermetic).
> Wiring them into a live research loop (gather → verify → decide → gather again) and the
> scientific-review **Report Generator** (§5a.5) land with **S17**; Python-computed
> results (S16) enter the same graph as **L5** evidence (§5a.6).

**Definition of Done (S15)** — all met:
- [x] Evidence Graph model (Source/EvidenceItem/ClaimValue/Claim/EvidenceGraph), serialisable + re-verifiable.
- [x] Evidence Levels L1–L5; convergence measured (agreement, not count).
- [x] Confidence **calculated** (quality + convergence + contradictions) with reasoning trace.
- [x] Evidence Budget + `decide()` continue/stop with explicit unmet criteria.
- [x] `VerificationService` (`verification` capability) wired in bootstrap; `research.*` config.
- [x] `POST /v1/verify` + `atlas verify`; hermetic tests (convergence, confidence, budget, graph, service, API, CLI). **444 tests pass** (+23).
- [x] **Done — S16:** Python Execution Sandbox (computed results become L5 evidence) — §6h.

---

## 6h. Sprint 16 — Python Execution Sandbox (D6, hybrid) (✅ DONE)

Atlas can now **run analysis code** in an isolated, resource-limited sandbox — the
substrate for data-driven estimates whose results become **L5 evidence** (§5a.6).

- **`atlas/sandbox/`**: `SandboxBackend` is the swap point (D6 *hybrid*).
  - **`SubprocessBackend`** (default): child interpreter (`python -I -B`) with a POSIX
    `preexec_fn` applying **rlimits** (`RLIMIT_CPU`, `RLIMIT_AS` memory, `RLIMIT_FSIZE`,
    no core dump); a **hard wall-clock timeout** that kills the whole **process group**
    (`start_new_session` + `killpg`); a **scratch working dir**; a **stripped env**; and
    — unless explicitly enabled — an in-interpreter **network block** (neutralises
    `socket.socket`/`create_connection`).
  - **`DockerBackend`**: selectable placeholder (reports itself unavailable → every run
    is `blocked`, R2) so stronger isolation drops in later via `sandbox.backend: docker`.
- **`ExecutionResult`** (serialisable): `outcome` (`ok`/`error`/`timeout`/`blocked`),
  stdout/stderr (truncated to a cap), returncode, `duration_ms`, `timed_out`, an optional
  structured **`result`** (parsed from a `result.json` the code writes), and **artifacts**
  (files the run produced). A run **never raises** into the caller (R2/R3).
- **`PythonSandboxService`** = the `python` capability: `run(code, timeout?, files?, stdin?,
  network?)` / `run_file(path)`; owns policy (limits, network default, per-run uuid workdir
  under `paths.data/sandbox`) and delegates to the backend.
- **Planner/dispatch**: new `run_python` intent (fenced ` ```python ` blocks or an explicit
  "run/execute python …") + `AssistantService._do_run_python` (reports output, errors,
  timeouts, and sandbox-unavailable honestly); `JobPlanner` accepts it (jobs can compute).
- **Concrete `PythonExecutionCapability`** contract (catalog `CAP_PYTHON`, since S16).
- **Config** `sandbox.*` (backend, timeout, cpu_seconds, memory_mb, output/code caps,
  network). **Surface:** `POST /v1/python/run` + `atlas python "…"`/`-f file.py`.

> **Isolation honesty:** the subprocess backend is *soft* isolation (kernel rlimits +
> an in-interpreter net block) — the right default for **trusted-ish** analysis code on
> the single self-hosted node. Hostile-code-grade isolation is the Docker backend's job
> (already the selectable path, D6).

**Definition of Done (S16)** — all met:
- [x] `SandboxBackend` interface + subprocess backend (rlimits, timeout→killpg, scratch dir, stripped env, net block).
- [x] Docker backend selectable + honestly unavailable (R2); `create_backend` factory.
- [x] `ExecutionResult` (ok/error/timeout/blocked) + `result.json` + artifacts; never raises.
- [x] `PythonSandboxService` (`python` capability) wired in bootstrap; `python.run` tool; `sandbox.*` config.
- [x] `run_python` intent + dispatch + `JobPlanner`; `PythonExecutionCapability` contract.
- [x] `POST /v1/python/run` + `atlas python`; hermetic tests (real subprocess: ok/error/timeout/net-block/result/artifacts/truncation, service, planner, assistant, api, cli, caps). **478 tests pass** (+34).
- [x] **Next — S17:** Research loop (gather→verify→decide) + Non-blocking HITL & scientific-review Report Generator (§5a.5). ✅ (§6i)

---

## 6i. Sprint 17 — Non-blocking HITL & Report Generator (§5a.5) (✅ DONE)

The research pipeline now has an *output* and a *human loop*: a finished job carries a
**scientific-review report**, and the sub-tasks a job couldn't do alone surface as a
**queue awaiting the user** — without ever having stalled the job (R3).

- **`atlas/reports/` — Report Generator (§5a.5).** `ReportGenerator.generate()` is a
  **pure, deterministic** assembly of the nine review sections — *Executive Summary →
  Answer → Confidence → Methodology → Evidence → References → Conflicting Views →
  Limitations → Next Research* — from *verified* claim dicts + source dicts. Every
  numeric answer carries its claim's **calculated confidence** and supporting/
  contradicting counts (ties into S15). **Overall confidence is derived, never guessed**:
  the most common claim confidence, tie-broken toward the *more conservative* level.
  **Conflicting Views** auto-flags claims with contradicting sources or weak/insufficient
  evidence; **Next Research** is derived from low-confidence / non-converged claims. An
  optional **`summarizer`-role LLM** only *polishes* the executive-summary prose — with no
  LLM (or on any failure) it falls back to deterministic text, so a report is **always
  producible**. Renders both a structured dict and a **Markdown** document.
- **`ReportService` = the `reports` capability.** `report(objective, graph, budget?)`
  runs the **verify→render** pipeline (Verification Engine → §5a.5 report);
  `render(objective, …)` renders directly from already-verified claims or a gathered
  answer + sources (no verification) — used by the Job Engine.
- **Job Engine integration.** On finalize, `JobService` builds a report from the job's
  completed steps (answers + citations→references) and attaches
  `result.report` (Markdown) + `result.report_sections` + `result.overall_confidence` —
  a report **never fails the job** (best-effort, R2/R3).
- **Non-blocking HITL (R3).** New `JobService.list_blocked()` aggregates **blocked steps
  across jobs** into one queue (job id, ordinal, capability, what it *needs*, objective);
  `resume_job` (S12) reruns them once the user provides the file/credential/capability.
  **Event notifications** now fire on `job.step_blocked` and `job.finalized` (in-app via
  the event dispatcher, Q2) so a surface can prompt the user.
- **Surface.** `POST /v1/report` (objective + serialised graph → verified report),
  `GET /v1/jobs/blocked` (the HITL queue), `atlas report graph.json`,
  `atlas jobs --blocked`.

> **Scope honesty:** S17 delivers the report *artifact* and the HITL *queue/notify* loop
> on top of the existing deterministic job decomposition. A fully **autonomous multi-round
> gather→verify→decide research orchestrator** (claim extraction from arbitrary sources,
> budget-driven re-search) is the deep-research work of **S18** — S17 gives it the report
> renderer and verification pipeline it will drive.

**Definition of Done (S17)** — all met:
- [x] `ReportGenerator` (§5a.5 nine sections, pure + optional summarizer-LLM polish, derived overall confidence, conflicting-views/next-research logic, Markdown).
- [x] `ReportService` (`reports` capability): verify→render pipeline + direct `render`; wired in bootstrap (container/capabilities/lifecycle).
- [x] `JobService` attaches a report on finalize; `list_blocked()` HITL queue; `job.step_blocked`/`job.finalized` notifications.
- [x] `POST /v1/report` + `GET /v1/jobs/blocked`; `atlas report` + `atlas jobs --blocked`.
- [x] Hermetic tests (generator sections/confidence/conflicts/references/LLM-polish, service verify→render, job report+notify+blocked, api, cli). **497 tests pass (+19).**
- [x] **Next — S18:** Deeper Research (YouTube/Scholar/arXiv) + the **Learning Pipeline** (D11/§5d) seeding the five stores. **S18a done** (§6j); **S18b** (Learning Pipeline) next.

---

## 6j. Sprint 18a — Deeper Research Sources (Scholarly + YouTube) (✅ DONE)

Atlas's research reach now extends past general web links to **academic literature** and
**spoken-word** sources — and, crucially, each result arrives **pre-graded on the
Evidence Level scale (§5a.2)** so it drops straight into the Verification Engine and
scientific-review reports (S15/S17).

- **`atlas/search/scholarly.py` — scholarly providers.** A `ScholarlyProvider` mirrors
  the D5 web-search protocol but returns **`Paper`s** (title, authors, year, venue,
  abstract, DOI, citation count) each tagged with an Evidence Level, plus an
  `as_source()` in the exact Evidence-Graph `Source` shape.
  - **`ArxivProvider`** — arXiv Atom API (keyless); preprints ⇒ **L3** (configurable).
  - **`SemanticScholarProvider`** — Semantic Scholar Graph API (keyless, rate-limited;
    optional key); published venues + citation counts ⇒ **L4** peer-reviewed.
  Both fetch through the resilient net layer and **translate outcomes, never raise**.
- **`ScholarPlugin`** = the `scholar` capability (tool `scholar.search`): ordered
  providers with **provider fallback** — the first `ok`-with-papers wins; a
  blocked/rate-limited backend falls through, and the final structured outcome is
  returned (R2/R3). Output carries both `results` (papers) and `sources` (graded).
- **`atlas/transcripts/` — YouTube transcripts.** `YouTubeTranscriptProvider` does two
  polite fetches (watch page → scrape `captionTracks` → timedtext XML → decode cues),
  returning a `TranscriptResult` (text + timed segments) as **L1** evidence. Every
  failure mode is an *outcome* (`error`/`skipped`/`blocked`), never an exception.
  `YouTubePlugin` = the `transcript` capability (tool `youtube.transcript`).
- **Planner/dispatch.** New `scholar_search` intent (arXiv/Scholar mentions or
  "papers/studies on …" — routed *ahead* of generic web search) and `youtube_transcript`
  intent (a YouTube URL — routed *ahead* of generic web fetch — or an explicit
  "transcript/transcribe" request), with `AssistantService._do_scholar_search` /
  `_do_youtube` (honest blocked/skipped reporting). `JobPlanner` accepts both so research
  jobs can gather peer-reviewed evidence and talks.
- **Concrete contracts** `ScholarCapability` / `TranscriptCapability` (catalog
  `CAP_SCHOLAR` / `CAP_TRANSCRIPT`, since S18). **Config** `plugins.scholar`
  (providers, levels, optional S2 key) + `plugins.youtube` (languages). **Surface:**
  `POST /v1/scholar` + `POST /v1/youtube/transcript`; `atlas scholar "…"` +
  `atlas youtube <url|id>`.

> **Why this ordering:** deeper *retrieval* was split from the *Learning Pipeline*
> (S13a/S13b precedent) because it is a direct extension of the shipped search-provider
> architecture and immediately feeds the S15 Verification Engine and S17 reports with
> **L3/L4 sources** — the biggest single quality lever for defensible conclusions.

**Definition of Done (S18a)** — all met:
- [x] `ArxivProvider` + `SemanticScholarProvider` (graded `Paper` → Evidence `Source`; never raise); `ScholarPlugin` (`scholar` cap) with provider fallback.
- [x] `YouTubeTranscriptProvider` (watch-page + timedtext scrape, outcomes not exceptions); `YouTubePlugin` (`transcript` cap).
- [x] Planner `scholar_search` (ahead of web search) + `youtube_transcript` (ahead of web fetch) intents + dispatch; `JobPlanner` support.
- [x] `ScholarCapability`/`TranscriptCapability` contracts + catalog; `plugins.scholar`/`plugins.youtube` config; both plugins enabled by default.
- [x] `POST /v1/scholar` + `/v1/youtube/transcript`; `atlas scholar`/`youtube`.
- [x] Hermetic tests (arXiv/S2 parse + grading, fallback, transcript flow/skip/block/lang, planner routing, assistant handlers/gaps, api, cli, caps). **532 tests pass (+35).**
- [x] **Done → S18b:** the **Learning Pipeline** (§6k).

---

## 6k. Sprint 18b — Learning Pipeline (Continuous Learning, the third pillar) (✅ DONE)

Atlas stops being amnesiac. Every completed activity **may** become durable
engineering knowledge — but only through a **governed, explainable, reversible**
pipeline, honouring the two hard guarantees of §1b/§5d: *Atlas never silently learns*,
and *learning is governed*.

- **`learning.events` ledger (migration 0011).** Every learning action is a row with
  *what* (`summary`), *why* (`reason`), *from where* (`origin`), a governance `policy`
  (**temporary/project/personal/verified**, §5d.5), a **Learning Level** (`level`,
  §5d.6), and a lifecycle `status` (**proposed → applied → reverted**). Nothing is in a
  store until an event is *applied*, and every application can be *reverted* — the
  guarantees are enforced by the schema, not just documented.
- **The Experience store (`learning.experiences`) — the "missing fifth store".** Each
  entry is a reusable **problem → diagnosis → actions → mistakes → solution → lessons**
  record so Atlas can recall *how* it solved a class of problem, not just facts.
  `status='reverted'` hides an experience without destroying the audit trail.
- **`LearningService` = the `learning` capability.**
  - `observe_job(detail)` distils a finished job into an Experience *candidate* and
    records a **proposed** event (default `auto_apply=false` ⇒ propose-only; never
    silent). Best-effort: it never raises into — or fails — a job.
  - `apply(event_id, policy?, level?)` promotes a proposal into its store (creating the
    Experience) and stamps the event `applied` with its governance labels;
    `revert(event_id)` flips it to `reverted` and deactivates the created record.
  - `remember_experience(...)` is the manual path (an explicit act ⇒ applied at once);
    `recall(query)` does lexical recall over the Experience store; `explain(event_id)`
    renders the what/why/from-where + status (explainable).
  - Concrete `LearningCapability` contract replaces the S18 catalog placeholder.
- **Wiring & governance defaults.** `JobService._finalize` calls `learning.observe_job`
  after the report is attached (guarded, best-effort). `LearningConfig`
  (`enabled/observe_jobs/auto_apply/default_policy/default_level/recall_k`) defaults are
  conservative: **propose-only, temporary policy, L1**. Registered in bootstrap
  (container/capabilities/lifecycle).
- **Surface.** `GET /v1/learning/events[/{id}]`, `POST /v1/learning/events/{id}/apply`,
  `.../revert`, `GET|POST /v1/learning/experiences`; `atlas learn
  events|show|apply|revert|experiences|recall`.

> **Scope line (why now):** S18b lands the *ledger + Experience store + job
> observation + review/apply/revert/recall* — the governance spine and the one
> concrete store. Promotion into the **other** stores (knowledge graph, code/
> architecture, generalized patterns) and the higher **Learning Levels L2–L5**
> (Understand/Connect/Generalize/Recommend) are the Engineering-Intelligence work of
> **S19**; the ledger already models them (`store`/`level`), so S19 adds sinks, not
> schema.

**Definition of Done (S18b)** — all met:
- [x] Migration 0011 `learning` schema (`events` + `experiences`, CHECK-constrained policy/status/level).
- [x] `LearningEvent` + `Experience` models (constants for sources/stores/policies/levels); repository (event + experience CRUD, lexical `search_experiences`, counts).
- [x] `LearningService` (`learning` cap): `observe_job`/`propose`/`apply`/`revert`/`remember_experience`/`recall`/`explain` + governance; never-silent + reversible enforced.
- [x] Concrete `LearningCapability` contract (replaces S18 catalog placeholder).
- [x] Bootstrap wiring + `JobService.observe_job` on finalize; `LearningConfig` + `learning:` defaults.
- [x] `/v1/learning/*` endpoints + `atlas learn` CLI.
- [x] Hermetic tests (service governance/apply/revert/recall/explain, repo-fake, job-observe, api, cli, caps). **555 tests pass (+23).**
- [x] **Done → S19:** **Engineering Intelligence** (§6l).

---

## 6l. Sprint 19 — Engineering Intelligence (the Personal Coding Assistant) (✅ DONE)

Atlas climbs the Learning-Level ladder (§5d.6) over the **Code store** — from merely
*storing* repositories to *understanding*, *connecting*, *generalizing*, and finally
*recommending*. The headline architectural move realises the S18b promise literally:
**"add sinks, not schema."** The one governed ledger (`learning.events`) gains a
pluggable **store sink**, and the Code store becomes the first non-Experience store
promoted through it — so repository learning is as *governed, explainable and
reversible* as everything else.

- **Store sinks on `LearningService`.** `register_sink(store, sink)` attaches a
  materialiser with `apply(payload) -> ref_id` + `revert(ref_id)`. `apply`/`revert`
  now route non-Experience stores through their sink; the Experience store stays the
  built-in one. `propose(..., apply=True)` is the public entry other learners use to
  record a governed event and (for an explicit act) promote it at once.
- **The Code store (migration 0012).** `learning.repositories` (L2 — a repo distilled
  to languages/frameworks/entry points/dependencies/graph size/**per-repo patterns**;
  re-learning a root replaces its active row) and `learning.patterns` (L4 — patterns
  **generalized across** repos, prevalence-scored; a recomputable materialised view).
- **`IntelligenceService` = the `intelligence` capability**, over `CodeCapability`
  (S14) artifacts:
  - **L2 Understand** — `learn_repository(root)` parses via `CodeService`
    (`repo_map`+`patterns`+`search_symbols`), builds the structure payload, and
    promotes it through the ledger (`CodeStoreSink`). Explicit ⇒ applied; still a
    reversible ledger event. Parsing errors are an `error` outcome, never an exception.
  - **L3 Connect** — `search(query)` (cross-project retrieval) + `connections()` (link
    repos sharing frameworks/languages).
  - **L4 Generalize** — `generalize()` mines the prevalence of each pattern/framework/
    language across learned repos, keeping those ≥ `generalize_min_prevalence`
    ("you *always* use the Repository pattern"); persisted via `replace_patterns`.
  - **L5 Recommend** — `recommend(context)` turns generalizations into proactive advice
    (auto-generalizing if needed); `profile()` summarises "who you are as an engineer".
- **Config** `intelligence.*` (`enabled`, `default_policy=project`,
  `generalize_min_repos`, `generalize_min_prevalence`, `recommend_top_k`). Concrete
  **`IntelligenceCapability`** contract (catalog `CAP_INTELLIGENCE`, since S19).
  **Surface:** `POST /v1/intelligence/repositories`, `GET .../repositories[/{id}]`,
  `GET .../search`, `.../connections`, `POST .../generalize`, `GET .../patterns`,
  `POST .../recommend`, `GET .../profile`; `atlas intel
  learn|repos|search|connections|generalize|patterns|recommend|profile`.

> **Design line:** what is *learned* (governed, reversible) is the **repository (L2)**;
> L3/L4/L5 are **inferences** over that governed data, so they are recomputed views
> rather than separately-governed truths. This keeps the governance model coherent
> while still delivering the full "Atlas learns *you*" story.

**Definition of Done (S19)** — all met:
- [x] Migration 0012 Code store (`learning.repositories` + `learning.patterns`, status-checked, unique-active-root).
- [x] `LearnedRepository` + `EngineeringPattern` models; `IntelligenceRepository` (repo CRUD + search, pattern replace/list, counts).
- [x] `LearningService` **store-sink registry** (`register_sink`/`propose`) — governed promotion into non-Experience stores; `CodeStoreSink`.
- [x] `IntelligenceService` (`intelligence` cap): L2 `learn_repository` / L3 `search`+`connections` / L4 `generalize` / L5 `recommend`+`profile`; honest outcomes.
- [x] `IntelligenceCapability` contract + catalog (`CAP_INTELLIGENCE`, S19); `intelligence.*` config + defaults; bootstrap wiring + sink registration.
- [x] `/v1/intelligence/*` endpoints + `atlas intel` CLI.
- [x] Hermetic tests (L2–L5 ladder, sink routing, repo-fake, code-fake, api, cli, caps). **573 tests pass (+18).**
- [ ] **Next — S20:** Tier 2/3 tools as needed (browser automation, OCR, Git, DB, Email/LinkedIn).

---

## 7. Decision log (append-only)

| # | Date | Decision | Status |
|---|------|----------|--------|
| — | 2026-07-11 | Stage 2 framing = Research & Execution System; capability-first; planner spine before browser | Accepted |
| D1 | 2026-07-11 | Chat-Mode slice first, **Job Engine is the north star** → Planner + ToolExecutor must be mode-agnostic (reused verbatim by async jobs) | ✅ Locked |
| D2 | 2026-07-11 | Planner v0 = deterministic rule-based router; LLM composes answers only; LLM decomposition deferred to S12+ | ✅ Locked |
| D3 | 2026-07-11 | New `conversation.sessions` + `conversation.messages` schema; working memory via `memory.items` scoped to session | ✅ Locked |
| D4 | 2026-07-11 | Commit full Research + Execution + Continuous-Learning arc S10–S20 | ✅ Locked |
| R1 | 2026-07-11 | Multiple concurrent jobs; jobs isolated, one never freezes another | ✅ Locked |
| R2 | 2026-07-11 | Capability honesty: pre-flight + runtime Capability Gap Reports; never fail silently or fabricate | ✅ Locked |
| R3 | 2026-07-11 | Non-blocking HITL: a blocker pauses only its sub-task; job continues; blocked items reported and resumable | ✅ Locked |
| R4 | 2026-07-11 | Hardware: multi-core CPU, no GPU, 16GB→64GB. CPU-parallel I/O; single LLM lane (`llm.max_concurrency`, default 1); models sized to RAM | ✅ Locked |
| D7 | 2026-07-11 | LLM selection by **role** (chat/planner/researcher/summarizer/code/vision), not a named model; `LLMService` resolves; swap via config | ✅ Locked |
| D8 | 2026-07-11 | Verification is a first-class subsystem: verify by claim, evidence levels 1–5, calculated confidence, convergence stopping rule, Evidence Budget (§5a) | ✅ Locked · **shipped S15** (§6g) |
| Q7 | 2026-07-11 | Secrets/credentials stay in `.env` / `/etc/atlas`; never in DB or plaintext logs | ✅ Locked |
| D9 | 2026-07-11 | Code understanding = **Tier B**: tree-sitter parse + code-aware RAG + repo map + symbol index + import **& cross-file call graph** + dependency analysis + `code`-role LLM (§5b); **own sprint S14**; incrementally enrichable (feeds S18 learning) | ✅ Locked |
| D10 | 2026-07-11 | Resilient/polite fetching: throttle + backoff + robots + cache + provider fallback; block → skip that source, job continues (§5c) | ✅ Locked |
| D6 | 2026-07-11 | **Python execution sandbox = hybrid** (shipped S16, §6h): a `SandboxBackend` interface with a **subprocess** default (child interpreter + rlimit CPU/memory/file caps + hard timeout→killpg + scratch dir + stripped env + **network off by default**) and a **Docker** backend swappable via `sandbox.backend` for stronger isolation. Runs return an outcome (`ok`/`error`/`timeout`/`blocked`), never crash (R2/R3); results become **L5 evidence** (§5a.6). Subprocess is soft isolation (trusted-ish code); Docker is the hostile-code path | ✅ Locked |
| D13 | 2026-07-11 | **Resilient net layer is a shared foundation, not per-plugin** (`atlas/net/FetchClient`): every web-facing capability fetches through one polite client (per-domain throttle + robots + backoff/retry + cache) that **classifies outcomes** (`ok`/`blocked`/`skipped`/`error`) instead of raising, so jobs degrade not crash (R2/R3, §5c). **Document Reader** = the fixed Q8 nine-format set via shared extractors + a `DocumentService`/`DocumentCapability` that reports an outcome (never throws on a bad file). S13 split: **S13a** (reader + net) done; **S13b** (search D5 + downloader) next — §6d | ✅ Locked |
| D12 | 2026-07-11 | **Job Engine = one step per self-re-enqueuing `advance_job` task** (not one task per whole job): short tasks interleave many jobs on the worker pool (R1) without a long job starving the scheduler; steps sequential per job (Q1). `blocked` is non-fatal and cascades to dependents (R3); reboot recovery re-hydrates jobs/steps (Q10) — §6c | ✅ Locked |
| D11 | 2026-07-11 | **Continuous Learning = third pillar** (Continuous Engineering Intelligence, §1b/§5d): `LearningCapability`; **five stores** (Knowledge/Memory/**Code**/**Experience**/Conversation); Learning Levels L1–L5; **governed** promotion (Temporary/Project/Personal/Verified) — explainable, reviewable, reversible, never silent; code **Pattern Mining**. Roadmap: S18 Learning Pipeline + **S19 Engineering Intelligence**; former tools sprint → **S20** (arc now S10–S20) | ✅ Locked |

## 8. Progress log (append-only)

| Date | Sprint | Notes |
|------|--------|-------|
| 2026-07-11 | — | Stage 2 plan drafted from `stage-2.txt`; gap analysis vs Stage 1; roadmap + open decisions D1–D6 raised for discussion |
| 2026-07-11 | — | D1–D4 locked (chat-first w/ Job-Engine north star; deterministic planner; new conversation schema; full arc). Sprint 10 detailed in §6a; ready to build |
| 2026-07-11 | — | Requirements R1 (multiple concurrent jobs), R2 (capability honesty / gap reports), R3 (non-blocking HITL) locked into §1a; Job Engine step-state model + Capability Gap Report added; ambiguities Q1–Q10 catalogued in §4b with defaults |
| 2026-07-11 | — | User answers Q1–Q6/Q10: added R4 (CPU/no-GPU/16GB → parallel I/O + single LLM lane), D7 (role-based LLM selection), D8 (Verification Engine + Evidence Graph, §5a). Roadmap re-cut to S10–S18 (Verification split from Python execution). Q1–Q6/Q10 resolved; Q7–Q9 remain gated at S13. Plan finalized — S10 ready to build |
| 2026-07-11 | — | Q7 locked (env secrets); Q9→D10 locked (resilient/polite fetching, §5c); Q8 base doc set locked, **code files spun out into D9/§5b (CodeCapability: tree-sitter + code-aware RAG + repo map + graph)** — one open discussion: v1 depth tier + roadmap placement |
| 2026-07-11 | — | D9 locked: **Tier B** (adds cross-file call graph + dependency analysis), **own sprint S14** after Document Reader; long-term coding-assistant intent recorded (feeds S18 learning). Roadmap renumbered to **S10–S19**. **All ambiguities Q1–Q10 resolved — Stage 2 plan fully finalized.** |
| 2026-07-11 | — | **Finalization pass:** reordered decisions to D8→D9→D10; D9 decision-log row set to ✅ Locked; §5b re-cast from "discussion" to **LOCKED Tier B / S14** (stale open questions removed); §4b note updated (only D5/S13 + D6/S16 intentionally deferred, nothing gates S10); §6a hardened with schema **grants**, S10 **config keys** (`llm.roles`/`max_concurrency`, `conversation.*`), explicit **build order**, and a **Definition of Done** checklist. Plan marked implementation-ready. |
| 2026-07-11 | S10 | **Sprint 10 shipped ✅.** Built: LLM **roles** + single lane (`LLMService.for_role`, semaphore; `llm.roles`/`max_concurrency`); migration **0009** (`conversation` schema + grants); `ConversationRepository` + models; `ConversationService` (session/history/context, working-memory scoped to session); `ToolExecutor` + `ToolResult` (`atlas/execution/`); deterministic **Planner** v0 (`atlas/planner/`); `ResponseBuilder` + **`AssistantService`** (`chat` service) with **capability-gap pre-flight (R2)**; `POST /v1/chat` + `/v1/chat/sessions[/{id}]`; `atlas chat` REPL/one-shot. **275 tests pass** (was 214; +61). **Live 5-test acceptance passes** end-to-end in one session (list→ingest→ask w/ citation→remember→recall). DoD met. |
| 2026-07-11 | S11 | **Sprint 11 shipped ✅ — Capability Contracts.** New `atlas/capabilities/` (runtime_checkable Protocols + capability ids + `CAPABILITY_CATALOG`); registry gains `contract`/`verify`/`missing`/`contract_of` + contract in `describe()`; services (llm/knowledge/agent/memory/conversation) and plugins (filesystem/web) declare contracts; planner tags steps with canonical ids; **AssistantService gap pre-flight now registry-driven + catalog-enriched (R2)**; `GET /v1/capabilities` + `atlas capabilities` inventory (provided vs missing + unlocks). **285 tests pass (+10).** |
| 2026-07-11 | S13a | **Sprint 13a shipped ✅ — Document Reader + Resilient Net Layer.** Expanded extractors to the Q8 nine-format set (pdf/docx/pptx/xlsx/csv/md/txt/html/json; deps `python-docx`/`python-pptx`/`openpyxl`); new `atlas/documents/` **`DocumentService`** (`document` capability) with outcome classification (ok/unsupported/empty/error, R2); scan + `atlas ingest` now read all formats; `GET /v1/documents/formats` + `atlas formats`. New **`atlas/net/`** **`FetchClient`** (D10/§5c): per-domain throttle + `robots.txt` + bounded backoff/retry w/ jitter + response cache, returning structured **outcomes** (`ok`/`blocked`/`skipped`/`error`) — never raises (R2/R3); `WebPlugin` rewired onto it; top-level `net.*` config. **343 tests pass (+31).** S13b (search D5 + downloader) is next. |
| 2026-07-11 | S12 | **Sprint 12 shipped ✅ — Job Engine.** Migration **0010** (`job` schema: `job.jobs` + `job.steps` w/ `depends_on`/`blocked_reason`/`attempts` + grants); `Job`/`JobStep` models + `JobRepository`; **`JobPlanner`** (deterministic fallback + optional planner-role LLM decomposition, D2c); **`JobService`** — one-step `advance_job` task that **re-enqueues itself** so jobs interleave (R1) while steps stay sequential (Q1); **`blocked`/`skipped`** states + dependency **cascade** (R3), `resume_job`/`cancel_job`, reboot recovery (Q10). Reuses chat dispatch via new **`AssistantService.run_step`** + `blocked` outcome (D1); missing capability/file → `blocked` not failed (R2/R3). Config `jobs.*`; `scheduler.workers`→3. `POST/GET /v1/jobs[/{id}][/resume|/cancel]` + `atlas jobs`/`atlas job …`. **312 tests pass (+27).** |
| 2026-07-11 | — | **D11 locked — Continuous Learning made the third pillar.** Vision retitled *Research, Execution & Continuous Learning System*; added §1b (Continuous Engineering Intelligence) and §5d (`LearningCapability`; **five stores** incl. new **Code** + **Experience**; capability→learns-from→produces table; **Learning Levels L1–L5**; **Continuous Learning Policy** + **Learning Governance** Temporary/Project/Personal/Verified — explainable/reviewable/reversible). `CodeCapability` gains **Pattern Mining** (§5b.1). Roadmap: **S18 Learning Pipeline**, **S19 Engineering Intelligence** (NEW), former tools → **S20** (arc now **S10–S20**). §2 mapping, §5 diagram + building blocks + contracts, D4 scope updated. |
| 2026-07-11 | S14 | **Sprint 14 shipped ✅ — Code Understanding (`CodeCapability`, Tier B, D9).** New `atlas/code/`: **Python parsed via stdlib `ast`** (symbols/imports/**call sites**, full fidelity) + **tree-sitter** (`tree-sitter-language-pack`) for JS/TS/TSX/C/C++/Rust/Go/Java/Bash/SQL (symbols+imports); honest per-file outcomes (`ok`/`shallow`/`unsupported`/`error`, R2). **Repo map** (manifests → deps/frameworks/entry points), **symbol index**, **import + cross-file call graph** (Python-first, conservative resolution — builtins ignored, ambiguous counted not guessed), **pattern mining** (Repository/Service/Registry/pytest/Docker/Postgres/UUID/dataclasses/async/framework, evidence-backed → feeds S19). **`CodeService`** = `code` capability: `parse`/`repo_map`/`index`/`search_symbols`/`graph`/`patterns`/`explain`; **code-aware chunking → knowledge** (one chunk per symbol) and **`code`-role LLM `explain`** grounded on structure. Concrete **`CodeCapability`** contract (catalog `CAP_CODE` now provided). `POST /v1/code/*` + `atlas code …`; `code.*` config. Deps `tree-sitter`+`tree-sitter-language-pack`. **421 tests pass (+51).** Next: **S15 Verification & Evidence Graph (D8)**. |
| 2026-07-11 | S16 | **Sprint 16 shipped ✅ — Python Execution Sandbox (D6, *hybrid*).** New `atlas/sandbox/`: a `SandboxBackend` swap point — **`SubprocessBackend`** (default) runs `python -I -B` in a child with a POSIX `preexec_fn` applying **rlimits** (CPU/`RLIMIT_AS` memory/file size/no-core), a **hard wall-clock timeout** that kills the whole **process group** (`start_new_session`+`killpg`), a **scratch workdir**, a **stripped env**, and (default) an in-interpreter **network block**; **`DockerBackend`** = selectable placeholder that honestly reports unavailable (R2) so stronger isolation drops in later via `sandbox.backend`. `ExecutionResult` (`ok`/`error`/`timeout`/`blocked`, stdout/stderr truncation, `duration_ms`, structured `result` from `result.json`, artifacts) — **never raises** (R2/R3). **`PythonSandboxService`** = `python` capability (`run`/`run_file`, per-run uuid workdir under `paths.data/sandbox`). Planner `run_python` intent (fenced code / "run python…") + `AssistantService._do_run_python` (honest output/error/timeout/blocked) + `JobPlanner` support. Concrete **`PythonExecutionCapability`** (`CAP_PYTHON`, S16). `sandbox.*` config; `POST /v1/python/run` + `atlas python`. **478 tests pass (+34).** Next: **S17 research loop + HITL & reports**. |
| 2026-07-11 | S15 | **Sprint 15 shipped ✅ — Verification Engine + Evidence Graph (D8/§5a), *the differentiator*.** New `atlas/evidence/` (serialisable **Evidence Graph**: `Source`/`EvidenceItem`/`ClaimValue`/`Claim`/`EvidenceGraph` — claims are persistent + **re-verifiable**) and `atlas/verification/` (pure, no LLM/I/O): **Evidence Levels L1–L5** (quality not count); `convergence()` = largest-cluster agreement ∈ [0,1] (`3.7/3.9/4.0/3.8`→1.0, `2/11/6/4`→low); **calculated confidence** HIGH/MEDIUM/LOW/INSUFFICIENT (0.6·convergence + 0.4·quality, contradiction penalty; single/low-level source never HIGH) with a human `reasoning_trace`; **Evidence Budget** + `decide()` continue/stop w/ explicit unmet criteria (stop on *convergence*, not paper count). **`VerificationService`** = `verification` capability (`verify(graph, budget?)` → per-claim decision), wired in bootstrap; `research.*` config (`ResearchConfig`). `POST /v1/verify` + `atlas verify graph.json`. Scope = engine/graph/budget primitives; live gather→verify→decide loop + scientific-review Report Generator land **S17**, Python results become **L5** at **S16**. **444 tests pass (+23).** Next: **S16 Python Execution Sandbox**. |
| 2026-07-12 | S19 | **Sprint 19 shipped ✅ — Engineering Intelligence (the Personal Coding Assistant; D11/§5d).** Atlas climbs the Learning Levels over the **Code store**. Headline: **"add sinks, not schema"** made literal — `LearningService` gains a **store-sink registry** (`register_sink`/`propose`); `apply`/`revert` route non-Experience stores through their sink, so the **Code store** is promoted through the *same* governed, reversible ledger as the Experience store. Migration **0012**: `learning.repositories` (L2 — repo distilled to languages/frameworks/entry-points/deps/graph-size/per-repo patterns; unique active root) + `learning.patterns` (L4 — patterns generalized across repos, prevalence-scored view). New `LearnedRepository`/`EngineeringPattern` models + `IntelligenceRepository`. **`IntelligenceService`** = `intelligence` cap over `CodeService` (S14): **L2** `learn_repository` (parse→structure→promote via `CodeStoreSink`; explicit⇒applied, reversible; errors are outcomes not exceptions), **L3** `search`+`connections` (link repos sharing frameworks/langs), **L4** `generalize` (prevalence of patterns/frameworks/languages ≥ threshold — "you *always* use X"), **L5** `recommend`+`profile` (proactive advice + engineer profile). Concrete **`IntelligenceCapability`** (`CAP_INTELLIGENCE`, S19); `intelligence.*` config + defaults; bootstrap wiring + sink registration. `/v1/intelligence/*` (`repositories`/`search`/`connections`/`generalize`/`patterns`/`recommend`/`profile`); `atlas intel …`. Design: the governed/reversible unit is the **repository (L2)**; L3–L5 are recomputed inferences over it. **573 tests pass (+18).** Next: **S20 Tier 2/3 tools**. |
| 2026-07-12 | S18b | **Sprint 18b shipped ✅ — Learning Pipeline (Continuous Learning, the third pillar; D11/§5d).** Atlas stops being amnesiac, *without* silently learning. New migration **0011** `learning` schema: **`learning.events`** = the governed ledger (what=`summary`/why=`reason`/from-where=`origin`, `policy` temporary/project/personal/verified, `level` L1–L5, `status` **proposed→applied→reverted**) and **`learning.experiences`** = the **Experience store** (problem→diagnosis→actions→mistakes→solution→lessons; `reverted` hides w/o deleting). New `LearningEvent`/`Experience` models + `LearningRepository` (CRUD + lexical `search_experiences`). **`LearningService`** = concrete `learning` cap: `observe_job` distils a finished job into a **proposed** Experience (never silent; `auto_apply` off by default, best-effort, never fails a job); `apply(policy?,level?)` creates the store record + stamps the event; `revert` deactivates it (reversible); `remember_experience` (manual→applied) + `recall` (lexical) + `explain` (what/why/where). Concrete **`LearningCapability`** contract replaces the S18 catalog placeholder. `JobService._finalize` observes after the report (guarded); `LearningConfig` (`enabled/observe_jobs/auto_apply/default_policy/default_level/recall_k`, conservative defaults) + `learning:` YAML; bootstrap container/caps/lifecycle. `GET/POST /v1/learning/*`; `atlas learn events|show|apply|revert|experiences|recall`. Scope = ledger + Experience store + job observation + review/apply/revert/recall; promotion into the other stores + Learning Levels L2–L5 = **S19** (ledger already models `store`/`level`). **555 tests pass (+23).** Next: **S19 Engineering Intelligence**. |
| 2026-07-11 | S18a | **Sprint 18a shipped ✅ — Deeper Research Sources (Scholarly + YouTube).** New `atlas/search/scholarly.py`: a `ScholarlyProvider` protocol → `Paper` (title/authors/year/venue/abstract/DOI/citations) + `as_source()` in the Evidence-Graph shape, graded on the **Evidence Level** scale (§5a.2). **`ArxivProvider`** (arXiv Atom, keyless; preprints ⇒ **L3**) + **`SemanticScholarProvider`** (Graph API, keyless/optional-key; published ⇒ **L4**), both over the resilient net layer (translate outcomes, never raise). **`ScholarPlugin`** = `scholar` cap (tool `scholar.search`) with **provider fallback**; output carries `results` + graded `sources`. New `atlas/transcripts/`: **`YouTubeTranscriptProvider`** (watch-page `captionTracks` → timedtext XML → decoded cues; **L1** evidence; outcomes not exceptions) + **`YouTubePlugin`** = `transcript` cap (tool `youtube.transcript`). Planner **`scholar_search`** (ahead of web search) + **`youtube_transcript`** (ahead of web fetch) intents + `AssistantService` handlers + `JobPlanner` support. `ScholarCapability`/`TranscriptCapability` contracts (`CAP_SCHOLAR`/`CAP_TRANSCRIPT`, S18). `plugins.scholar`/`plugins.youtube` config; both enabled. `POST /v1/scholar` + `/v1/youtube/transcript`; `atlas scholar`/`youtube`. **532 tests pass (+35).** Split from the Learning Pipeline (S18b next). |
| 2026-07-11 | S17 | **Sprint 17 shipped ✅ — Non-blocking HITL & Report Generator (§5a.5).** New `atlas/reports/`: **`ReportGenerator`** = pure/deterministic assembly of the nine scientific-review sections (Exec Summary→Answer→Confidence→Methodology→Evidence→References→Conflicting Views→Limitations→Next Research) from *verified* claim dicts + sources; **overall confidence derived** (most-common, tie→conservative), conflicting-views auto-flag (contradictions/weak), next-research from low-confidence/non-converged claims, optional `summarizer`-LLM polish (deterministic fallback), Markdown render. **`ReportService`** = `reports` capability: `report()` verify→render pipeline (Verification Engine) + `render()` direct. **Job Engine**: report auto-attached on finalize (`result.report`/`report_sections`/`overall_confidence`, best-effort, never fails the job); **`list_blocked()`** HITL queue across jobs; **`job.step_blocked`/`job.finalized`** event notifications (Q2). Surface `POST /v1/report` + `GET /v1/jobs/blocked`; `atlas report` + `atlas jobs --blocked`. **497 tests pass (+19).** Autonomous multi-round research orchestration deferred to **S18**. Next: **S18 Deeper Research + Learning Pipeline (D11)**. |
| 2026-07-11 | S13b | **Sprint 13b shipped ✅ — Web Search (D5) + Downloader.** **D5 locked → DuckDuckGo** (keyless HTML) default: new `atlas/search/` (`SearchProvider` protocol + `SearchResponse`/`SearchHit` + `DuckDuckGoProvider` unwrapping `uddg` redirects) and **`SearchPlugin`** (`search` capability, tool `web.search`) with an **ordered provider list → provider fallback** (SearXNG/Brave drop in via config); all over the resilient net layer so blocked/rate-limited backends degrade (R2/R3), never crash. New **`DownloaderPlugin`** (`downloader`, `web.download`) → size-capped fetch to a sandbox-confined downloads dir, honest block/skip. Planner gains **`web_search`** intent + `AssistantService._do_web_search` (lists results, reports blocked/empty honestly); `JobPlanner` accepts it. `POST /v1/search`; `atlas websearch`/`download`; `plugins.search`/`plugins.downloader` config, both enabled. **370 tests pass (+27).** Next: **S14 Code Understanding (D9)**. |
