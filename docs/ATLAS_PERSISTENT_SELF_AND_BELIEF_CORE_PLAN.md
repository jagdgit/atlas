# Atlas Persistent Self — Identity · Goals · Belief Core

> **Status:** 🔒 **OPERATOR-LOCKED** 2026-08-11 night — ready for implementation sequencing  
> **OI umbrella:** `OI-SELF0`  
> **Children:** `OI-SELF-ID` · `OI-SELF-BELIEF` · `OI-SELF-EXP` · `OI-SELF-REASON` · `OI-SELF-REFLECT` · `OI-SELF-SEED`  
> **Parents (do not reopen):**  
> [`BELIEF_REVISION_AND_LLM_INTELLIGENCE_DISCUSSION.md`](BELIEF_REVISION_AND_LLM_INTELLIGENCE_DISCUSSION.md) (`OI-BRE0`) ·  
> [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md) (`OI-JDG0`) ·  
> Experience OS (`OI-MP1` / EX.1) · DI packets (`OI-DI0`) · Memory hierarchy (`OI-PA-MEM`)  
> **North star:** Models are replaceable CPUs; **Atlas remains** — identity, goals, beliefs, experiences.  
> **Wall sentence:** *Atlas should never learn the same lesson twice.*  
> **Center (locked):** **Identity → Goals → Beliefs** (beliefs are not the top of the stack).

**Related:** LLM-use inventory (2026-08-11) · [`OPEN_ITEMS.md`](OPEN_ITEMS.md)

**Amendment A (lock night):** Identity is the center; operator answers §12 frozen; `candidate` lifecycle; belief aging; “What changed your mind?” benchmark; Postgres `beliefs.*` schema; advice-only influence; Engineering first non-market domain; `atlas.reasoning`; stay on 4B until Phase 1; seed 20–30 operator beliefs.

**Amendment B (final check):** Belief **Consultation Rate** metric (worldview must be used, not decorative); ReasoningService is a **mandatory cognitive choke point** (no worker-direct semantic LLM); supreme invariant — every semantic belief/revision is **evidence-traceable and explainable**; expected progression Phase 1→4 = consistent → memory-bearing → self-correcting → feels like Atlas; do not couple beliefs to trading performance until ~100 trusted revisions.

---

## 0. Why this document exists

This is not “use LLMs more.”

The 2026-08-11 inventory diagnosed:

| Wrong framing | Correct framing |
|---------------|-----------------|
| Atlas lacks AI | Atlas lacks a **persistent self** that survives tasks, modules, and time |
| Add more workers / reports | Add **inheritance** (future decisions consult prior mind) |
| Bigger model will fix it | Without accumulation, GPT-N still forgets tomorrow |

**Knowledge is archived, not accumulated.**

That sentence is the bottleneck. WSO, BRE, Experience, mentors, and evening reports all exhibit it.

This plan attacks continuity — not another symptom.

---

## 1. Locked diagnosis

### 1.1 What Atlas is today

- Excellent **orchestration** (scheduler, jobs, Host Guard, missions, DB, RAG plumbing).
- Strong **deterministic nervous system** (bars, ledger, ranking, packets, honesty).
- LLM stack **wired correctly** (roles, single lane, provider swap) and **operationally sidelined**.
- Cognitive-named modules (WSO, BRE, MEM, META, DCA, JIS) are largely **scaffolding + skip paths**.

Atlas is closer to an **enterprise workflow platform with AI plugins** than to one mind with domain branches.

### 1.2 The missing center (locked architecture)

**Not** “Beliefs at the top.” Beliefs without goals become interesting philosophy.

```text
Identity
    ↓
Goals
    ↓
Beliefs
    ↓
Reasoning Service
    ↓
Living RAG
    ↓
Domain Programs (Market · Engineering · Personal · …)
    ↓
Actions
    ↓
Experiences
    ↓
Reflection
    ↓
Belief Revision
    ↺
```

Why identity first:

| Belief alone | Belief under identity + goals |
|--------------|-------------------------------|
| “Momentum works better in high volatility.” | Matters **because** Atlas aims to preserve capital, compound returns, avoid overtrading, outperform NIFTY. |
| Interesting claim | Actionable worldview |

Identity determines **which beliefs matter**. Goals determine **what experiences to seek**. Beliefs determine **how to predict**. Experiences revise beliefs. Reflection closes the loop.

### 1.3 One-sentence product definition

> Atlas is a durable **identity** that pursues **goals**, maintains a revisable **belief** worldview, learns via **experiences**, and uses LLMs only as replaceable reasoning engines.

### 1.4 Inheritance (the product of this work)

Workers must not start from scratch. Every meaningful decision path **consults** identity + goals + beliefs (+ Living RAG). Every closed loop **writes** experience → candidate or revision. That is inheritance.

---

## 2. What already exists (do not throw away)

Promote and unify. No parallel universe.

| Existing piece | Today | Role under Persistent Self |
|----------------|-------|----------------------------|
| **Knowledge OS** | Facts, chunks, embeddings | Store **Knowledge** |
| **Memory hierarchy** | Working / session / long-term | Store **Memory** — densify |
| **Experience OS** | Observation→…→Lesson | Store **Experience** — upgrade prediction/outcome/delta + belief links |
| **WSO** | Per-symbol shells | **Market projection / working memory** over Belief Core — keep |
| **BRE.2–5** | Budgeted revise / rationale / morning / global | **Market adapters** → Reasoning Service → Belief Core |
| **Decision Packets** | Frozen decide-time snapshot | Experience **prediction** seed; link Belief IDs |
| **Cognitive Budget** | Cap LLM passes | Reasoning Service respects it |
| **Curiosity / CWS / DCA** | Unknowns → work | Living RAG channel + goal-aligned research |
| **Mentors** | Heuristic lessons | Emit **`candidate` beliefs**, not only prose |
| **Assistant / RAG / ReAct** | Chat + tools | Identity-first Living RAG |
| **LLMService roles** | chat / planner / researcher / … | Only Reasoning Service uses them for cognition |
| **Policy / mentor soft-bias** | Advice before hard control | **Precedent for belief influence ladder** |

### 2.1 Honest gap

Today “belief” is scattered across packets, empty WSO thesis text, lesson strings, mentor tags, and dead report paragraphs.

**None of these is** a cross-domain, queryable, confidence-tracked, contradiction-aware, aged Belief that future decisions inherit under an Identity.

---

## 3. Permanent stores (locked)

### 3.1 Knowledge (facts)

Documents, papers, code, manuals, filings, transcripts, verified findings.  
**Not** generalizations.

### 3.2 Memory (events)

Conversations, tasks, observations, notable mission events. Chronological.  
**Not** strategies.

### 3.3 Identity & Goals (center — versioned)

| Artifact | Contents |
|----------|----------|
| **Identity** | Who Atlas is; non-negotiables; voice; permanence doctrine (“models swap, Atlas remains”) |
| **Goals** | Domain + cross goals (preserve capital, compound, honest learning, engineering determinism, …) |
| **Versioning** | Append-only revisions; operator-gated for identity; goals may evolve with reflection proposals |

Identity/goals are **not** chat system-prompt fluff only — they are durable, stored, citables.

### 3.4 Beliefs (worldview) — first-class Postgres subsystem

**Store home (locked):** Postgres schema **`beliefs`** from day one. **No JSONL bootstrap.**

Tables (minimum):

| Table | Role |
|-------|------|
| `beliefs.beliefs` | Core rows (statement, confidence, status, domain, level, themes, …) |
| `beliefs.revisions` | Append-only mind-change history |
| `beliefs.evidence_links` | Links to Knowledge / Experience / packets / URLs |
| `beliefs.contradictions` | Competing beliefs / counter-evidence |
| `beliefs.influence` | Declared influence intents (advice / soft / hard) — Phase 1 advice-only |

Reason: joins, evidence refs, revision history, retrieval, analytics, timestamps, confidence filters — Atlas already trusts Postgres.

#### Belief fields (locked minimum)

| Field | Purpose |
|-------|---------|
| `belief_id` | Stable ID |
| `domain` | `market` · `engineering` · `personal` · `cross` |
| `level` | `concrete` · `domain` · `abstract` |
| `themes[]` | e.g. `momentum`, `complexity`, `hidden_state` |
| `applies_to[]` | domains / symbols / modules |
| `statement` | One clear claim |
| `confidence` | Stored 0–1 |
| `effective_confidence` | After **aging** (computed or cached) |
| `status` | see lifecycle |
| `origin` | `operator` · `llm` · `mentor` · `experience` · `research` · `imported` |
| `last_evidence_at` | Drives aging |
| `last_consulted_at` / `last_revised_at` | Continuity metrics |
| `open_questions[]` | Falsifiers / what would change this |

#### Belief lifecycle states (locked)

| Status | Meaning |
|--------|---------|
| **`candidate`** | Proposed; weak; not yet worldview. From mentor / experience / research / operator note / repeated observation |
| **`active`** | Promoted; consulted in Living RAG as worldview |
| **`weakened`** | Still held; confidence / force reduced |
| **`falsified`** | Rejected by evidence |
| **`superseded`** | Replaced by a newer belief ID |
| **`dormant`** | Not deleted; out of active consult set |

**Promotion rule:** Reflection (or operator) promotes `candidate` → `active`. Weak ideas must not flood the worldview.

Example candidate:

> “Switches after macro events may require a cooldown.”  
> confidence 0.32 · evidence: 3 experiences · status: `candidate`

#### Belief aging (locked)

Not deletion — **decay**.

```text
stored_confidence = 0.81
last_evidence_at  = 400 days ago
effective_confidence = decay(stored_confidence, age, domain_half_life)
```

Markets age faster than abstract engineering heuristics (domain-specific half-lives in config). Aging forces revalidation and keeps “What changed your mind?” honest.

**Semantic ownership (carry BRE §1.7):**  
Deterministic code may score, schedule, age, store structure.  
**Only LLM or operator** may author / revise semantic `statement` text.

### 3.5 Experience (learning engine) — upgrade Experience OS

| Field | Purpose |
|-------|---------|
| Context | Situation |
| Prediction | Expected outcome + thesis |
| Action | What Atlas did |
| Outcome | What happened |
| Delta | Prediction vs outcome |
| Lesson candidate | Provisional rule |
| Affected beliefs[] | Belief IDs revised **or** candidates proposed |
| Counterfactuals | Optional (`OI-CF0`) |

**Upgrade rule:** Experience without belief link (and without honest `no_belief_link_reason`) = archive. With link = accumulation.

Wall sentence:

> If the same lesson is extracted twice with no belief change or candidate strengthen in between, the Experience Engine failed.

---

## 4. WSO fate (locked)

**Do not delete WSO.**

| Layer | Role |
|-------|------|
| **Belief Core** | Long-term worldview (momentum weighting, valuation discipline, capital preservation, sizing heuristics, …) |
| **WSO (e.g. TCS)** | Entity-scoped **runtime working memory**: current thesis, unknowns, local evidence, local confidence — a **Market projection** of Belief Core + local state |

Human analogy: durable principles vs “what I currently think about this one company.”

BRE adapters update both: local WSO fields **and** Belief Core revisions / candidates when generalizations emerge.

---

## 5. Influence strength (locked ladder)

**Phase A (implementation Phase 1–2):** **Advice-only.**  
Beliefs must **not** mutate ranking, allocations, gates, or execution.

| Phase | Influence |
|-------|-----------|
| **A — now** | Belief → recommendation → explanation (consult APIs, chat, evening sections) |
| **B — later** | Belief → soft weight (mentor-bias precedent) |
| **C — later** | Policy-approved hard influence |

Reason: until one full learning cycle proves belief quality, hard coupling would confound “belief good vs market luck vs hallucination.”

---

## 6. Living RAG (locked)

Not library mode (question → chunks → answer).

Every cognition / chat turn retrieves:

1. **Identity + Goals**  
2. **Beliefs** (active + relevant candidates; use `effective_confidence`)  
3. **Experiences** (prediction/outcome peers)  
4. **Knowledge** documents  
5. **Open questions / unknowns**  
6. **Active goals** (explicit in bundle even if also in identity store)

Responses cite `belief_id` / `experience_id` / `revision_id` where claims rest on worldview.

---

## 7. Reasoning Service — `atlas.reasoning` (locked)

**Package name:** `atlas.reasoning` (not “cortex”).

Expected layout:

```text
atlas/reasoning/
  service.py          # ReasoningService — sole cognitive LLM façade
  beliefs/            # store adapters, consult, revise, age, promote
  reflection/         # nightly / budgeted reflection
  retrieval/          # Living RAG bundle builder
  identity/           # identity + goals loaders
```

### 7.1 Responsibilities

- Synthesize evidence packs  
- Propose **candidates** / revise **active** beliefs  
- Record contradictions  
- Generate hypotheses  
- Critique plans against identity + goals  
- Cross-domain pattern detection (abstract beliefs)  
- Chat answers via Living RAG  
- Respect Cognitive Budget + single LLM lane  

### 7.2 Hard rule — mandatory cognitive choke point

**`ReasoningService` must not become another thin utility wrapper.**

It is the **only** path for semantic cognition (belief propose/revise/promote, hypothesis, mind-change narrative, identity-grounded chat synthesis).

| Allowed | Forbidden |
|---------|-----------|
| Workers call `ReasoningService` cognitive ops | Workers call `LLMService` / Ollama directly for semantic reasoning |
| Deterministic code, embeds, ranking math | Parallel “just this one chat()” escape hatches that rewrite worldview outside Belief Core |

If workers keep calling `LLMService` for semantic reasoning, the architecture **drifts back into fragmentation** — the failure mode this plan exists to end.

Enforce in review + tests: semantic belief writes without going through Reasoning Service / Belief store are defects.

BRE.2/3/4/5 become Market adapters into this service.

---

## 8. Models (locked for Phase 1)

### 8.1 Inventory

| Role | Model | Notes |
|------|-------|-------|
| `chat` / `planner` / `researcher` / `summarizer` | `qwen3:4b` | Stay here through Belief Engine land |
| `code` | `llama3` | Already separate |
| `embed` | `nomic-embed-text` | Vectors |
| `vision` | `gemma3` | Not pulled — out of scope |

### 8.2 Doctrine

- **Stay on 4B until Phase 1 (Belief Engine) lands.**  
- Separate **architecture quality** from **model quality**.  
- Later config-only: `researcher` → 8B/14B when RAM allows; chat stays small.  
- Single lane remains.  
- Model swap must not rewrite identity / beliefs / experiences.

---

## 9. Operator seed worldview (locked) · `OI-SELF-SEED`

**Yes — 20–30 beliefs only.** Not hundreds. Status: `active`, origin: `operator`, moderate confidence, explicit open_questions.

Seed themes (exact statements finalized at implementation; count ~20–30):

**Market**

- Capital preservation before growth  
- Prefer understandable businesses  
- Evidence before conviction  
- Avoid strategy changes from small samples  

**Engineering**

- Determinism is valuable  
- Measure before optimizing  
- Prefer explicit interfaces  
- Complexity compounds silently  

**Personal**

- Long-term projects require consistency  
- Sleep affects judgment  
- Learning compounds  
- Documentation preserves cognition  

**Cross-domain**

- Hidden state reduces predictability  
- Feedback loops improve systems  
- Small repeated improvements compound  
- Uncertainty should be represented explicitly  

This gives Atlas an immediate personality. Every seed is revisable.

---

## 10. Build order (locked for implementation)

> Effort guess: **30–60k lines of the right code** (seams + stores + Reasoning Service + wiring).  
> **Freeze:** strategy optimization, AtlasNet live NN, ranking vanity, hard belief→execution coupling, model bumps for “smarter revise.”  
> **Parallel allowed:** Judgment Month evidence densify (J1/J2) — fuel for the engine.

### Phase 0 — Plan lock · ✅ this document

- [x] Diagnosis accepted  
- [x] Identity-centered stack locked  
- [x] Seven operator questions answered (§12)  
- [x] `OI-SELF0` registered  
- [x] Candidate + aging + mind-change benchmark added  

**Exit:** ✅ Locked. Implementation may begin when operator schedules Phase 1.

### Phase 1 — Identity stub + Belief Engine · `OI-SELF-ID` (minimal) + `OI-SELF-BELIEF` + `OI-SELF-SEED` + `OI-SELF-REASON` (façade)

Ship first (highest leverage):

1. Versioned **Identity + Goals** store (even if thin) — center exists before beliefs sprawl  
2. Postgres `beliefs.*` schema + repository  
3. Lifecycle including **`candidate`**; **aging** helper; revision + evidence + contradiction + influence(advice) tables  
4. Seed 20–30 operator beliefs  
5. `atlas.reasoning.service` façade: consult / explain / revise (LLM) / promote candidate — **instrument every consult** (Belief Consultations metric)  
6. WSO remains; document projection contract (implement read-path consult from Belief Core)  
7. **Advice-only** influence — no ranking/gates mutation  
8. Enforce choke point: no new semantic LLM paths outside Reasoning Service  

**Acceptance:**

- “Why do you believe X?” → statement · stored + effective confidence · evidence · contradictions · last revision · falsifiers  
- “What changed your mind?” works once a revision exists (seed a controlled revise in tests)  
- WSO still loads; Belief Core queryable via API/CLI  

### Phase 2 — Experience Engine upgrade · `OI-SELF-EXP`

- Prediction / outcome / delta on Experience (contract or columns)  
- `affected_beliefs[]` or honest `no_belief_link_reason`  
- Packets + CF.1 + fills seed experiences  
- Mentors / research emit **candidates**  
- First closed loop: packet → outcome → experience → belief revision or candidate  

**First non-market domain (locked): Engineering** — faster feedback (reviews, refactors, bug patterns) and abstractions that transfer to market systems.

### Phase 3 — Reflection Engine · `OI-SELF-REFLECT`

Nightly budgeted reflection via Reasoning Service:

- Failed predictions? Repeats? New evidence? Promote/weaken/falsify? Unknowns that matter?  
- Wire BRE.2 / BRE.5 / MEM through Reasoning Service; end hardcoded `allow_llm=False` for budgeted passes once Belief Core is real  
- JIS metric counts **Belief Core revisions** (not only WSO status strings)  

**Exit:** ≥1 material revision/week when evidence exists — or honest zero.

### Phase 4 — Full Identity + Living RAG chat · `OI-SELF-ID` (complete)

- Chat path: Identity → Goals → Living RAG six-pack → model  
- Feels like Atlas, not raw Qwen  
- Benchmarks pass for **Market + Engineering**  
- Personal remains schema-ready; not the Phase 4 gate  

### Phase 5 — Soft influence (only after one learning cycle)

- Belief → soft weight (mentor-bias pattern)  
- Still no silent hard execution mutation without Policy  

### Phase 6 — Cross-domain abstraction densify

- Measure abstract belief reuse across domains  
- Do not start here  

---

## 11. Acceptance benchmarks (locked)

### 11.0 North-star metrics (honesty pair)

| Metric | Purpose |
|--------|---------|
| **Belief Revisions / week** (JIS-aligned) | Mind is changing for reasons |
| **Belief Consultations / day** (new) | Mind is **used**, not decorative |

Example evening / introspection line:

```text
Belief Consultations Today: 47
  Market: 32 · Engineering: 15 · Personal: 0
Belief Revisions (7d): 3 material
```

If consultations stay ~0 while beliefs exist, Belief Core failed — it is a semantic archive. Instrument `consult()` from Phase 1.

**Temptation to resist:** do not wire beliefs into ranking / capital until you have watched on the order of **~100 belief revisions**, deleted bad ones, and trust the worldview. Influence ladder stays advice-only until then.

### 11.0b Supreme invariant (protect above all else)

> Every semantic belief must be **traceable to evidence**, and every revision must be **explainable**.

Lose this → Belief Core becomes a vector store with nicer names.  
Keep this → models can be replaced forever.

### 11.1 Why do you believe X?

Required: belief · confidence (stored + effective) · evidence · contradictions · last revision · what would change it · status.

Domains: market; engineering (Phase 4 gate); personal when live.

### 11.2 What changed your mind? (harder — required)

Example shape:

```text
I believed valuation should dominate ranking.
That belief weakened on <date>.
Reason:
  - N decisions
  - competing signal outperformed in regime R
  - confidence 0.82 → 0.61
Revision: B-014 → revision r3
```

Intelligence becomes **visible** here.

### 11.3 Non-repetition

Same lesson twice → strengthen / cite existing belief or candidate — no orphan duplicate worldview row.

### 11.4 Model-swap smoke

Config-only researcher change; belief store intact; revise still appends `beliefs.revisions`.

### 11.5 Negative honesty

Empty evidence → refuse semantic revise (`skip_reason`); never invent confidence.

### 11.6 Influence quarantine

Automated test/assert: belief writes do not change ranking weights / gates / allocations in Phase 1–2.

---

## 12. Operator lock answers (frozen)

| # | Question | **Locked answer** |
|---|----------|-------------------|
| 1 | Store home | **Postgres `beliefs.*` from day one.** No JSONL bootstrap. |
| 2 | WSO fate | **Market projection / entity working memory** over Belief Core. Keep WSO. |
| 3 | Influence | **Advice-only** until one full learning cycle; then soft; then policy-hard. |
| 4 | First non-market | **Engineering** (not Personal). |
| 5 | Package | **`atlas.reasoning`**. |
| 6 | Model bump | **Stay on qwen3:4b until Phase 1 lands.** |
| 7 | Seed worldview | **Yes — 20–30 operator beliefs**, revisable. |

---

## 13. OPEN_ITEMS registration (locked)

| ID | Status | Pri | Item |
|----|--------|-----|------|
| `OI-SELF0` | 🟡 | P0 | Umbrella — Identity-centered Persistent Self |
| `OI-SELF-ID` | 🔴 | P0 | Identity + Goals store; Living RAG chat (full in Phase 4; stub in Phase 1) |
| `OI-SELF-BELIEF` | 🔴 | P0 | Postgres Belief Engine + lifecycle + aging + consult/revise |
| `OI-SELF-SEED` | 🔴 | P0 | 20–30 operator seed beliefs |
| `OI-SELF-REASON` | 🔴 | P0 | `atlas.reasoning` — sole cognitive LLM façade |
| `OI-SELF-EXP` | 🔴 | P0 | Experience prediction/outcome/delta + affected_beliefs / candidates |
| `OI-SELF-REFLECT` | 🔴 | P1 | Nightly Reflection Engine; promote candidates; BRE adapters |

Judgment Month (`OI-JDG0`) remains **parallel fuel**, not replaced.

---

## 14. What we will not do in this window

- Hard belief → ranking / gates / execution (until ladder Phase B/C)  
- Delete WSO  
- JSONL belief bootstrap  
- Second Experience database  
- Per-module private belief silos  
- “Turn on allow_llm everywhere” without Belief Core  
- Block on GPU / larger models  
- New strategy / AtlasNet live NN / indicator farms  
- Seed hundreds of beliefs  

---

## 15. Relationship to Judgment Month

| Track | Disposition |
|-------|-------------|
| J1 / J2 evidence densify | **Keep** — empty evidence starves reflection |
| J3 BRE | Retarget writes through Reasoning Service → Belief Core (+ WSO projection) |
| J4 curiosity | Living RAG unknowns channel |
| JIS | Count **Belief Core** material revisions / week **and** Belief Consultations / day (by domain) |
| AtlasNet / strategy sprawl | Frozen |

---

## 16. Discussion log

| Date | Note |
|------|------|
| 2026-08-11 eve | Diagnosis + first draft plan; multi-model inventory noted. |
| 2026-08-11 night | **OPERATOR LOCK.** Identity centered over beliefs; §12 answers frozen; candidate + aging; mind-change benchmark; Postgres `beliefs.*`; advice-only; Engineering first; `atlas.reasoning`; 4B until Phase 1; 20–30 seed beliefs. Implementation not started. |
| 2026-08-11 night | **Amendment B.** Final check accepted: Consultation Rate metric; ReasoningService choke point; evidence/explainability invariant; ~100 revisions before money influence; Phase 1–4 progression (consistent → memory → self-correcting → Atlas-feel). |
| 2026-08-11 night | **Phase 1 implementation landed.** Migration `0050_beliefs.sql`; `BeliefRepository` + InMemory; `atlas.reasoning` (aging, seed×21, ReasoningService); bootstrap seed; API `/v1/beliefs*` + `/v1/reasoning/*`; tests `test_self0_belief_core.py` (11 passed). Advice-only. BRE choke-point migration deferred to later SELF work. |
| 2026-08-11 night | **Phase 2 landed.** Experience learning-loop (prediction/delta/affected_beliefs); `experience_loop.close_loop`; engineering mentor→belief candidates; CF horizons→honest archive loops; API `POST /v1/experience/learning-loop`; tests `test_self0_experience_loop.py`. |
| 2026-08-11 night | **Phase 3 landed.** `atlas.reasoning.reflection` — promote candidates, age-weaken, Belief Core JIS + consultations; evening BRE.5/MEM `allow_llm=True` when LLM bound; mailer `bind_reasoning`; API `POST /v1/reasoning/reflect`; tests `test_self0_reflection.py`. |
| 2026-08-11 night | **Phase 4 landed.** Living RAG (`retrieval`) + identity-first chat (`identity_chat`); AssistantService `_do_answer`/`smalltalk` via ReasoningService; why/mind-change benchmarks without free-form LLM; tokenized belief search; API `POST /v1/reasoning/living-rag`; tests `test_self0_identity_chat.py`. Phase 5 soft influence still deferred. |

---

## 17. One-paragraph summary

Atlas already has the body of an OS. What it lacked was **inheritance**: a durable **identity** and **goals** that make **beliefs** matter, **experiences** that update those beliefs, and a **Reasoning Service** that uses models as CPUs over Living RAG. Beliefs live in Postgres with candidate→active promotion and aging; WSO stays as Market working memory; influence stays advice-only until quality is proven; Engineering is the first non-market proving ground; Qwen 4B must succeed before model bumps. When Atlas can answer both “Why do you believe X?” and “What changed your mind?” — the original sentence becomes true: *models can be replaced, Atlas remains forever.*
