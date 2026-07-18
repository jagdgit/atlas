# Atlas — Stage 3B Plan (Knowledge & Learning Foundation)

> **Status:** ✅ **FINALIZED**; **3B.0–3B.5 complete** (2026-07-17). Stage 3B engineering closed;
> §10 code close-out done (soft-bias wiring, provenance edges, tier honesty, review worker).
> Operator remaining: Benchmark Set live run + one live acceptance topic (D3B.14).
> Gating decisions **D3B.1–D3B.30** and defaults **A3B.1–A3B.25** are locked (§11–§12).
> Architecture is frozen.
> **Hardening pass (2026-07-18)** applied post-BM-001 live eval — quality/correctness + UI status
> fixes (§16), then a wave-2 fix for the Acquire→Read→Extract batch-discard regression, exec-summary
> honesty, and a per-source Pipeline Trace (§16.7); wave-3 closes the first feedback-loop half with
> **advice-only operational source-reliability learning** (`source:{domain}`) (§16.8); wave-4 hardens
> **document ingestion** (main-content HTML extraction, paywall detection) + grouping/cap fidelity
> so peer-reviewed sources yield claims (§16.9).
>
> **Purpose:** Define Atlas’s reusable **knowledge operating system** *before* Stage 4
> (Engineering Intelligence), so Atlas finishes becoming a researcher whose knowledge is
> measurable, retrievable, synthesized, maintained, traceable, and reusable — not only a
> research *pipeline*.
>
> **Prerequisite:** Stage **3.2a–3.2e** shipped. See `docs/STAGE_3_2_PLAN.md`.
> **Companion history:** Stage 3 Research Worker spine — `docs/STAGE_3_PLAN.md`.

---

## 0. How to use this document

| Section | Role |
|---------|------|
| §1–§3 | Why 3B, honest status, Stage 3A vs 3B |
| §4 | Target architecture (knowledge OS) |
| §5 | Capability deep-dives |
| §6 | Learning taxonomy |
| §7 | Committed phases 3B.0 → 3B.5 |
| §8 | Stage 4 / 5 relationship |
| §9 | Non-goals |
| §10 | Acceptance criteria |
| §11 | Locked decisions D3B.* |
| **§12** | **Locked implementation defaults A3B.*** |
| **§13** | **Implementation blueprint (files, order, acceptance)** |
| **§14** | **Frozen checklist (no open ambiguities)** |
| §15 | Decision log |
| **§16** | **Hardening pass — post-BM-001 live eval (2026-07-18)** |

---

## 1. Why stop before Stage 4

Atlas is at the point where adding more *domains* (code, personal) without consolidating
the *foundation* will create technical debt.

```
                    Atlas Kernel
                          │
            ┌─────────────┴─────────────┐
            │                           │
   Knowledge Infrastructure    Execution Infrastructure
   (Access, Evidence, Graph,   (Jobs, Scheduler, RM,
    Lifecycle, Experience)      Execution Planner, LLM lanes)
            │                           │
            └─────────────┬─────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
    Research         Engineering        Personal
    Intelligence     Intelligence      Intelligence
    (Stage 3)        (Stage 4)         (Stage 5)
```

**Central decision (locked):**

> Build one knowledge operating system beneath Research, Engineering, and Personal
> Intelligence — do not build three intelligence stacks that each invent retrieval,
> evidence, memory, and learning.

---

## 2. Where Atlas stands today (honest)

### 2a. Is Research Intelligence finished?

| Lens | Verdict |
|------|---------|
| **Functional** | **Yes** — research jobs run end-to-end with findings, reasoning, reports |
| **Architectural** | **Yes for 3B scope** — shared Access Layer, durable findings, lifecycle, experience learning. Live Benchmark / operator acceptance remain operator-owned (D3B.14). |

### 2b. Stage 3A complete (Research Pipeline)

Job Engine, Workspace, Resource-aware execution, Readers, Verification, Evidence Graph models,
Reports, Learning ledger, Gap-driven research, Source classification — all shipped.

### 2c. Codebase ground truth (post–3B.5)

| Area | Status |
|------|--------|
| Knowledge search | Hybrid dense+lexical RRF via global `retrieve(..., role=)` |
| Chat RAG | `RagAgent` → Access Layer (`role=chat`); soft bias after apply+enable |
| Findings | `EvidenceSynthesizer` → `knowledge.findings` + append-only lifecycle |
| Learning | Rich Experience payloads + component observations; advice-only recall |
| Capabilities | Spec has cost/version/metrics; retrieval/synthesis/lifecycle provided |
| Evaluation | Hermetic baselines + Benchmark Set seeded (`not_run` until live run) |
| Memory tiers | Live tier = knowledge; working/session deferred; archive opt-in filter |

### 2d. Stage 3B capabilities (all shipped)

| # | Capability | Status |
|---|------------|--------|
| 1 | Evaluation Framework | ✅ 3B.0 |
| 2 | Knowledge Access Layer | ✅ 3B.1 |
| 3 | Evidence Synthesizer | ✅ 3B.2 |
| 4 | Knowledge Lifecycle + Freshness | ✅ 3B.3 |
| 5 | Memory Hierarchy | ✅ (honest: knowledge live; others deferred) |
| 6 | Knowledge Quality + Provenance | ✅ (dimensions + parent edges) |
| 7 | Cross-document reasoning | ✅ 3B.4 |
| 8 | Component Experience Learning | ✅ 3B.5 |

---

## 3. Reframe Stage 3 (locked)

```
Stage 3 = Knowledge & Learning Foundation
          ├── Stage 3A  Research Pipeline          ✅ SHIPPED (incl. 3.2)
          └── Stage 3B  Knowledge Operating System  ← THIS DOCUMENT
              + Research Intelligence as first complete application
```

Stage 4 = same engine, new domain (engineering). Stage 5 = personal, after engineering.

---

## 4. Target architecture

### 4a. Hard rule

> Knowledge access, synthesis, lifecycle, provenance, quality, memory hierarchy,
> evaluation, and experience learning are **kernel/service-level**.
> Research *uses* them. Engineering and Personal *reuse* them. They must not live only
> inside `atlas/research/`.

### 4b. Package ownership (locked)

| Concern | Home |
|---------|------|
| Knowledge Access Layer | Extend `atlas/knowledge/` + **one global** retrieval service contract; RAG is a *consumer* |
| Evidence / Verification | Transient, re-verifiable claim/evidence models in `atlas/evidence/` + verification |
| Finding (durable) | **`knowledge.findings`** — durable home. Ownership chain: Evidence → Verification → Finding → Knowledge |
| Synthesis | Synthesis module (evidence-adjacent) writes Findings into knowledge store |
| Lifecycle / freshness / revisions | Finding store: append-only revisions + supersedes links |
| Provenance | Shared lineage records (embedded fields + parent edges) |
| Memory hierarchy | Tier router over existing conversation / memory / knowledge / learning stores + archive |
| Evaluation + Benchmark Set | `atlas/eval/` + `tests/eval/` / fixtures + fixed research-topic regression suite |
| Experience Learning | Extend `LearningService` / Experience store — do **not** replace the ledger |
| Cross-doc reasoning | Built on synthesizer outputs; research is first consumer |

### 4c. Knowledge Access path (locked pipeline order)

```
Document / Paper / Code / Note
  → Reader → Chunker + Metadata → Embedding → Vector (+ lexical index)
  → Retrieve (dense + lexical + metadata + temporal + tier routing)
  → Re-rank
  → Context Build (citations, provenance, budgets)
  → LLM / Agent / Research / Chat / Planner / …
```

**Never** Retrieve → LLM → Re-rank. Order is always **Retrieve → Re-rank → Context → LLM**.

Day-one: dense + lexical hybrid (equal RRF weights) + metadata/domain/temporal filters +
heuristic rerank. Persist per-hit `dense_score`, `lexical_score`, and `rrf_score` for later
tuning. Graph traversal and cross-encoder rerank are **interfaces now, depth later**
(A3B.5–A3B.6).

### 4d. Evidence / Finding path

```
Per-document claims
  → Evidence Synthesizer → Finding (support/contradict/quality/freshness/lifecycle)
  → Consolidation + Lifecycle (append revision / supersede / deprecate / archive)
  → Cross-document Reasoning (patterns, gaps, hypotheses)
  → Reports / Access Layer answers / next-job planning
```

### 4e. Memory hierarchy (locked)

```
Working Memory      current step/job state
Session Memory      current conversation/research episode
Knowledge Base      validated, *active* findings + source chunks
Experience          operational lessons and recommendations
Archive             deprecated/superseded findings and cold material
```

Archive is **excluded by default**; opt-in / fallback only. Access Layer selects tiers by
request purpose — not “search everything.”

### 4f. Capability descriptors — extend existing registry

Enrich `CapabilitySpec` / catalog entries with: I/O contract, cost class (reuse 3.2d),
dependencies, quality guarantees, metrics emitted, version. New capability ids as needed
(`retrieval`, `synthesis`, `knowledge_lifecycle`, …). **No second registry.**

### 4g. Provenance Graph

```
Answer → Finding → Claim → Chunk → Document → Reader/version → URL/path
```

Enables targeted invalidation when a parser/version is buggy.

---

## 5. Capability deep-dives (summary)

### 5a. Evidence Synthesizer

`group_claims` is the job-local ancestor. Stage 3B introduces durable **Findings** in
`knowledge.findings`: statement, support/contradict, confidence, quality profile, freshness,
lifecycle, claim_type, provenance, and **append-only revisions**.

**Ownership (locked):** Evidence is transient and traceable; Knowledge is durable.

```
Evidence → Verification → Finding → Knowledge (knowledge.findings)
```

Do **not** store canonical findings under an evidence-only schema.

**IDs (locked):** every finding has:

| ID | Role |
|----|------|
| Internal UUID | Immutable row identity |
| Stable canonical ID | Human-debuggable (e.g. `F-000042`) |
| Revision ID | Monotonic revision within the canonical finding (e.g. `3`) |

**Versioning (locked):** knowledge is **append-only**. New evidence creates a new revision;
never overwrite in place. Revisions carry `supersedes` / `superseded_by`. Active retrieval
sees the current head revision unless archive/history is requested.

**Merge policy (locked):** conservative. Prefer value+unit clusters + normalized statement;
embedding similarity as assist, not sole key. Surface contradictions; split contested findings
rather than silently averaging.

**Promotion (locked):** synthesize inside the job first, then promote/upsert into
`knowledge.findings` (job → durable), creating a new revision when the finding already exists.

### 5b. Knowledge Access Layer (single global service)

One API for **everything** — designed now even where Engineering/Personal are not yet callers:

```
retrieve(
    query,
    *,
    domains=None,
    tiers=None,
    filters=None,
    as_of=None,
    role="research",   # research | chat | planner | scheduler | engineering | personal | …
    k=None,
) → RankedContext

answer(query, context, *, role=...) → GroundedAnswer + citations
```

**Not** `retrieve_research()` / `retrieve_chat()`. Role is a parameter on one service.

Mandatory shared callers in 3B: chat / ask_knowledge / research prior-knowledge recall.
Planner/scheduler may call the same API for advice context. Engineering/personal reuse later
without API redesign.

**Pipeline (locked):** Retrieve → Re-rank → Context Build → LLM.

**Diagnostics (locked):** every ranked hit persists `dense_score`, `lexical_score`, and
`rrf_score` (plus any later ranker score) for evaluation and weight tuning.

### 5c. Lifecycle + freshness

Statuses: `active | contested | deprecated | superseded | archived`.
Freshness: `current | aging | stale` + `valid_from` / `valid_until` / `last_verified`.

**Freshness is knowledge-type aware** — newest does **not** automatically win over higher-
quality primary evidence. Software/API decays fast; stable science decays slowly unless
contradicted; standards use effective dates.

### 5d. Cross-document reasoning (v1)

Relationships (support/contradict/refine), pattern cards, research-gap discovery
(contradiction + missing variable → opportunity), typed **hypotheses** (never auto-promoted
as findings). No society-of-workers.

### 5e–5g. Quality, provenance, memory

- Confidence ≠ quality. Store a **dimension profile** first — do **not** invent a lone
  “Quality = 87%” without meaning. Dimensions (locked names):

  | Dimension | Meaning |
  |-----------|---------|
  | Research Quality | Method / study design fitness for the claim |
  | Extraction Quality | How faithfully text→structured was extracted |
  | Evidence Quality | Source strength / primary vs secondary |
  | Freshness | Currency-type-aware currency |
  | Completeness | Coverage of required variables / context |

  Optional **Overall Quality** may be derived later for ranking; never the only stored truth.
- Provenance: embedded fields **and** parent edges; bug → mark descendants stale + enqueue
  review/reprocess.
- Memory: tier-aware retrieval enforced by Access Layer.

### 5h. Evaluation (day one)

Fixtures + baselines + regression gates **before** sophisticated algorithms. Metrics cover
retrieval, grounding, synthesis, lifecycle, end-to-end. LLM-as-judge may supplement; labeled
fixtures + operator review are authoritative.

Maintain an **Atlas Benchmark Set**: 10–20 fixed research problems. Re-run after every
significant milestone (3B.0 → 3B.1 → … → Stage 4) as the regression suite. Live acceptance
topic remains operator-chosen; the benchmark set is separate and durable.

### 5i. Experience Learning

Job + **component+version** observations. Soft retrieve bias is **never automatic**:

```
Experience → Recommendation → Human Apply → Bias Enabled
```

Never:

```
Experience → Automatic Bias
```

**No** auto-rewrite of prompts/schedulers/pools/extraction in 3B. Soft retrieve-order bias
only after human apply (A3B.18); tiny boost only; never hides results.

---

## 6. Learning taxonomy (locked framing)

| System | Learns about | Stage |
|--------|--------------|-------|
| Knowledge Learning | The world | 3A partial → 3B deepens |
| Experience Learning | Atlas itself (jobs + components) | **3B** |
| Operator Learning | You | **Stage 5** |

Atlas has started learning by **accumulation** (~30–40% of eventual meaning). 3B adds
retrieval quality, evidence/ops experience, and measurable improvement.

---

## 7. Committed build order

Phasing is **order and safety**, not scope cut. Everything below is committed.

### 3B.0 — Evaluation + contracts foundation ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Evaluation corpus | Relevant-chunk, duplicate, contradiction, freshness, provenance fixtures | ✅ `tests/fixtures/eval/` |
| Metric contracts | Retrieval, synthesis, grounding, lifecycle, end-to-end | ✅ `atlas/eval/contracts.py` |
| Atlas Benchmark Set | 15 fixed research problems; milestone regression suite | ✅ seeded (`not_run`) |
| Registry extensions | CapabilitySpec cost/deps/version/metrics/quality + retrieval/synthesis/lifecycle stubs | ✅ |
| Baseline | Hermetic dense-style ranks + `group_claims` | ✅ `docs/eval_baselines.md` |
| Regression harness | Versioned `run_baseline_suite()` | ✅ `atlas/eval/baseline.py` |

**Acceptance:** fixtures run green; baseline numbers + Benchmark Set recorded; no production
retrieval algorithm change in 3B.0.

### 3B.1 — Knowledge Access Layer (global) ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Single global API | `retrieve(query, domains=, filters=, role=…)` | ✅ `KnowledgeService.retrieve` |
| Pipeline | **Retrieve → Re-rank → Context Build → LLM** | ✅ `atlas/knowledge/access.py` |
| Retrieval | Dense + lexical hybrid (equal RRF); persist scores | ✅ + `knowledge.retrieval_diagnostics` |
| Re-ranking | Heuristic v1; swappable interface | ✅ `heuristic_rerank` |
| Memory routing | Tiers + archive excluded by default | ✅ |
| Context builder | Token/char budget, citations, de-dup | ✅ `build_context` |
| Call sites | Chat (RagAgent), API search, research prior recall | ✅ |
| Evaluation | Hybrid holds/improves vs dense on toy fixture | ✅ `tests/test_access_layer.py` |

**Acceptance:** one `retrieve` serves chat + research (`role` param); archive excluded by
default; score diagnostics persisted; migration `0014_knowledge_access_fts.sql`.

### 3B.2 — Evidence Synthesizer ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Finding model | statement, support/contradict, confidence, quality dims, freshness, type | ✅ `Finding` |
| IDs | Internal UUID + stable canonical (`F-######`) + revision | ✅ (canonical on promote) |
| Store | **`knowledge.findings`** | ✅ migration `0015` |
| Synthesis pass | After extract/verify; evolves `group_claims` | ✅ `EvidenceSynthesizer` |
| Report integration | Prefer findings; fall back to claims | ✅ A3B.9 |
| Provenance | claim/source/job/component on Finding | ✅ |
| Evaluation | Merge/contradiction fixtures hold 3B.0 baselines | ✅ |

**Acceptance:** research deep path emits findings + `findings.json`; reports are finding-centric
when synthesis produces results; eval fixtures do not regress.

### 3B.3 — Knowledge Consolidation + Lifecycle ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Versioning | Append-only revisions; `supersedes` / `superseded_by` | ✅ |
| Upsert rules | Identity key + revise on content change | ✅ `KnowledgeLifecycleService` |
| Lifecycle | create/revise/deprecate/supersede/archive/reactivate | ✅ |
| Freshness | Type-aware policy (eval-aligned) | ✅ |
| Access index | Active heads; archive opt-in | ✅ `list_findings` |
| Invalidation | Stale + `finding_reviews` + `review_finding` task | ✅ |
| Evaluation | Freshness + supersession fixtures | ✅ |

**Acceptance:** second promote revises (does not overwrite); superseded rows retained; archive
excluded from default heads; migration `0016`.

### 3B.4 — Cross-document reasoning (v1) ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Relationship edges | support / contradict / refine | ✅ `CrossDocumentReasoner` |
| Pattern cards | Recurring ranges/methods | ✅ |
| Research gap discovery | Contradiction + gaps → opportunities | ✅ |
| Hypotheses | Explicit type; never auto-promoted as findings | ✅ `filter_out_hypotheses` |
| Report / activity | Patterns, opportunities, hypotheses sections | ✅ |
| Evaluation | Relationship + promotion-guard tests | ✅ `tests/test_reasoning.py` |

**Acceptance:** research emits `reasoning.json`; reports surface patterns/gaps/hypotheses without
false certainty; hypotheses never land in `knowledge.findings`.

### 3B.5 — Experience Learning (ops + components) ✅ COMPLETE

| Deliverable | Detail | Status |
|-------------|--------|--------|
| Rich job experience | readers, paywalls, timings, strategies, recommendations | ✅ `_experience_from_job` |
| Component observations | component + version (A3B.17 keys) | ✅ `learning.component_observations` |
| Recall into planning | Advice only by default | ✅ `advice_for` → research + JobPlanner |
| UI / API | Inspect; apply/revert; bias gate; components | ✅ API + CLI |
| Hard boundary | Recommend ≠ auto-rewrite; bias off until enable | ✅ |

**Acceptance:** finalize proposes structured experience (never auto-apply); component metrics
visible; applied advice recallable; soft bias only after apply + explicit enable; migration
`0017`.

**Dependency order:** **3B.0 → 3B.1 → 3B.2 → 3B.3 → 3B.4**. **3B.5** starts after 3B.0 and
grows alongside later phases.

---

## 8. Stage 4 / 5 after 3B

**Stage 4 — Engineering Intelligence:** new readers/parsers for repos, CAD, schematics, twins,
etc., plugged into Access Layer + Findings + Experience. Not invent RAG/synthesis again.

**Stage 5 — Personal Intelligence:** after Engineering; same knowledge/experience layers over
career/projects/decisions.

---

## 9. Non-goals for Stage 3B

- ❌ Stage 4 Engineering before Access + Synthesizer land
- ❌ Auto-rewrite prompts / schedulers / pools / extraction without human approval
- ❌ Multi-agent society-of-researchers as a 3B prerequisite
- ❌ Operator preference learning (Stage 5)
- ❌ Publisher paywall conquest as a 3B gate
- ❌ Forking Verification / Evidence Graph — extend them
- ❌ Research-only retrieval that Engineering cannot reuse
- ❌ A second Capability Registry
- ❌ “Newest always wins” regardless of quality
- ❌ Collapsing confidence/quality/freshness/provenance into one opaque score
- ❌ Searching all memory tiers indiscriminately
- ❌ Shipping algorithms without evaluation baselines
- ❌ Overwriting durable findings in place (must append revisions)
- ❌ Surface-specific retrieve APIs (`retrieve_chat` / `retrieve_research`) instead of one global service
- ❌ Retrieve → LLM → Re-rank (wrong order)
- ❌ UUID-only finding identity without stable canonical + revision IDs
- ❌ Automatic experience→bias without human apply
- ❌ Full graph-RAG / cross-encoder depth as day-one requirement (interfaces yes; depth later)

---

## 10. Acceptance criteria — Stage 3 complete

1. ✅ Research from multiple sources (3A).
2. ✅ Multi-format read/normalize (3.2a).
3. ✅ Global **Knowledge Access Layer** shared by chat + research.
4. ✅ **Synthesize** claims → canonical findings.
5. ✅ Detect agreement/contradictions at finding level.
6. ✅ **Lifecycle**: freshness, re-verify, supersede, archive.
7. ✅ **Provenance** embedded fields + parent edges on findings.
8. ✅ Distinguish **confidence** from quality dimensions.
9. ✅ **Memory hierarchy** routing (knowledge live; archive opt-in; others deferred honestly).
10. ✅ Cross-document patterns, research gaps, typed hypotheses (v1).
11. ✅ Job + component **experience** records (governed).
12. ✅ Reuse knowledge + experience in future work.
13. ✅ Explain conclusions **and** strategy preferences (traces + advice/explain).
14. ✅ Versioned **evaluation** metrics and regression gates (hermetic); Benchmark Set seeded.

**Operator-owned (D3B.14 / A3B.19) — not automatic:** execute BM-001…BM-015 live; choose one live acceptance topic.

---

## 11. Locked decisions (D3B.*)

| ID | Locked resolution | From |
|----|-------------------|------|
| **D3B.1** | Keep 3B inside Stage 3; do **not** open Stage 4 until 3B acceptance | Q1→A |
| **D3B.2** | Build order: **3B.0 → 3B.1 → 3B.2 → 3B.3 → 3B.4**; 3B.5 parallel after 3B.0 | Q2→C→A→B |
| **D3B.3** | Extend `atlas/knowledge/` + `atlas/evidence/`; no parallel `atlas/rag` product stack | Q3→A |
| **D3B.4** | Day-one retrieval: dense + lexical **hybrid** | Q4→B |
| **D3B.5** | Day-one rerank: **heuristic**; swappable interface for cross-encoder later | Q5→A |
| **D3B.6** | **One global** `retrieve(..., role=…)` for all surfaces — never per-surface retrieve APIs | Q6→A+ |
| **D3B.7** | Findings: synthesize in-job, then **promote** to durable store | Q7→C |
| **D3B.8** | Auto-merge: **conservative** | Q8→A |
| **D3B.9** | Contradictions: **surface and split** contested findings (both) | Q9→C |
| **D3B.10** | Experience Learning is **in** Stage 3B | Q10→A |
| **D3B.11** | Experiences default **propose/recommend only**; no auto-apply in 3B | Q11→A |
| **D3B.12** | Soft bias only via Experience → Recommendation → Human Apply → Bias Enabled | Q12→A (+ gated B) |
| **D3B.13** | Docs name Stage 3 “Knowledge & Learning Foundation”; Research Intelligence = first app | Q13→A |
| **D3B.14** | Live acceptance is **operator-owned**; plus durable **Atlas Benchmark Set** regression | Q14 |
| **D3B.15** | Full lifecycle: create/revise/deprecate/supersede/archive/reactivate | Q15→B |
| **D3B.16** | Freshness is **knowledge-type / version / effective-date** aware | Q16→B |
| **D3B.17** | Provenance = **embedded fields + parent edges** | Q17→C |
| **D3B.18** | Quality = **dimension profile first**; overall score only if derived later | Q18→C |
| **D3B.19** | Bug invalidation: mark descendants **stale** + enqueue review/reprocess | Q19→B |
| **D3B.20** | Explicit memory tiers: working/session/knowledge/experience/archive | Q20→A |
| **D3B.21** | Archive **excluded** unless requested/fallback | Q21→A |
| **D3B.22** | Evaluation (**3B.0**) before algorithm depth | Q22→A |
| **D3B.23** | Eval oracle: labeled fixtures + operator review (not LLM-judge-only) | Q23→A |
| **D3B.24** | Component experience = **component + version** (+ corpus/profile when known) | Q24→B |
| **D3B.25** | Extend existing Capability Registry/contracts/catalog — **no new registry** | Q25→A |
| **D3B.26** | Durable findings live in **`knowledge.findings`** (not under evidence) | Final review |
| **D3B.27** | Knowledge is **append-only**: revisions with `supersedes` / `superseded_by`; never overwrite | Final review |
| **D3B.28** | Retrieval pipeline order: **Retrieve → Re-rank → Context Build → LLM** | Final review |
| **D3B.29** | Finding IDs: internal UUID + stable canonical ID + revision ID | Final review |
| **D3B.30** | Persist retrieval diagnostics: `dense_score`, `lexical_score`, `rrf_score` | Final review |

**Legend:** ✅ locked for implementation.

---

## 12. Locked implementation defaults (A3B.*)

| ID | Topic | Locked default |
|----|-------|----------------|
| **A3B.1** | Finding identity | Prefer `(normalized_statement \| value+unit+kind)` + source-set overlap; embedding similarity assist only |
| **A3B.2** | Finding store | **`knowledge.findings`**; Evidence → Verification → Finding → Knowledge; job keeps episode copy |
| **A3B.3** | Lexical index | Postgres `tsvector` / FTS on chunk (+ finding) text for hybrid; no external search engine in 3B |
| **A3B.4** | Hybrid fusion | Equal-weight RRF of dense + lexical; **tune later via eval**; persist `dense_score` / `lexical_score` / `rrf_score` |
| **A3B.5** | Graph retrieve | Stub / provenance edge filters until eval proves benefit; no deep walk in 3B |
| **A3B.6** | Cross-encoder | Interface only; not required for 3B.1 acceptance |
| **A3B.7** | Domain filter | Wire `domains` through Access Layer + API; use researcher domains for research recall |
| **A3B.8** | Embed on promote | Findings/promoted docs become searchable (enqueue embed if needed) — no silent non-searchable promote |
| **A3B.9** | Report | Prefer findings; fall back to claims if synthesis empty |
| **A3B.10** | Hypothesis status | Explicit `hypothesis` / `open_question`; never auto-apply into active findings |
| **A3B.11** | Quality dimensions | Research / Extraction / Evidence / Freshness / Completeness — store all; Overall only if derived later |
| **A3B.12** | Provenance min fields | entity ids, transform type, component id+version, ts, source identity, parent ids |
| **A3B.13** | Invalidation UX | Activity + learning proposal; reprocess is scheduled task, not silent rewrite |
| **A3B.14** | Memory mapping | working→`memory` working; session→conversation(+session memory); knowledge→knowledge+findings; experience→learning; archive→lifecycle status |
| **A3B.15** | Eval location | `atlas/eval/` + `tests/eval/` / fixtures + **Atlas Benchmark Set** (10–20 fixed topics) |
| **A3B.16** | Experience schema | Extend Experience payload/JSON fields without breaking ledger governance |
| **A3B.17** | Component keys | Stable ids like `reader:html`, `reader:ocr`, `retrieval:hybrid`, `synthesizer:v1` |
| **A3B.18** | Soft bias | Experience → Recommendation → Human Apply → Bias Enabled; tiny boost only; never hides results; never automatic |
| **A3B.19** | Live acceptance | Operator chooses topic; Atlas does not auto-start; Benchmark Set is separate regression suite |
| **A3B.20** | Cost model | New LLM-heavy synthesis/retrieve-assemble tasks use existing RM LLM lane + static costs |
| **A3B.21** | Knowledge versioning | Append-only revisions with `supersedes` / `superseded_by`; never overwrite |
| **A3B.22** | Pipeline order | Retrieve → Re-rank → Context Build → LLM (never Retrieve → LLM → Re-rank) |
| **A3B.23** | Finding IDs | Internal UUID + stable canonical (`F-000042`) + revision ID |
| **A3B.24** | Access API shape | Single `retrieve(query, domains=[], filters=[], role="research")` for all future domains |
| **A3B.25** | Soft bias magnitude | Tiny rank boost only after apply; never hide or hard-filter results |

---

## 13. Implementation blueprint (grounded)

### 13.1 3B.0 — files & work

| Touch | Work |
|-------|------|
| `atlas/eval/` (new) | Metric helpers: precision@k, recall@k, citation coverage, merge accuracy |
| `tests/fixtures/eval/` | Golden corpora: relevant chunks, duplicates, contradictions, stale/fresh |
| `tests/eval/` | Baseline runners against current `KnowledgeService.search` + `group_claims` |
| Benchmark Set | Seed 10–20 fixed research problems + runner for milestone deltas |
| `atlas/capabilities/contracts.py` | Extend `CapabilitySpec`; add retrieval/synthesis/lifecycle stubs as needed |
| Docs | Record baseline numbers in decision log or `docs/eval_baselines.md` |

### 13.2 3B.1 — files & work

| Touch | Work |
|-------|------|
| `atlas/knowledge/` access module | Global `retrieve(..., role=)`; pipeline Retrieve→Re-rank→Context |
| Hybrid + diagnostics | Equal RRF; persist dense/lexical/rrf scores on each hit |
| Migration | `tsvector` indexes; retrieval diagnostics storage as needed |
| `atlas/agents/rag_agent.py` | Consume Access Layer, not private search path |
| `atlas/services/assistant_service.py` | ask_knowledge via shared retrieve |
| `atlas/research/` | Prior-knowledge recall via shared retrieve |
| `atlas/api/schemas.py` + routes | Expose domains/tiers/filters/`role` on retrieve |
| Tests | Hybrid vs dense; archive exclusion; citation integrity; score logging |

### 13.3 3B.2 — files & work

| Touch | Work |
|-------|------|
| `atlas/evidence/` | Transient claim/evidence + synthesizer; provenance helpers |
| Finding write path | Write durable rows into **`knowledge.findings`** with UUID + `F-######` + rev |
| `atlas/research/grouping.py` / service | Call synthesizer after extract/verify |
| `atlas/reports/` | Render findings |
| Workspace | `findings.json` (+ keep claims) |
| Tests | Merge/split/contradiction fixtures |

### 13.4 3B.3 — files & work

| Touch | Work |
|-------|------|
| Migration | `knowledge.findings`: status, freshness, validity, revision chain, quality JSON, provenance, canonical_id |
| Consolidation service | Append revision / supersede; never in-place overwrite of statement body |
| `atlas/research/learn.py` | Promote findings (searchable) |
| Invalidation | Stale mark + reprocess task type |
| Access Layer | Default active head revision; archive/history opt-in |
| Tests | Second-job new revision; supersede links; freshness policy cases |

### 13.5 3B.4 — files & work ✅

| Touch | Work |
|-------|------|
| `atlas/research/reasoning.py` | Edges, patterns, gaps→opportunities, hypotheses |
| Research deep path | Persist `reasoning.json`; activity note; pass into report |
| Reports | `patterns` / `opportunities` / `hypotheses` sections + next_research |
| Learn / promote | `filter_out_hypotheses` before finding promote |
| Tests | `tests/test_reasoning.py` (+ research/reports regression) |

### 13.6 3B.5 — files & work ✅

| Touch | Work |
|-------|------|
| `LearningService._experience_from_job` | Rich structured fields from pipeline/usage |
| `atlas/learning/components.py` | A3B.17 keys + observation helpers |
| Migration `0017` | `experiences.payload` / `bias_enabled` + `component_observations` |
| Recall | `advice_for` into research + JobPlanner (non-mutating) |
| Soft bias | `enable_bias` → tiny `heuristic_rerank` boost only |
| API/CLI | `/learning/advice`, `/components`, `/bias`; `atlas learn advice\|components\|bias` |
| Tests | Rich payload; propose-only; bias gate; component keys |

---

## 14. Frozen checklist (no open ambiguities)

Prior §14 items are **resolved**. Architecture for Stage 3B is frozen.

| Item | Locked resolution |
|------|-------------------|
| Findings schema | **`knowledge.findings`** — Evidence → Verification → Finding → Knowledge |
| Hybrid RRF weights | Equal now; tune later; persist dense / lexical / rrf scores |
| Quality score | Dimensions first; Overall Quality only if derived later |
| Soft retrieve bias | Experience → Recommendation → Human Apply → Bias Enabled; tiny boost only |
| Knowledge Access API | Single global `retrieve(..., role=…)` for all surfaces/domains |
| Graph retrieval depth | Stub until eval proves benefit |
| Live acceptance | Operator chooses; **Atlas Benchmark Set** for milestone regression |
| UI polish | Minimal Console first |
| Knowledge versioning | Append-only revisions with `supersedes` / `superseded_by` |
| Retrieval pipeline | Retrieve → Re-rank → Context Build → LLM |
| Knowledge IDs | UUID + stable canonical (`F-######`) + revision ID |

**No gating or non-gating architectural ambiguities remain.** Remaining work is engineering
and evaluation, starting at **3B.0**.

---

## 15. Decision log (append-only)

- **2026-07-17 — Document opened (discussion).** Pause Stage 4; finish knowledge foundation.
- **2026-07-17 — Architecture-review refinements.** Lifecycle, provenance, quality, memory
  hierarchy, component experience, evaluation as 3B.0; RAG → Knowledge Access Layer.
- **2026-07-17 — Plan FINALIZED for implementation.** Locked D3B.1–D3B.25 and A3B.1–A3B.20;
  blueprint §13. **Start at 3B.0** when operator says go.
- **2026-07-17 — Final freeze defaults.** Locked D3B.26–D3B.30 and A3B.21–A3B.25:
  `knowledge.findings`, append-only revisions, Retrieve→Re-rank→Context→LLM, finding IDs,
  retrieval score diagnostics, global `retrieve(role=)`, Benchmark Set, formal soft-bias path.
  Architecture ~98% complete; remaining work is implementation + eval.
- **2026-07-17 — 3B.0 complete.** Added `atlas/eval/` metrics + baseline suite; fixtures under
  `tests/fixtures/eval/`; Benchmark Set BM-001…BM-015; CapabilitySpec extended; catalog stubs
  for `retrieval` / `synthesis` / `knowledge_lifecycle`; baselines in `docs/eval_baselines.md`.
- **2026-07-17 — 3B.1 complete.** Global `KnowledgeService.retrieve` (dense+lexical equal RRF,
  heuristic rerank, context build); FTS migration + retrieval diagnostics; RagAgent / API /
  research prior-knowledge recall wired; `retrieval` capability provided.
- **2026-07-17 — 3B.2 complete.** `Finding` model + `EvidenceSynthesizer`; `knowledge.findings`
  + canonical seq; research deep path writes `findings.json` and prefers findings in reports;
  promote into FindingRepository; `synthesis` capability provided.
- **2026-07-17 — 3B.3 complete.** Append-only consolidation (`KnowledgeLifecycleService`);
  freshness policy; archive exclusion; component invalidation + review queue; `knowledge_lifecycle`
  capability provided.
- **2026-07-17 — 3B.4 complete.** Cross-document reasoning v1 (`atlas/research/reasoning.py`):
  support/contradict/refine edges, pattern cards, gap→opportunities, typed hypotheses;
  research persists `reasoning.json` and reports surface sections; hypotheses filtered before
  promote.
- **2026-07-17 — 3B.5 complete.** Experience Learning: rich job payloads; component+version
  observations (`0017`); `advice_for` into research/planner (non-mutating); soft bias only after
  apply + explicit `enable_bias`. **Stage 3B engineering closed.**
- **2026-07-17 — §10 code close-out.** Soft bias wired into `KnowledgeService.retrieve`; finding
  provenance parent edges; memory-tier honesty (live=knowledge); `review_finding` re-verifies;
  docs/baselines updated. Remaining: operator Benchmark Set + live acceptance.
- **2026-07-18 — Hardening pass (post-BM-001 live eval).** Reader/extractor/report/confidence
  quality fixes + UI status fix from the first live operator run. Details in §16.

---

## 16. Hardening pass — post-BM-001 live evaluation (2026-07-18)

The first live operator run (BM-001) surfaced quality issues that the architecture allowed but
did not yet guarantee. This pass hardened the research → synthesis → report path so Atlas can be
trusted as a production researcher. Architecture stays frozen; these are correctness/quality fixes.

### 16.1 Report ⇄ runtime consistency

- **Authoritative funnel counters.** `atlas/research/service.py` now computes a single, detailed
  pipeline dict (`read`, `reader_failures`, `paywalled`, `extract_ok/failed`, `numeric/prose/
  inferred_claims`, `edges`, `contradictions`, `patterns`, `opportunities`, `hypotheses`) and
  persists it as `pipeline.json`.
- **Serialization mismatch fixed.** Report re-render on job completion was losing rich data.
  `atlas/jobs/service.py` now loads `findings.json`, `reasoning.json`, and `pipeline.json` and
  passes them through `ReportService.render(..., pipeline=…)` →
  `ReportGenerator.generate(..., pipeline=…)`, so patterns/opportunities/findings that existed at
  runtime now appear in the final report.
- **Research Funnel section.** `atlas/reports/generator.py` renders a deterministic funnel table
  from the pipeline metrics; the executive summary prepends a deterministic sentence (findings
  assessed + overall confidence) so the LLM polish can no longer contradict the numbers.

### 16.2 Reader / normalization

- **Publisher landing → real PDF.** `atlas/research/acquire.py` resolves `citation_pdf_url`
  meta tags on publisher HTML landing pages and fetches the advertised article PDF instead of
  storing a near-empty landing page.

### 16.3 Extraction honesty & taxonomy

- **Deterministic qualitative (prose) extraction.** `atlas/research/extract.py` adds LLM-free
  cue-based extraction (comparison / finding / method / limitation / recommendation), so prose
  claims are captured even when the LLM extractor returns nothing.
- **Evidence vs inference.** `EvidenceItem.origin` (`extracted` vs `inferred`) marks verbatim
  quotes apart from LLM paraphrases; surfaced per-row in the report.
- **Claim taxonomy.** `Claim.claim_type` (result / parameter / method / conclusion / limitation /
  recommendation / comparison / observation). Reports headline results/conclusions/comparisons/
  limitations and relegate `parameter` claims (e.g. `q=0.9`, `80/20 split`, `30-day window`) to a
  dedicated **Parameters & Configuration** section.
- **Better zero-claim diagnostics.** Extractor records *why* few/no claims were produced.

### 16.4 Canonical identity & study-aware confidence

- **Canonical source identity.** `canonical_source_id` (DOI / arXiv id / normalized URL)
  collapses multiple representations of the same paper (arXiv abstract, PDF, ar5iv HTML). Candidate
  absorption dedups on it, preferring the richer representation.
- **Claim/finding dedup.** `atlas/research/grouping.py` preserves `claim_type` on merge and dedups
  identical standalone numeric claims (parameters) across sources by statement similarity.
- **Independent-study-aware confidence.** `atlas/verification/engine.py` counts distinct
  independent studies (not representations); HIGH now requires real breadth (≥3 independent
  sources, or ≥2 L3+ with high convergence and no contradictions). The reasoning trace explains
  “high convergence but capped confidence” when diversity is insufficient.

### 16.5 Report structure

- **Conflicts vs weak evidence separated.** `Conflicting Views` now lists only genuine
  contradictions; a new `Weakly Supported Findings` section holds low-confidence-but-uncontested
  claims. `next_research`/opportunities remain the research-gap channel.
- **Synthesis-oriented executive summary.** Leads with the top finding and synthesizes overall
  confidence, conflicts, and weak evidence instead of listing raw counts.
- **Theme patterns.** `atlas/research/reasoning.py` builds theme pattern cards from qualitative
  claims grouped by cue kind, in addition to method patterns.

### 16.6 UI job status (stuck on “planning”)

- **Root cause.** There is no push channel; the console SPA (`atlas/web/static/app.js`) live-updates
  only via a 2 s poll of `GET /v1/jobs/{id}`. The old poll did `catch (_) { stopJobPoll(); }`, so a
  single transient fetch/render error — most likely during the slow LLM planning phase, while the
  label reads `planning` (a `metadata.phase`, not a status) — permanently killed the poll. The
  status then froze until a hard refresh restarted polling.
- **Fix.** `startJobPoll` now tolerates transient failures (resets on success, only stops after
  `JOB_POLL_MAX_FAILURES = 8` consecutive errors) and keeps re-rendering each tick until the job
  reaches a terminal state — so the badge advances planning → ready/running → completed on its own.
- **Follow-up (not done here).** No `job.status`/`job.updated` event and no SSE/websocket exist; a
  future improvement is a real push/stream channel so updates don’t depend on polling at all.

### 16.7 Acquire→Read→Extract regression + pipeline trace (2026-07-18, wave 2)

A second live run showed the classic contradiction: runtime *“Text read ≈46.8 KB across 1
document”* while the Research Funnel showed **acquired 0 / read 0 / 0 findings** and no Read/Extract
events. Not architectural — an **implementation regression** in the Acquire→Read→Extract path.

- **Root cause.** `usage_stats()` counts files under `documents/`, written only when a doc has text
  — so one document *was* read (46.8 KB). But `map_parallel` re-raises worker exceptions
  (`fut.result()`), and `Librarian._process_one` ran `_read()` + the new `_maybe_resolve_pdf()`
  **outside any try/except**. A single source raising there (most likely the landing-page→PDF
  resolver added in §16.2) propagated up, and `ResearchService._acquire_unread`’s broad `except`
  swallowed the whole batch — discarding **every** already-read document. Hence funnel 0 despite a
  doc on disk, and the empty middle of the pipeline. This is the operator’s “Hypothesis #1
  (short-circuit)” — confirmed. (Hypotheses #2/#3 ruled out: `ExtractionResult.claims` is intact,
  and the funnel counters are correct — they just reflected the discarded batch.)
- **Fixes (defense-in-depth, so one bad source can never lose a batch):**
  1. `Librarian._process_one` — read + landing-page→PDF resolution wrapped per source; on error,
     record a `parse_error` skip with reason and continue (try the next candidate URL, then move on).
  2. `map_parallel` (`atlas/research/concurrency.py`) — isolate per-item worker failures: a raising
     item is logged and its slot dropped; **siblings always survive**. Applied to both acquire and
     extract; a `logger` is threaded through.
  3. `Librarian.acquire` merge loop — build a `by_source` map and merge documents even if a source
     can’t be mapped back for manifest/activity (never lose artifacts to a `StopIteration`).
- **Executive-summary honesty.** With **0 verified findings**, the summary no longer asserts a
  general-knowledge conclusion (e.g. *“Evidence confirms that soiling reduces solar panel output…”*).
  It now states Atlas *“identified N source(s) and read M, but was unable to extract any verifiable
  claims … no conclusion can be drawn … see the Research Funnel,”* and the LLM polish is **skipped
  entirely when there are no claims** so it can’t fabricate one. (`atlas/reports/generator.py`.)
- **Per-source Pipeline Trace (new).** `ResearchService._build_source_traces` emits one structured
  state object per source — searched → acquired → read (`reader`/`chars`/`sections`) → extracted
  (`numeric`/`qualitative`/`inferred`) → `distinct` → `verified` → `findings`, plus an explicit
  `status` (`ok`/`no_claims`/`read_failed`/`blocked`/`not_acquired`) and `failure_reason`. Persisted
  to `pipeline_trace.json` (and inside `pipeline.json`), summarized on the activity feed, and
  rendered as a **“Pipeline Trace (per source)”** table in the report. Regressions in any stage are
  now diagnosable per source in minutes.
- **Tests.** `test_acquire.py::test_one_source_read_exception_does_not_discard_batch`;
  `test_concurrency_32b.py::test_map_parallel_isolates_worker_failures`;
  `test_reports.py` honesty + trace-render cases; `test_research_deep.py` per-source-trace build +
  end-to-end. Full suite: **992 passed.**

### 16.8 Closing the loop — operational source-reliability advice (2026-07-18, wave 3)

The per-source Pipeline Trace (§16.7) made per-source outcomes *observable*; this closes the first
half of the feedback loop **Research → Knowledge → Experience → Recommendations → (human approval)
→ improved future research** by turning those outcomes into **accumulated, advice-only** retrieval
guidance. Still no autonomous behavior change — Atlas *recommends*, a human (or the informed planner)
*decides* (D3B: “experience produces recommendations first, never silent behavior”).

- **New component family `source:{domain}` (`atlas/learning/components.py`).** `domain_from_url()`
  normalizes hosts (`https://www.ieeexplore.ieee.org/x` → `ieeexplore.ieee.org`, bare hosts accepted);
  `source_component_key()` maps a URL/domain to `source:{domain}`.
- **Capture (governed).** `LearningService._experience_from_job` now folds the pipeline trace into
  per-domain acquisition outcomes (`_source_outcomes_from_trace`): `{ok, no_claims, read_failed,
  blocked, not_acquired, total, claims}`. These land in the experience payload (`source_outcomes`)
  **and** as `source:{domain}` component observations. Because observations persist only on
  **apply** (auto-apply stays off), the store only accumulates evidence a human has approved — the
  approval gate, unchanged.
- **Recommend.** `LearningService.source_advice()` aggregates all `source:{domain}` observations and
  ranks **prefer** (produced claims in ≥50% of ≥2 attempts) vs **deprioritize** (blocked/unreadable
  in ≥50% of ≥2 attempts), each with a reason and counts (e.g. *“Prefer arxiv.org — produced claims
  in 2/2 attempt(s)”*, *“Deprioritize ieeexplore.ieee.org — blocked/unreadable in 2/2 attempt(s);
  seek an open-access alternative”*). Purely non-mutating.
- **Surface.** Folded into `advice_for()` (new `operational` field + a “Source reliability” block in
  the advice text) so it flows into `ResearchService._recall_advice` → `experience_advice.json`, the
  planner’s advice context, and a new `source_advice` activity-feed line. Also exposed directly via
  `GET /v1/learning/sources` and `atlas learn sources`.
- **Not yet (deferred, intentional).** Atlas does not *reorder* acquisition automatically from this
  advice — that adaptive step remains behind the human-approval gate, matching the Stage 3B stance.
- **Tests.** `test_learning.py`: domain normalization, trace aggregation, payload capture,
  prefer/deprioritize ranking, `min_attempts` guard, **apply-gated** accumulation, and `advice_for`
  fold-in; `test_api.py::test_learning_sources_endpoint_is_advice_only`.

### 16.9 Document ingestion + grouping fidelity (2026-07-18, wave 4)

A third live run (85.2 KB read across 4 docs; ar5iv→15 & RdTools→4 claims; IEEE/Springer/review
papers → **0 claims**) localized the remaining bottleneck to **document ingestion, not reasoning**:
the HTML reader flattened publisher pages into a nav/boilerplate blob (or empty text) with no article
body, so peer-reviewed sources yielded nothing. This wave hardens ingestion and tightens a couple of
grouping/cap refinements the operator flagged (the "15 → 14" worry).

- **Main-content HTML extraction (biggest lever).** `atlas/ingestion/extractors.py` gains
  `html_to_main_text()`: try **trafilatura** (new dependency; best publisher coverage) → a
  deterministic **boilerplate-stripping heuristic** (`_heuristic_main_text`: drop
  `script/style/nav/header/footer/aside/form/…` and any element whose id/class/role matches
  chrome hints like `menu/cookie/subscribe/sidebar/share`, then select the container with the most
  *paragraph* text, preferring semantic `<article>`/`<main>`/`[role=main]`) → naive `html_to_text`
  fallback so simple pages still work. The `.html/.htm` extractor and the content-type HTML reader
  path now use it, so ar5iv-style full-text pages keep their body while nav/footers are dropped.
- **Paywall / landing-page classification.** `looks_paywalled()` detects subscribe/login/purchase
  gates; `Reader.read_path` flags HTML gates with `metadata["paywall_suspected"]`, a warning, and
  `failure_code="paywall"` (**text is kept** so an available abstract can still be mined). This gives
  the Pipeline Trace a precise reason ("paywall") instead of a vague "no claim patterns matched".
- **Per-doc claim cap raised + adaptive.** `ClaimExtractor` default `max_claims_per_doc` **15 → 30**,
  with `_doc_cap()` giving peer-reviewed sources 1.5× headroom (they carry the most findings). ar5iv
  was being truncated at exactly 15; this stops mid-paper cut-off.
- **Grouping keeps the *specific* claim.** `_rep()` now ranks by (evidence level → **carries a
  number** → length), so merging near-duplicate prose never discards the quantified version
  ("SVR beat Ridge by 0.4%" wins over a longer vague paraphrase).
- **Round logging clarity.** The per-round line now reads `N raw → M distinct claim(s)` so the
  deduplicated total is never mistaken for a per-document extraction count. A property test
  (`test_grouping_is_monotonic_adding_claims_never_reduces_count`) proves grouping only ever
  merges — the "15 → 14" was a raw-vs-distinct log mismatch, **not** lost evidence.
- **Deferred (documented next step).** DOI→open-access resolution (Unpaywall/PMC) and routing
  paywalled publishers to OA mirrors — pairs naturally with §16.8 source-reliability advice; skipped
  here because it needs network/credentials and can't be tested hermetically.
- **Tests.** `test_ingestion.py` (main-content keeps article/drops nav+footer+cookie, heuristic
  container selection, tiny-page fallback, paywall detection); `test_reader.py`
  (`test_read_path_html_flags_paywall_landing`); `test_grouping.py` (specific-representative +
  monotonic property); `test_extract.py` (raised default cap + peer-reviewed headroom). Full suite:
  **1009 passed.**

---

## 17. One-line summary

> Finish Stage 3 by building an evaluated **knowledge operating system** — shared access,
> append-only findings, lifecycle, provenance, quality dimensions, memory hierarchy, and
> governed job/component learning — so Stage 4/5 only teach new domains.

> **What comes after Stage 3:** the project reframes from "Stages" into a product roadmap
> built on **Intelligence Domains + Missions + Persistent Workers** with durable state,
> model-independence, and design-for-failure. See **`docs/ATLAS_OS_ROADMAP.md`** (discussion
> draft — no code yet).
