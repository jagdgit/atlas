# Atlas — Stage 3 Plan & Discussion (From an Operating System to a *Researcher*)

> **Status:** 🟢 **PLANNED — gating decisions LOCKED (2026-07-12).** Ready to build on your go.
> The gating Open Decisions (§7) are resolved from your answers; the build sequence (§8) is
> firm. First increment: **Workspace + Source Classifier (C3)**.
> **Started:** 2026-07-12
> **Source vision:** the user's "stop designing, start building — build the Research
> Worker" critique (2026-07-12) after the first two real research runs on
> *"data-driven soiling estimation for solar panels"*.
> **Builds on:** Stage 1 (Sprints 1–9) + Stage 2 (S10–S23) — see `docs/IMPLEMENTATION_PLAN.md`
> and `docs/STAGE_2_PLAN.md`. Test suite at Stage 2 close: **782 passing.**
> **Purpose:** Stage 2 proved Atlas is an *AI operating system*. Stage 3 asks a harder,
> narrower question: **can Atlas actually do one complete piece of research, correctly,
> end-to-end?** We stop adding layers and prove one workflow.

---

## 0. How to use this document

- **§2 Diagnosis** is the honest teardown of the two real runs, grounded in the actual code
  (file + line references). Read this first — it is *why* Stage 3 exists.
- **§3 The thesis** is the one idea Stage 3 is built around: the missing **READ** stage.
- **§7 Open Decisions** is where we **discuss**. Each has options, a recommendation, and a
  status (`OPEN` / `LOCKED`). **Nothing is built until the gating decisions are `LOCKED`.**
- **§8 Capabilities & acceptance tests** replaces sprint numbering (per the user's
  recommendation): we measure Atlas by *what it can accomplish*, proven by an acceptance test.
- **§12 Questions for you** is the short list I need answered to start.

---

## 1. The pivot (again — but sharper)

Stage 2's north star was *"you are building a Research, Execution & Continuous Learning
System, not a chatbot."* We built the **machine**: kernel, capability registry, planner,
durable Job Engine, Verification Engine + Evidence Graph, Report Generator, Learning
pipeline, Web Console. All of it works and is tested.

Stage 3's north star is different and deliberately humble:

> **Prove ONE complete workflow. The *Research Worker*.**
> Given *"Research X"*, Atlas must go from prompt → verified, cited report that reflects
> the **content of real documents it actually read** — not a list of links it found.

The user's key insight, which this whole document accepts:

> *"You have successfully built an AI operating system. You have not yet built a
> researcher. Those are two very different things. The missing capability is no longer
> architecture — it's **cognition**. Atlas needs to learn how to **study**, which is a
> very different problem from learning how to **search**."*

If the Research Worker works once, we have exercised nearly every subsystem for real, and
the **same engine** (Acquire → Read → Extract → Verify → Learn) becomes the Code Worker
(ingest a *repository* instead of a *paper*) and later the Engineering Worker (100 repos).

---

## 2. Diagnosis — what the two real runs actually proved

The prompt was *"Research data-driven soiling estimation for solar panels."* It ran the
real `ResearchService` loop (`atlas/research/service.py`). Both runs finished
`completed`, produced a report, and reported **`INSUFFICIENT` / "No verified claims"**
despite finding 8 then 21 relevant sources including IEEE, ScienceDirect, Wiley, and arXiv.

That is not a crash — it is Atlas doing **exactly** what the code says. Here is the teardown,
mapped to source.

### 2.1 There is no READ stage (the root cause)
The loop's `_gather()` builds evidence from **search-result snippets and abstracts only** —
it never downloads or reads a document:

- Web hits → a `Source` + an `EvidenceItem` whose `snippet` is the ≤300-char search snippet
  (`atlas/research/service.py`, `_gather`, ~L211–225).
- Scholar hits → the paper **abstract** (~L206–210).

The document readers already exist and are **not wired in**: `atlas/ingestion/extractors.py`
(`extract()` handles PDF/HTML/DOCX/PPTX/XLSX/CSV/JSON/MD/TXT) and the downloader plugin
(`web.download`, `atlas/plugins/downloader_plugin.py`). The research loop calls **neither**.
→ *Atlas retrieves; it never studies.*

### 2.2 Source classification is broken (the "everything is L2" bug)
Every web hit is hardcoded to L2, regardless of domain:

```python
# atlas/research/service.py (~L219)
src = Source(
    id=sid, title=..., url=...,
    evidence_level=LEVEL_TECHNICAL,  # <-- always L2, ignores the domain
    kind="web",
)
```

So `ieeexplore.ieee.org`, `sciencedirect.com`, `wiley.com`, `arxiv.org` found **via web
search** all become *"L2 technical blog."* Only the scholar provider (Semantic Scholar)
assigns L4 (via `paper.as_source()`), which is why run 2 showed a *few* L4 rows and the rest
L2. The budget then says *"need ≥3 peer-reviewed (have 0)"* — **because the classifier threw
the peer-reviewed signal away.** There is no domain→level map anywhere in the codebase.

### 2.3 There is exactly one "claim" — and it's the question itself
The loop creates a single claim equal to the objective and attaches all snippets to it:

```python
# atlas/research/service.py (~L141)
claim = Claim(id="c1", statement=objective)
```

There is **no claim extraction**. The evidence model is rich enough for real claims —
`Claim`, `EvidenceItem` (with `locator`, `stance`, `extracted_value`, `unit`) in
`atlas/evidence/models.py` — but nothing ever populates atomic claims like *"model X reduced
soiling-estimation RMSE from A to B."* Hence the report's **"No verified claims"** is
structurally guaranteed: you cannot verify a statement you never extracted.

### 2.4 "Convergence" is measuring noise
`extract_value()` takes the **first non-year number** out of a title/snippet
(`atlas/research/service.py`, ~L70–84) and the Verification Engine converges those numbers.
So "56% convergence" is agreement among **arbitrary numbers scraped from snippets**, not
among comparable quantitative findings. The Verification Engine itself
(`atlas/verification/engine.py`) is sound — per-claim confidence, convergence, reasoning
trace — it is just being **fed URLs and snippet-numbers instead of claims.**

### 2.5 "12 rounds" is retry-with-synonyms, not iterative research
The plan is a fixed cross-product of query suffixes:

```python
# atlas/research/service.py (~L44)
_VARIANTS = ("", "data", "study", "measurement", "statistics", "review")
# scholar then web, per variant  ->  6 x 2 = 12 rounds
```

It re-searches *"… data", "… study", "… review"* and accumulates more snippets. There is no
reading, no gap analysis, no *"I still lack a government source, search NREL."* It is search
breadth, dressed as iteration.

### 2.6 There is no job Workspace
Job artifacts live only inside the DB `result` JSON. Nothing is written to disk per job:
no downloaded PDFs, no extracted claims, no `evidence.json`, no `report.md`. Debugging,
reproducibility, and auditing are therefore very hard.

### 2.7 Summary
| Symptom in the report | True cause in code |
|---|---|
| "No verified claims" after 21 sources | No READ/extract stage; the only claim is the objective |
| "0 peer-reviewed" despite IEEE/Elsevier/Wiley | Web hits hardcoded to L2; no domain classifier |
| "12 rounds", still INSUFFICIENT | Fixed query-variant cross-product, not gap-driven iteration |
| Confidence 0.585 / 56% convergence | Convergence over arbitrary snippet numbers |
| Nothing to inspect afterward | No per-job workspace / artifacts |

**Verdict:** the pipeline is `Search → (snippet pseudo-evidence) → Verify → Report`. The
subsystems are real; the **workflow is wrong**. Stage 3 fixes the workflow.

---

## 3. The thesis — one pipeline, many sources

Every symptom above is the same missing middle. Atlas must insert **READ + EXTRACT** between
search and verification, and it must be the **same pipeline for every source type**:

```
            ┌─────────── the universal Atlas pipeline ───────────┐
Objective → Plan → ACQUIRE → READ → EXTRACT → EVIDENCE GRAPH → VERIFY → REPORT → LEARN
                    (get the   (turn it   (structured   (claims,   (per-   (per-    (knowledge,
                     bytes)     into text) claims, not    not URLs)  claim)  claim)   embeddings,
                                           chunks)                                    experience)
```

Non-negotiable properties that fell out of §2:

1. **Verification never sees a URL.** It only ever sees `Claim → EvidenceItem → Source`.
2. **A source becomes evidence only after it is read.** "Found a paper" ≠ "have evidence."
3. **The same Acquire→Read→Extract path serves papers, PDFs, HTML, YouTube, and code.**
   A repository is just another thing you *read and extract from*. This is why proving the
   Research Worker also (largely) proves the Code Worker.

The user's framing, adopted verbatim as the Stage-3 acceptance bar:

> *Given a paper URL, Atlas can download it, read it, extract structured claims, equations,
> datasets, and experimental results, and add those to an evidence graph. Once that works,
> every source of information flows through the same Acquire → Read → Extract → Verify →
> Learn pipeline.*

### 3a. Cross-cutting requirements (LOCKED — apply to every Stage-3 increment)

These are hard requirements from you, not options. Every capability below must honour them.

- **RS — Self-aware from now.** Atlas learns from *everything we do*, starting immediately.
  Every job (and notable action) emits a governed, reversible **Experience** (Stage 2 §5d),
  read documents flow into Knowledge, and Atlas can answer *"what have you done / learned /
  read so far?"* Learning is **on by default** during Stage 3 — not a final-milestone
  afterthought. (Governed + reversible via the existing learning ledger.)
- **RL — Watchable live.** When you're at the screen, you can **watch a job work in real
  time**: the current step, what it's searching, which document it's reading (e.g. "reading
  4/12: *Data-Driven Soiling Detection…*"), claims extracted so far, and each stop/continue
  decision — streamed to the Web Console, not just visible after completion.
- **RC — Responsive chat.** A simple/general question (*"what is the stock market?"*) must be
  answered by **one** LLM call and return in roughly a single generation — never the
  multi-call ReAct tool-loop. The heavyweight agent (tool catalog prompt + reason/act
  iterations) is reserved for queries that genuinely need tools or actions. Chat must not
  hit the LLM timeout on plain questions. (This is the immediate bug behind
  *"request to /api/chat failed: timed out"* on trivial questions — see §7 D3.12.)

---

## 4. Reuse map — build the gap, not another plugin

Per the user: *"Don't build plugin #11. Prove plugins 1–10 work together."* Most of the
pipeline already exists in parts; Stage 3 is mostly **wiring + one new cognition stage**.

| Pipeline stage | Already exists? | Plan |
|---|---|---|
| Plan | ✅ `JobPlanner` + deterministic `Planner` | Reuse; make plans **typed data** (§5b) |
| Acquire (download) | ✅ `web.download` (downloader plugin) | Reuse; wrap in an Acquisition step with paywall handling |
| Acquire (paywall/login) | ⚠️ net layer returns `blocked` | Reuse the R3 **blocked-step / resume** mechanism (Stage 2) |
| Read PDF/HTML/Office | ✅ `atlas/ingestion/extractors.py` | Reuse `extract()` directly |
| Read scanned PDF | ✅ `ocr.image` plugin | Fallback when `extract()` returns `None` |
| Read video | ✅ `youtube.transcript` plugin | Reuse |
| **Extract claims/equations/data** | ❌ **does not exist** | **NEW — the core Stage-3 subsystem (§5f)** |
| Evidence Graph | ✅ `atlas/evidence/models.py` (rich) | Reuse; feed it real claims |
| Verify | ✅ `VerificationEngine` (sound) | Reuse; feed claims, report per-claim |
| Report | ✅ `ReportService`/generator | Extend: per-claim confidence + artifact manifest |
| Learn/Store | ✅ Knowledge + Learning services | Reuse at end of a successful job |
| **Source classifier (domain→level/type)** | ❌ **missing** | **NEW — small, mostly deterministic (§5c)** |
| **Job Workspace (on-disk artifacts)** | ❌ **missing** | **NEW — per-job directory (§5a)** |
| **Task DSL (declarative plan)** | ⚠️ steps exist as rows | **Formalize step contracts (§5b)** |

So Stage 3 introduces **three genuinely new things** (Extraction, Source Classifier,
Workspace) and **re-wires** the rest. No new external plugin.

---

## 5. Proposed new subsystems (design sketch — details pending §7)

### 5a. Job Workspace
Every job gets an isolated directory so work is durable, inspectable, and reproducible:

```
atlas_data/jobs/job_<id>/
    plan.json            # the typed plan (§5b)
    search/              # raw search results per query
    downloads/           # acquired files (pdf/html/…)
    documents/           # normalized extracted text per source
    claims.json          # extracted structured claims
    evidence.json        # the serialized Evidence Graph
    notes.md             # loop trace / gap analysis
    report.md            # final report
    manifest.json        # what was found/downloaded/read/extracted/verified
```

Debugging becomes *"open the workspace"*; a crash loses nothing; auditing is trivial.
Retention/cleanup policy is **Open Decision D3.5**.

### 5b. Task DSL (plans are *data*, not code)
Represent a job as a declarative, validated plan the executor consumes — so the planner
"produces data instead of code":

```yaml
objective: "data-driven soiling estimation for solar panels"
budget: { min_sources: 8, min_peer_reviewed: 3, max_documents_read: 12 }
steps:
  - id: s1  op: search_web        args: { query: "...", k: 10 }
  - id: s2  op: search_scholar    args: { query: "...", k: 10 }
  - id: s3  op: classify_sources  needs: [s1, s2]
  - id: s4  op: acquire           needs: [s3]  args: { top_k: 12, open_access_first: true }
  - id: s5  op: read              needs: [s4]
  - id: s6  op: extract_claims    needs: [s5]
  - id: s7  op: verify            needs: [s6]
  - id: s8  op: report            needs: [s7]
  - id: s9  op: learn             needs: [s8]
```

We already persist `job.steps` rows with `intent/capability/args/depends_on`; the DSL is
mostly a **typed op vocabulary + validation** layer on top. Whether to build a full DSL now
or just add typed step contracts is **Open Decision D3.6**.

### 5c. Source Classifier (domain + metadata → type + evidence level)
A small, mostly deterministic service. Input: a URL (+ optional DOI/metadata). Output:
`{ source_type, evidence_level, access_method }`.

| Domain / signal | Type | Level |
|---|---|---|
| `nrel.gov`, `sandia.gov`, `*.gov`, national labs | government/lab | L3 |
| `ieeexplore.ieee.org`, `sciencedirect.com`, `wiley.com`, `nature.com`, DOI-backed | peer-reviewed | L4 |
| `arxiv.org`, `*.labs.arxiv.org` (preprint) | preprint | L3 |
| dataset repositories, measured field data | field data | L5 |
| `youtube.com` (talk/presentation) | presentation | L2 |
| vendor blogs, Medium, manufacturer white-papers | technical blog | L2 |
| `reddit.com`, forums, LinkedIn | discussion | L1 |

Fixes §2.2 immediately. Whether classification is a **static domain map**, **metadata via
Crossref/DOI**, or **both**, is **Open Decision D3.4**.

### 5d. Acquisition Service
For each classified, prioritized source: attempt to fetch the full document (prefer
open-access/PDF; arXiv/ar5iv HTML for preprints). On a hard paywall/login wall, **do not
fabricate** — mark the step `blocked` with an honest reason (reusing Stage-2's non-blocking
HITL / resume) and continue with what is accessible. Cost/volume limits → **D3.2**;
paywall policy → **D3.3**.

### 5e. Reader Service
Normalize any acquired artifact to a common `Document` representation
(`{ source_id, title, sections[], text, tables[], figures?, metadata }`) using the existing
`extract()` extractors, OCR fallback for scanned PDFs, and transcript for video. One shape,
regardless of origin — so extraction is source-agnostic.

### 5f. Knowledge / Claim Extraction — **the heart of Stage 3**
Turn a read `Document` into **structured claims**, not chunks/embeddings:

```
Claim:      "A CNN model reduced soiling-loss estimation RMSE from 3.1% to 1.2%."
Value:      { number: 1.2, unit: "%", kind: "rmse" }
Source:     ieee:10049391
Locator:    "Section 4.2, Table III"
Stance:     support
```

These populate the existing `Claim`/`EvidenceItem` model directly. **How** to extract —
LLM-based, deterministic patterns, or hybrid — and whether it's even feasible on this
CPU/RAM box, is the single biggest **Open Decision (D3.1 + D3.9).**

### 5g. Evidence Graph wiring
Group extracted claims across sources (same finding from multiple papers → one claim with
several supporting `EvidenceItem`s; disagreements → `contradict` stance). Verification then
operates on **claims with real multi-source support** — exactly what the engine was built for.

### 5h. Verification (unchanged engine, correct inputs)
Run `VerificationEngine.verify_claim` **per extracted claim** after extraction. Report
per-claim confidence, not a single job-level number (§5i). The stop rule becomes gap-driven:
*"I have claims but no L3/government source → search government domains,"* rather than
*"append another synonym."*

### 5i. Report (per-claim + artifact manifest)
Report shows, per the user's ask:
```
Downloaded 6 papers → Read 5 → Extracted 127 claims → Verified 83 → Rejected 44
Claim 1  HIGH    (5 peer-reviewed, converge)
Claim 2  MEDIUM  (2 papers + 1 preprint)
Claim 3  LOW     (single source)
```
plus Executive Summary, Methodology, Evidence, References (real, from read sources),
Conflicting Views, Limitations, Future Work — and a link to the job workspace.

### 5j. Learn / Store
On a successful, sufficiently-confident job: ingest read documents into Knowledge (chunks +
embeddings), record an Experience (governed, reversible — Stage 2 §5d), and persist the
evidence graph so future jobs can reuse it. Governed by the existing learning ledger.

---

## 6. Capabilities, not sprints (the measurement shift)

Per the user: *"stop numbering sprints; switch to Capabilities with acceptance tests."*
Stage 3 is measured by these. A capability is "done" **only** when its acceptance test passes
on a real run (not a unit test).

| # | Capability | Acceptance test (real run) |
|---|---|---|
| C0 | **Watch it work (RL)** | While a job runs, the Web Console shows a live activity feed: current step, current query, document being read (n/total), claims extracted so far, and each stop/continue decision. |
| C1 | **Read one document** | Given a paper URL, Atlas acquires it (or uses metadata+abstract when gated), extracts text, and stores artifacts in the job workspace. |
| C2 | **Extract claims** | From an abstract (Tier 1) or full text (Tier 2), Atlas produces ≥N structured claims with values, locators, and source. |
| C3 | **Classify sources** | IEEE/Elsevier/Wiley→L4, arXiv→L3, NREL/`*.gov`→L3, YouTube→L2, forums→L1. |
| C4 | **End-to-end research** | Given a topic, Atlas produces a report with **verified claims, per-claim confidence, and real citations from content it read** — never "No verified claims" when relevant papers were read. |
| C5 | **Gap-driven iteration + recommend** | Atlas searches to fill a *named* evidence gap (not synonym cycling), and when the doc cap is hit it **recommends** specific further reading (title + why). |
| C6 | **Self-aware learning (RS)** | Every completed job leaves reusable knowledge (embeddings + governed Experience); Atlas can report what it has done/learned/read. |
| C7 (Stage 4) | **Learn one repository** | Given a repo path, Atlas explains its architecture, indexes symbols, learns patterns — *same engine, `code` reader*. |

Milestones (user's roadmap): **M1** complete one research job to a verified report (C1–C6) →
**M2** learn one repository (C7) → **M3** 100 repositories → M4 coding assistant → M5 research
assistant → M6 digital-twin platform. **Stage 3 = M1.** Everything after M2 is out of scope here.

---

## 7. Decisions

Gating decisions (**D3.1, D3.2, D3.3, D3.9, D3.10**) plus D3.8 and D3.11 are **LOCKED**
(2026-07-12, see §11). D3.4–D3.7 remain `OPEN` but are non-gating — we decide them as we reach
the relevant increment. Each entry keeps its options for the record.

### D3.1 — How do we extract structured claims? — **LOCKED**
**Decision (2026-07-12): Hybrid extraction over a *tiered* reading depth.**
- **Tier 1 (always, cheap):** for *every* candidate source, extract from **metadata +
  citation info + the abstract**. Get as much signal as possible from abstracts first, since
  they're freely available. This is the reliable floor and drives early confidence.
- **Tier 2 (when accessible):** read the **full text** for sources that are open-access, that
  the classifier ranks highly, or that **you provide later** (some papers need login — see
  D3.3). Atlas must be **capable of reading an entire paper clearly when required**, not just
  the abstract.
- **Mechanism (both tiers):** the **hybrid** extractor — deterministic pass for
  numbers/units/tables + a bounded `researcher`-role LLM pass for prose claims, with strict
  JSON validation (drop anything unparseable).
- **Rationale:** abstract-first makes every run useful even fully paywalled; full-text is
  earned by access, not assumed. Fits "deterministic core, LLM improves," and the CPU budget.

### D3.2 — How many documents does a job acquire/read? — **LOCKED**
**Decision (2026-07-12):** cap **`max_documents_read` = 10–12** for now (default **12**), while
honoring the Evidence Budget. **Atlas must recommend when more reading is warranted** — when it
hits the cap with an unmet gap, it surfaces a ranked *"recommended further reading"* list
(title + why it matters) rather than silently stopping, so you can approve reading more.

### D3.3 — Paywalled / login-required sources? — **LOCKED**
**Decision (2026-07-12):**
- **Open access → Atlas reads it directly** (arXiv/ar5iv/PMC/open PDFs).
- **Login/paywall required → Atlas pauses and asks you** (reuses Stage-2 non-blocking HITL /
  `blocked` step + resume). You then either **provide the document/data** (Atlas ingests it and
  resumes) or **choose to skip** it (Atlas notes the gap and continues). Atlas never fabricates
  content it couldn't read.
- Browser-rendered full-text is **deferred** (the "plugin #11" temptation).

### D3.4 — Source classification mechanism?
- **(a) Static domain map** (fast, offline, covers the 80%).
- **(b) Metadata/DOI via Crossref** (authoritative venue/type, adds a network call).
- **(c) Both** — map first, DOI to refine when present.
- **Recommendation:** **(c)**, shipping **(a)** first so C3 passes offline immediately.

### D3.5 — Workspace location & retention?
- Where: `atlas_data/jobs/job_<id>/` (recommended). Retention: keep last N jobs / N days /
  keep forever; cleanup on success vs. always.
- **Recommendation:** keep everything by default; add a `jobs.workspace_retention` knob later.

### D3.6 — Full Task DSL now, or typed step contracts?
- **(a) Full declarative DSL** (YAML/JSON plan, validated op vocabulary).
- **(b) Extend existing `job.steps`** with a typed **op** enum + arg schemas (less churn).
- **Recommendation:** **(b) first** (fastest path to a correct pipeline), design the DSL as
  the serialization of (b) so we don't paint ourselves into a corner.

### D3.7 — Verification model for non-numeric claims?
- Numeric convergence stays for quantitative claims. For prose claims, add **multi-source
  agreement** (K independent sources asserting the same claim → higher confidence) and
  contradiction detection.
- **Recommendation:** add qualitative agreement; keep numeric convergence for values.

### D3.8 — Adopt "capabilities + acceptance tests" and stop sprint numbering? — **LOCKED**
**Decision (2026-07-12): Yes.** `IMPLEMENTATION_PLAN.md` stays as history; Stage 3 progress is
tracked by the §6 capability table + acceptance tests.

### D3.9 — Is local extraction even feasible on this hardware? — **LOCKED**
**Decision (2026-07-12):** Yes, via the tiered/queued approach (with D3.1/D3.2). The box is
**15 GiB RAM (swapping), CPU-only**, `qwen3:4b`, so: **abstract/metadata first** (cheap, always),
**section-scoped** full-text extraction (abstract + results/conclusions + tables) only for
accessible/ranked docs, run as **queued per-document steps** (progress + resumable, never one
giant call), under a hard **document cap** (D3.2). A larger extraction model can be swapped in
later (config-only) if RAM allows.

### D3.10 — Stage 3 scope boundary? — **LOCKED**
**Decision (2026-07-12):** Stage 3 = **Research Worker (C0–C6 / Milestone 1)**. Code Worker
(C7) and Engineering Worker are **Stage 4**. **Caveat (RS):** *continuous, self-aware learning
is switched ON now* — Atlas learns from everything we do during Stage 3 (governed/reversible),
even though the deep code-learning *capabilities* wait for Stage 4.

### D3.12 — How do we make chat responsive (RC)? — **LOCKED**
**Problem:** `Planner.plan()` routes every open-ended message to the `REACT` fallback
(`atlas/planner/planner.py` ~L579), so a plain question runs the ReAct agent — multiple LLM
calls, each carrying the full tool catalog — and times out on CPU. `SMALLTALK` already proves
the cheap path: a single `compose()` call in `AssistantService._do_smalltalk`.
**Decision (2026-07-12):**
- **(a) Add a fast `answer` path** — a single chat-model call with conversation context (like
  smalltalk, but for questions). Make it the **default fallback** instead of ReAct.
- **(b) Escalate to ReAct only on explicit tool/action signals** — the message needs current
  data or an action (e.g. "search", "latest/today", a URL, "run/execute", "download",
  "browse", a file path), or the user explicitly asks Atlas to *do* something. Otherwise answer
  directly.
- **(c) Interactive timeout + honest fallback** — a shorter wall-clock for interactive chat
  than for background jobs; on timeout, return a clear message, never a 2-minute hang.
- **(d) Streaming (stretch)** — stream tokens to the Console so even a few-second answer feels
  instant. Poll-based feed first (aligns with RL/D3.11); SSE later if needed.
- **Trade-off accepted:** ambiguous questions that *might* have benefited from autonomous tool
  use will get a direct answer instead; heavy tool work is what **jobs** are for. This matches
  "deterministic, fast for the simple case."

### D3.11 — How does the live "watch it work" view (RL) get its data? — **LOCKED**
**Decision (2026-07-12): build it in.** Steps already persist and the Console already polls
`/v1/jobs/{id}` every 2s. Stage 3 adds a per-job **activity feed** (progress events written to
the workspace + emitted on the event bus): each op logs human-readable progress
("searching scholar: …", "reading 4/12: …", "extracted 12 claims", "decision: continue — no
government source"). The Console renders this feed live for a running job. Start with
poll-based (simple, works today); upgrade to server-sent events only if 2s polling feels laggy.

---

## 8. Build sequence (gating decisions LOCKED — this is the plan)

Capability increments, each ending in its acceptance test (not sprint numbers). Each step
keeps the full suite green and adds a real-run acceptance check.

0. **Responsive chat fix** (RC / D3.12) — *quick win, do first; independent of the research
   pipeline.* Add a fast single-call `answer` path and make it the default fallback; reserve
   ReAct for tool/action queries; add an interactive timeout. Fixes the *"api/chat timed out"*
   on trivial questions. Acceptance: *"what is the stock market?"* answers in one generation,
   no timeout.
1. **Workspace + Source Classifier** (C3) — foundations; deterministic; fully testable offline.
   Per-job `atlas_data/jobs/job_<id>/` (§5a) + domain→type/level map (§5c).
2. **Live activity feed** (C0 / RL) — per-job progress events → workspace + event bus; Console
   renders a live feed for running jobs (poll-based). Landed early so we can *watch* the rest
   of Stage 3 build itself out.
3. **Acquisition + Reader, tiered** (C1 / D3.1 Tier 1→2, D3.3) — wire `web.download` +
   `extract()`/OCR/transcript; **abstract/metadata first**, full text when open-access;
   **pause & ask** on login walls (you provide the doc or skip); artifacts to the workspace.
4. **Claim Extraction** (C2 / D3.1) — the hybrid extractor (deterministic + bounded LLM),
   section-scoped, run as **queued per-document steps** (progress + resumable). Biggest new
   subsystem.
5. **Evidence wiring + per-claim Verification + Report** (C4) — feed **claims, not URLs**, to
   the engine; per-claim confidence; artifact manifest (found/downloaded/read/extracted/verified).
6. **Gap-driven iteration + recommend-more** (C5 / D3.2) — replace synonym cross-product with
   evidence-gap targeting; at the doc cap, surface ranked *"recommended further reading."*
7. **Self-aware learning** (C6 / RS) — ingest read docs into Knowledge + record a governed
   Experience per job; Atlas can report what it has done/learned/read. (Switched on from
   step 1's jobs onward, wired fully here.)

---

## 9. Non-goals for Stage 3 (explicit)

- ❌ No new external plugin (no "plugin #11"). Browser automation stays deferred (D3.3c).
- ❌ No Code Worker / Engineering Worker yet (Stage 4).
- ❌ No LinkedIn/CV/personal-assistant capability yet.
- ❌ No new "architecture layer." Stage 3 adds exactly one cognition stage (extraction) +
  two supports (workspace, classifier) and **wires the rest.**

---

## 10. Risks

- **R-A: Extraction quality on CPU.** Mitigate via D3.9 (section-scoped, capped, queued).
- **R-B: Paywalls block full text.** Mitigate via open-access-first + honest blocking (D3.3).
- **R-C: Extractor breadth.** PDFs vary wildly; start with arXiv/ar5iv HTML + text-layer PDFs,
  OCR as fallback; accept partial reads and record them in the manifest.
- **R-D: Scope creep back into "architecture."** This document's job is to prevent that —
  every increment must map to a §6 acceptance test.

---

## 11. Decision Log (append-only)
- **2026-07-12 — D3.1 LOCKED:** Hybrid extraction over tiered depth. Tier 1 = metadata +
  citations + **abstract** for all candidates; Tier 2 = full text when open-access/ranked/
  user-provided; Atlas must read a full paper when required.
- **2026-07-12 — D3.2 LOCKED:** `max_documents_read` = 10–12 (default 12); Atlas **recommends**
  further reading when the cap is hit with an unmet gap.
- **2026-07-12 — D3.3 LOCKED:** Open access → read directly; login/paywall → **pause & ask**;
  user provides the doc/data or skips; never fabricate. Browser full-text deferred.
- **2026-07-12 — D3.8 LOCKED:** Adopt capabilities + acceptance tests; stop sprint numbering.
- **2026-07-12 — D3.10 LOCKED:** Stage 3 = Research Worker (C0–C6). Code/Engineering = Stage 4.
  **RS caveat:** self-aware continuous learning is ON now.
- **2026-07-12 — D3.11 LOCKED:** Live "watch it work" feed via per-job progress events +
  Console polling (SSE only if needed).
- **2026-07-12 — RS / RL LOCKED (cross-cutting):** self-aware learning from now; every job is
  watchable live.
- **2026-07-12 — RC / D3.12 LOCKED:** responsive chat — fast single-call `answer` path as the
  default fallback, ReAct only on tool/action signals, interactive timeout, optional streaming.
  Scheduled as build **Step 0** (quick win). Fixes trivial-question timeouts.
- *Still OPEN (non-gating, decide as we reach them): D3.4 (classifier mechanism — shipping
  static map first), D3.5 (workspace retention), D3.6 (typed steps vs full DSL), D3.7
  (qualitative claim agreement).*

---

## 12. Status of the discussion

All gating questions answered (2026-07-12) and locked in §7 / §11:
- ✅ D3.1 — tiered abstract-first, hybrid, full-text when available/required.
- ✅ D3.2 — cap 10–12 (default 12) + recommend-more.
- ✅ D3.3 — open-access direct; login → pause & ask (provide or skip).
- ✅ D3.10 — Research Worker scope; **self-aware learning ON now** (RS).
- ✅ D3.8 — capabilities + acceptance tests.
- ✅ New: RL (watch it work live) + D3.11 (how).
- ✅ New: RC (responsive chat) + D3.12 — fast single-call answers; scheduled as build **Step 0**.

**Next action:** begin **Step 1 — Workspace + Source Classifier (C3)** — the smallest, safest,
fully-offline first win. Remaining OPEN items (D3.4–D3.7, D3.5 retention) are non-gating and
will be decided as we reach them.
