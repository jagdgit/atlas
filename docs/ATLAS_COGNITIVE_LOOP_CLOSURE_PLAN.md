# Atlas — Cognitive Loop Closure

> **Status:** 🔒 **OPERATOR-LOCKED** 2026-09-21 (architecture) · **live stamp 2026-09-22 ~21:30 IST**  
> **Codename:** `OI-CLC0`  
> **Live (2026-09-23 ~20:55 IST):** **CLC.R1-SYNTHETIC 🟢 LOCKED** (mechanical + polarity + L2 −0.25 + polarity guard). J1 🟡 running · F&O-LAB paper 🟢 isolated · **R1-LIVE 🟡** · L5 ❌
> **Stop manufacturing R1 fixtures.** Do not force a trade. Do not enable live F&O. Leave system running: J1 + wait for genuine production packet. Synthetic green ≠ “Atlas has learned.”
> **Evidence:** Full intelligence audit 2026-09-20 (`atlas serve` PID 1973; fitness ledger; FEL E001/E002; F-002118 canary)  
> **Parents (do not fork):**  
> [`ATLAS_NOW_CLOSED_LOOP_ROADMAP.md`](ATLAS_NOW_CLOSED_LOOP_ROADMAP.md) ·  
> [`ATLAS_FEATURE_EXPERIMENT_LABORATORY_PLAN.md`](ATLAS_FEATURE_EXPERIMENT_LABORATORY_PLAN.md) ·  
> [`ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md`](ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md) ·  
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) ·  
> [`ATLAS_COGNITIVE_UNIFICATION_PLAN.md`](ATLAS_COGNITIVE_UNIFICATION_PLAN.md) ·  
> [`ATLAS_LABS_INTEGRATION_AND_LEARNING_FEEDBACK_DISCUSSION.md`](ATLAS_LABS_INTEGRATION_AND_LEARNING_FEEDBACK_DISCUSSION.md)  
> **Connect, do not rebuild:** `decision_consult` · `belief_context` · `ranking.experience` (8% weight) · `decide_rationale` drain · Cognitive Core · findings RAG · FEL hypothesis store · Experience OS · PLC.A / concentration / session gates  
> **Does not reopen:** LLM → BUY/SELL · SMA/RSI V1 as live **control** · FEL `live_control` · adding capital · PyTorch/RL/LangChain/MCP · loosening PLC.A · more FEL experiments before the Day-2 gate · multi-model theater · MATLAB/PSpice/LabVIEW readers as the next step

---

## 0. Operator thesis

The 2026-09-20 audit’s governing sentence:

> **The learning ledger is working; the learning loop is not.**

Atlas is a deterministic market laboratory OS with a thin, mostly idle agent framework and LLM sidecars. Memory, retrieval, and (sometimes) Qwen comprehension work. **Behaviour does not change because a lesson was retrieved.**

That is not “Atlas is empty.” It is “the brain is not on the control bus.”

```text
                    ATLAS TODAY

       ┌──────────────────────────────────────┐
       │       DETERMINISTIC LAB OS           │
       │  Data → calculations → trades        │
       │       → experiments → storage        │
       └──────────────────┬───────────────────┘
                          │
                    ┌─────▼─────┐
                    │ LLM SIDE  │  mostly advice
                    │   CAR     │  146 rationales pending
                    └───────────┘

     LEARN ──X──► FUTURE DECISION     experience_refs = 0
```

**North star for this cycle**

> A retrieved lesson must appear on the next relevant decision packet, be reasoned over (LLM or explicit UNREVIEWED), be allowed a **bounded, cited** effect on ranking/caution, survive deterministic safety gates, and be persisted as `experience_refs`. Until that Day-2 test passes, we do not add experiments, books, models, or workers.

Not the milestone: “Atlas traded more.” Not: “Qwen bought something.”

**What CLC.5 proves, and what it does not**

CLC.5 proves the **common learning junction**: retrieve → cite → bounded influence → persist. It does **not** prove that Engineering, Personal, Research, or Books are now learners. Those labs plug into the same junction later, each with its own outcome contract (see §17 Post-CLC applicability). Declaring “CLC passed, therefore Atlas is fully learning across all domains” is forbidden.

---

## 1. What the audit already proved (do not re-litigate)

| Claim | Status | Do not “fix” by rebuilding |
|-------|--------|----------------------------|
| Data plane (Zerodha LTP, ~202 daily bars, some XBRL) | LIVE | Do not add feeds for volume |
| Paper SMA/RSI V1 | LIVE (script) | Do not replace as control |
| FEL can run walk-forward | LIVE (E001 worse, E002 no_significant) | Do not start E003 |
| Findings RAG retrieve after restart | LIVE (F-002118) | Retrieval is not the bottleneck |
| Belief consult stamps packets | LIVE, `influence=advice_only` | Stamp exists; apply does not |
| Ranking has `experience` weight 0.08 | LIVE, fed by **keyword** advice | Slot exists; structured lessons do not |
| BRE.3 decide-rationale drain | WIRED, **0/146 completed** | Do not add a second rationale system |
| Planner / jobs | Architecture only (last job 2026-07-24) | Revive later with **one** job |
| One 4B model for all roles | LIVE fact | Be honest; don’t pretend specialization |
| Tesseract missing; 1 PDF | Book path NO | After the loop |
| `seed.cross.hidden_state` | Operator seed; consult `domain=market` drops it | Cross-domain after market loop |
| BRE.5 `_llm_global_narrative` | Broken (`text` undefined) | Hygiene, not Phase 1 |

**One genuine experimental lesson exists and is unused:** volume acceleration did not beat momentum+RS after 15 bps costs (E001, hypothesis **rejected**, `decision_eligible: false`).

---

## 2. Locked architecture (influence without LLM authority)

### 2.1 Desired decide path

```text
Evidence
   ↓
deterministic analysis (SMA/RSI, PLC.A, E[R], ranking)
   ↓
candidate
   ↓
     ┌──────────────┴──────────────┐
     ↓                             ↓
historical lessons            LLM rationale
(structured retrieve)         (or UNREVIEWED)
     └──────────────┬──────────────┘
                    ↓
           decision packet
           (citations required)
                    ↓
         deterministic gates
         (PLC.A, session, size,
          concentration, lab isolation)
                    ↓
              final action
```

Qwen **never** emits BUY/SELL/qty. Qwen emits: cited interpretation, unknowns, falsifiers, confidence, `review_status`.

### 2.2 Four influence layers (strict order)

| Layer | Name | May change action? | Required on Day-2 |
|-------|------|--------------------|-------------------|
| **L0** | Hard gates | Yes — can **block** | Already live (keep) |
| **L1** | Cite | No — packet must name the lesson | **YES — CLC.1** |
| **L2** | Bounded score / caution | Yes — only via existing score compare; cap ±0.25 on option score / ±0.2 on ranking experience bias | **YES — CLC.2** |
| **L3** | LLM rationale | No direct; may inform L2 only if `REVIEWED` + cited | **YES for material buy — CLC.R** |

L2 without L1 is forbidden (silent bias). L3 without L1 is forbidden (un-grounded prose). L0 always wins.

### 2.3 What “decision packet changed” means

A packet has **changed because of learning** iff **all** of:

1. `experience_refs` and/or `lesson_refs` nonempty  
2. At least one ref is the expected lesson (F-002118 and/or `H-buy_name-vol-accel`)  
3. `belief_context.influence` is `cited_bounded` (not `advice_only` when a matching lesson exists)  
4. Either `feature_contributions.experience` ≠ 0 **or** buy option score moved by the bounded delta **or** a gate recorded `lesson_caution`  
5. If LLM lane was free: rationale `llm=true` and `status=completed`; else honest `UNREVIEWED` — never silent skip forever

Action flip (buy→hold) is **allowed** only as a consequence of L0 or L2, never as an LLM token.

### 2.4 Epistemic ladder (preserve; stop collapsing)

| Layer | Who writes it | May affect L2? |
|-------|---------------|----------------|
| `AUTHOR_CLAIM` | Book/doc extract | **Never** |
| `ATLAS_HYPOTHESIS` | Planner / scientist / FEL register | **Never** (research only) |
| `EXPERIMENT_RESULT` | FEL runner | **Never** until mapped |
| `VALIDATED_MARKET_LESSON` | Promotion from result + sample gate | **Yes**, if retrieve matches |
| `ACTIVE_BELIEF` | Belief Core promote (operator or rule) | **Yes**, advice+bounded |

E001 today is stuck at `EXPERIMENT_RESULT` / rejected hypothesis. CLC.3 maps it to a **negative** `VALIDATED_MARKET_LESSON` without making it `live_control` and without mutating SMA/RSI V1.

A book that claims “volume acceleration predicts returns” must remain `AUTHOR_CLAIM` until a **new** hypothesis is registered. E001 already answered the related hypothesis; the book does not override the experiment.

### 2.5 One cognitive core, many labs

Atlas is **one** cognitive loop with multiple domains, not four separate AIs. Labs are experimentation environments feeding a common experience / learning / intelligence junction.

```text
                  ATLAS COGNITIVE CORE

       ┌────────── Knowledge ──────────┐
       │ Sources → Claims → Findings → │
       │ Beliefs                       │
       └──────────────┬────────────────┘
                      ↓
                 RETRIEVAL
                      ↓
                  REASONING
                      ↓
                   DECISION
                      ↓
                    ACTION
                      ↓
                   OUTCOME
                      ↓
                 EXPERIENCE
                      ↓
                  EXPERIMENT
                      ↓
                  VALIDATION
                      ↓
                    LESSON ──────────→ future decision
```

| Lab | World | Outcome that can validate a lesson |
|-----|-------|------------------------------------|
| Market | Market state → trade | P&L / paper round-trip |
| Engineering | Problem → implementation / simulation | Test / review result |
| Personal | Goal → action | Result vs plan |
| Research | Question → investigation | Evidence / falsification |
| Books / sources | Source → claims | Hypothesis test, never L2 from the claim |
| Cross-domain | Abstract pattern | Cited retrieve in another domain |

### 2.6 Lock amendments (explicit)

Previous freezes said SELF0 Phase 5 / size-side stay frozen, and FEL forbids `live_control`.

| Prior lock | CLC0 amendment |
|------------|----------------|
| SELF0 Phase 5 “no size/side” | **Narrow unfreeze:** cited L2 may change **ranking score and buy-option caution** within caps. Still no LLM qty. Still no silent strategy rewrite. |
| FEL D6 SMA/RSI stays control | **Holds.** Lessons caution/rank; they do not replace V1. |
| FEL D7 LLM never BUY/SELL | **Holds.** |
| `promotion: never` / `live_control` | **Holds** for strategy plugins. Negative lessons may still **inform L1/L2**. |
| AGENT-1 freeze | **Holds** until Phase 3 one-job. |
| No E003 until… | **Until Day-2 gate green.** |

---

## 3. What we will not do in this cycle

- More indicators, dashboards, seed beliefs, consultation counters, workers, or data sources for volume  
- E003 / E004 / new ModelPlugins  
- Letting Qwen place or size orders  
- Installing a second chat model “for specialization”  
- MATLAB/Simulink/LabVIEW/PSpice readers  
- 500-page book ingest as the next milestone  
- Treating 30,971 decisions / 14,719 consultations / 36.7M ticks as intelligence  
- Fixing BRE.5 global mind **before** L1/L2 (it does not close the loop)  
- Auto-applying all 91 proposed learning events (`auto_apply` stays false)  
- Pytest writing into the live DB (separate hygiene; do not block CLC)

---

## 4. Phases (dependency order)

```text
PHASE 1  CLOSE THE LEARNING LOOP          ← NOW
   CLC.1 Cite lessons on the packet
   CLC.2 Bounded L2 influence
   CLC.3 Promote E001 to negative lesson
   CLC.4 Persist experience_refs
   CLC.5 Hermetic Day-2 test (THE GATE)
   CLC.6 Live stamp on one real decide
        ↓
PHASE 2  LLM ON REAL REASONING
   CLC.R0 Why 146 pending never drain
   CLC.R1 Drain one material buy with lessons in prompt
   CLC.R2 Honest model labels (one reasoner + embed)
        ↓
PHASE 3  ONE REAL AGENT JOB
   CLC.J1 Planner-run objective, not a new worker
        ↓
PHASE 4  EXTERNAL KNOWLEDGE ACQUISITION
   CLC.B1 Tesseract + page policy
   CLC.B2 AUTHOR_CLAIM ≠ hypothesis (books are one source)
        ↓
PHASE 5  CROSS-DOMAIN TRANSFER
   CLC.X1 consult domain ∪ cross
   CLC.X2 One abstract lesson used in market retrieve
        ↓
PHASE 6  OTHER LABS AS LEARNERS
   Same junction; domain-specific outcome contracts
   Not new brains / DBs / LLMs
```

Each phase has a **single gate**. Do not start the next phase because the previous phase has “some code.”

---

## 5. Phase 1 — Close the learning loop (`CLC.1`–`CLC.6`)

### 5.1 Diagnosis of the missing apply

The retrieve path **already runs** on paper decide:

- `PaperTradingWorker._belief_context_for_packet` → `consult_unique_decision`  
- Consults Belief Core with `domain="market"` (drops `cross`)  
- Recalls Experience OS by keyword query  
- Stamps `belief_context` with `influence: "advice_only"`  
- `feature_contributions_v1` **ignores** that context  
- `decision.experience_refs` stay empty  
- Ranking `_experience_bias` is **keyword** (`loss`/`caution` in advice text), not FEL/findings  

FEL sealed the useful result out: `volume_acceleration_20d@1.json` has `decision_eligible: false`.

**We do not add a new cognition service.** We stop throwing the retrieved objects away.

### 5.2 CLC.1 — Cite (packet must listen)

**Change**

1. Extend consult retrieve to a **lesson matcher**, not only ILIKE beliefs:
   - findings tier query (same hybrid retrieve as Step 11 canary)
   - FEL findings / rejected hypotheses for this `decision_type` / feature / regime
   - Experience OS recall (keep)
   - Belief Core: `domain in {market, cross}` when query tokens hit themes (do not dump all seeds)
2. Write onto the packet:
   - `lesson_refs[]`: `{id, kind, statement, match, layer}`  
     `kind` ∈ `finding | fel_result | hypothesis | experience | belief`  
     `layer` ∈ epistemic ladder  
   - `experience_refs[]`: ids only (existing column; **stop leaving it empty**)
3. When `lesson_refs` nonempty, `belief_context.influence = "cited_bounded"` and the note must **not** say “no size/side change” if L2 will run.
4. `feature_contributions_v1` must take an `experience` input from matched lessons (signed, clamped). Today `experience` is a misuse of the risk axis.

**Files (expected)**

- `atlas/reasoning/decision_consult.py` — retrieve + slice  
- `atlas/reasoning/service.py` — consult filter `domain ∪ cross`  
- `atlas/investment/decision_packets.py` — `feature_contributions` + freeze `lesson_refs`  
- `atlas/workers/paper_trading.py` — copy refs onto DecisionEngine payload  
- `atlas/decision/engine.py` / `decision/contracts.py` — persist `experience_refs`  
- `atlas/knowledge/service.py` — reuse findings retrieve (no second RAG)

**Do not** call `RagAgent.generate` on the fill path. Retrieve only.

### 5.3 CLC.2 — Bounded influence (listen, don’t hand the wheel)

**Rules**

| Match | L2 effect | Cap |
|-------|-----------|-----|
| Negative validated lesson matching setup **and** regime | Subtract from buy option score (reuse `_apply_mentor_bias` pattern, structured not keywords) | −0.25 |
| Negative lesson matching feature used in ranking (`volume_acceleration`) | `experience_bias_by_symbol` negative | −0.20 |
| Positive validated lesson (none exist today) | Small support | +0.10 |
| `AUTHOR_CLAIM` / open hypothesis / invalid FEL (`n=1`) | Cite only (L1), L2 = 0 | — |
| Operator seed without match | Cite if consulted; L2 = 0 unless `ACTIVE_BELIEF` and theme matches | — |

Safety: PLC.A fail, session closed, concentration, FNO isolation, cash completeness — **unchanged**. A lesson cannot authorize a buy that gates forbid.

Replace `investment_universe._experience_bias` keyword scan with the same matcher, so swing ranking and paper packets share one function.

**Files**

- `atlas/investment/lesson_influence.py` **(new, small)** — match + clamp + explanation lines  
- `atlas/trading/strategy.py` — structured caution instead of/in addition to mentor keywords  
- `atlas/workers/investment_universe.py` — stop `"loss" in text`

### 5.4 CLC.3 — E001 becomes a lesson Atlas can retrieve

Map existing artifacts; **do not rerun** the 79-fold walk-forward.

| From | To |
|------|----|
| `H-buy_name-vol-accel` status=rejected | `VALIDATED_MARKET_LESSON` (negative) |
| Feature `volume_acceleration_20d` `decision_eligible: false` | Keep **false for live_control**; set `lesson_eligible: true` for L1/L2 caution when a candidate would use vol-accel or when query is buy_name+volume |
| Statement | “Volume acceleration did not add economic information beyond momentum and relative strength for buy_name after 15 bps costs (E001, 79 folds, 2018–). Do not treat vol-accel as a reason to buy.” |

Publish as a finding with stable canonical id (not a canary token). RAG must retrieve it for query: *“Does volume acceleration help buy_name?”*

Paper round-trip FEL (`n=1`, invalid) stays **cite-only / not L2**.

### 5.5 CLC.4 — Persistence honesty

- `decision.decisions.experience_refs` must be the lesson ids when L1 fired  
- Packet JSON `lesson_refs` durable  
- Learning audit: a row with refs + later outcome is **not** L5 by itself; it is **loop_closed_cite**. L5 still requires prediction→outcome→attribution→lesson→**subsequent** validation. CLC.4 is necessary for L5, not a fake L5.

### 5.6 CLC.5 — THE GATE (hermetic Day-2)

Extend Step 11; do **not** replace the RAG canary.

**Fixture**

- Finding F-002118 (or test double): Setup X poor in regime Y  
- Lesson from E001 JSON (load file, no live Ollama required for L1/L2)  
- Candidate packet: `strategy_tag` matching X, `regime=Y`, optional vol-accel feature flag  

**Must pass**

1. Retrieve F-002118 into `lesson_refs`  
2. Retrieve E001 lesson when the candidate is buy_name/vol-accel  
3. `experience_refs` nonempty on the recorded decision  
4. Buy score or ranking experience component **moves** vs identical packet without lessons  
5. PLC.A still blocks if pe/fcf missing  
6. LLM generate **not required** for this hermetic test (fake retrieve is enough for Phase 1)

**Tests (expected)**

- `tests/test_clc0_day2_packet.py` — hermetic  
- Keep `tests/test_lab_loop0_step11_canary.py` as retrieval-only  

**Gate:** red tests → Phase 1 not done. Do not “ship cite” without score movement.

### 5.7 CLC.6 — Live stamp (one real decide)

After hermetic green, one live paper decide (next session or forced replay) must show:

- `lesson_refs` including E001 **or** an honest `no_match`  
- `experience_refs` length > 0 **or** documented `no_match`  
- Fitness/ledger not required yet  

If live packets still have empty refs **and no `no_match`**, CLC.1 did not actually sit on the worker path.

**Hermetic 2026-09-22:** `PaperTradingWorker` forced replay writes packets with `no_match` when SMA/RSI does not match a lesson; worker consult with `volume_acceleration_20d` cites E001.

**Live stamp 2026-09-22 (PID 1999, bounce 10:44 IST):** swing `2026-09-22.jsonl` n=132. **131 honest `no_match`** (SMA/RSI does not match E001 — correct). **0 `experience_refs`, 0 E001 cites.** One miss: `HBLPOWER.NS` `hold` / `switch_blocked_plc_a` has empty refs and `no_match=None` (PLC.A hold path skipped the stamp). Gate = one real decide with refs or honest `no_match` → **GREEN**. Densify leftover = stamp every path including PLC.A holds. Next is **CLC.R\***, not E003.

---

## 6. Phase 2 — LLM on real reasoning (`CLC.R*`)

Start only after CLC.5 green.

### 6.1 CLC.R0 — Why drain never completes

`decision_evolution` already calls `drain_pending_rationales` (max 2 passes). **146/146 remain `pending`, `llm=false`.** Before writing more drain code, log one tick:

- Is `self._llm` / `self._reasoning` bound on that worker?  
- `lane_busy` always?  
- Evening `reports.py` last-chance drain skipped?  
- Pending files older than the current drain selector?

**Likely fix (do not pre-commit):** bind LLM on the evolution worker; drain **new material buys first**; expire the 146-backlog as `skipped_stale` with honesty — do not try to catch up 146 CPU chats.

**Hermetic 2026-09-22 (CLC.R0):** Root cause confirmed. Material buys score `llm_budget=3`; `pick_budgeted` treated that as pass cost against `max_passes=2` → **zero chosen**. Non-chosen rows were permanently `skipped_no_budget` (480 files). Host Guard revisit budget 0 returned before drain. Fix: each sidecar costs **one** pass; unchosen stay `pending`; pre-today backlog `skipped_stale`; drain runs on thinned ticks. LLM was already bound on `DecisionEvolutionWorker`. Live proof still needs a bounce of PID 1999.

### 6.2 CLC.R1 — One completed rationale

On a **material buy** (not session_closed noise):

- Prompt includes `lesson_refs` + packet_summary + unknowns  
- Output JSON: rationale, falsifiers, cited ids, confidence  
- Uncited claims dropped (existing BRE.3 filter)  
- `status=completed`, `llm=true`, `review_status=REVIEWED` **or** `UNREVIEWED` with reason  
- **Never blocks the fill** (keep async). Fill may happen with `llm_pending`; drain must finish the sidecar the same evening.

**Live proof:** one file under `investment/decide_rationale/*/by_id/` with `llm: true`. Fitness purpose `bre3_decide_rationale` count ≥ 1.

**Hermetic 2026-09-22 (CLC.R1):** `packet_summary` carries `lesson_refs` / `experience_refs` / `no_match`. Prompt requires citing lesson ids; honest `no_match` must not invent a lesson. Fill path still never calls LLM.

**Live 2026-09-23 (one NSE session after bounce — CLC.R1 still 🟡):** Bounce 07:42 IST PID 1940. `skipped_pre_clc` expired yesterday's 102. **New stamped packets existed** (`no_match=true` on all 150 swing packets). Material fills happened (swing COALINDIA 5/5 wash, intraday IDEA/PATANJALI). Drain ran: **10 COALINDIA `llm:true`**, all `empty_rationale_and_falsifiers` because Qwen **echoed the compact JSON prompt** (`raw_llm_text` starts with `"task": "bre3_decide_rationale"`). REVIEWED = 0. Remaining ~129 same-day IDEA/COALINDIA sidecars must not be drained (`skipped_r1_quota` in code).

F&O idle is **isolation**, not a hang: 0 fills, `fno_no_cash_alts`×97, `mark_only`×44, contract still `NIFTY26SEPFUT` / phase1. Do not let F&O buy cash names to look busy.

Prompt fix in repo: plain-text user turn (not JSON-in/JSON-out), reject `failed_prompt_echo`, do not list worldview IDs as lessons when `no_match=true`. Bounce to load; do not retry the 10 echoes or the wash backlog. Next REVIEWED still requires the new prompt on **one** new stamped packet.

The one-session wait bound is **consumed**. HOLD fallback is not required — fills existed. R1 failed at **LLM output contract** (prompt echo), not at missing sample and not at retrieve/cite/apply.

**Operator lock 2026-09-23 ~20:55 IST — R1-SYNTHETIC milestone closed; stop fixture churn.**

```text
E001 → retrieve → cite → Qwen "caution" → polarity validation
    → L2 = −0.25 → buy option 0.72 → 0.47 → L0 gates → final decision
Qwen never owns BUY/SELL.
```

**Declared:** Atlas can retrieve a lesson, reason about its polarity, reject an unsafe semantic inversion, apply the lesson through the deterministic bounded influence layer, and persist the reasoning result.

**Not declared:** Atlas has learned / L5 / R1-LIVE.

| Gate | Status | Proves |
|------|--------|--------|
| **R1-SYNTHETIC** (incl. polarity + L2) | 🟢 **LOCKED** | Structured path + grounded caution + bounded score effect |
| **CLC.J1** | 🟡 running | Multi-step E001 investigation (hypothesis or no-further-test) |
| **F&O-LAB** | 🟢 paper-only | Isolated cognitive loop; live execution OFF |
| **R1-LIVE** | 🟡 waiting | Genuine production packet → same contract |
| **L5** | ❌ | Not claimed |

**Do not:** add more R1 synthetic fixtures unless a concrete failure appears; force a trade for R1-LIVE; enable live F&O; mutate SMA/RSI from J1.

**Do:** leave serve running; let J1 finish; wait for the next real stamped packet.

**CLC.R1 live gate (unchanged, still open):**

```text
NEW material BUY
        ↓
lesson retrieval already on the packet
        ↓
lesson_refs in prompt
        ↓
Qwen JSON (rationale / falsifiers / cited ids / confidence)
        ↓
status=done · llm=true · review_status=REVIEWED
        ↓
fitness bre3_decide_rationale ≥ 1
```

Letter-of-gate `llm: true` happened. Usable REVIEWED rationale did **not**. CLC.R1 stays yellow until the new-buy path above.

**R1 green still is not “Atlas has proven learning.”** R1 proves Qwen can consume a lesson-aware (or honest `no_match`) packet and emit a grounded rationale. CLC.1–6 prove a lesson can affect a later packet (`loop_closed_cite`). Genuine L5 remains the longer chain: prediction → outcome → attribution → lesson → subsequent validation/reuse. Do not collapse those.

**Do not wait forever if no trade happens.** A missing fill is a sample problem, not a reason to loosen PLC.A, invent a BUY, or drain pre-stamp IDEA files.

Wait bound (locked 2026-09-22):

1. **One NSE session after the bounce** (skip a holiday; that session does not count). Prefer a **new material BUY**; a **new material SELL** with `lesson_refs` or honest `no_match` also counts.  
2. **If that session has no such fill:** same evening, one operator-supervised sidecar from a **same-day** HOLD/reject packet that already has `lesson_refs` or honest `no_match`. No order. No PLC.A change. Not a replay of IDEA.  
3. **If Atlas produced no stamped packet that day:** record `r1_blocked=no_stamped_packet` and stop waiting. That is an observation about the decide path, not a license to keep hoping. J1 stays paused until a REVIEWED rationale exists.

Never: force SMA/RSI, raise capital, replay the ~102 backlog, or ask Qwen to BUY so the counter moves.

| CLC component | Status |
|---------------|--------|
| CLC.1 — Cite lesson | 🟢 |
| CLC.2 — bounded influence | 🟢 / proven hermetically |
| CLC.3 — E001 negative lesson | 🟢 |
| CLC.4 — persist refs | 🟢 |
| CLC.5 — Day-2 hermetic test | 🟢 |
| CLC.6 — live stamp | 🟢 |
| CLC.R0 — understand drain failure | 🟢 |
| CLC.R1 — one usable rationale | 🟡 overall · **R1-SYNTHETIC 🟢 LOCKED** (mech+polarity+L2) · R1-LIVE open |
| CLC.R2 — honest one-model labels | 🟡 / in progress |
| CLC.J1 — real planner job | 🟡 running (`e498ebb2…`) |
| CLC.B — books/OCR | ⏸️ |
| CLC.X — cross-domain | ⏸️ |
| Other labs as learners | ⏸️ |
| CLC-CF — counterfactual / opportunity-cost observation | ⏸️ after CLC.J1 (`OI-CF-SNAP0`) |

### 6.3 CLC.R2 — Honest models

Config already maps every reasoning role to `qwen3:4b`. **Option B (locked for this cycle):**

- Docs, UI, `/v1/capabilities`, chat identity: “one local reasoner (`qwen3:4b`) + embed (`nomic-embed-text`)”  
- `vision=gemma3` stays “not installed”  
- `llama3:latest` unused — do not swap in  
- Do not pull a second 4B “planner” until Phase 3 shows planner calls > 0 on the **same** model

Role names remain (planner/scientist) as **lanes**, not different weights.

**Hermetic 2026-09-22 (CLC.R2):** `LLMService.honest_roster()` + `health_check().data["honest_roster"]`. Identity chat states one reasoner + embed. `config/defaults.yaml` comments match. `vision=gemma3` stays not installed.

---

## 7. Phase 3 — One real agent job (`CLC.J1`)

Start only after one `bre3_decide_rationale` fitness row (R1-SYNTHETIC REVIEWED is enough to *start*; R1-LIVE remains a separate proof).

**Assignment (example — operator may substitute one sentence):**

> Investigate why E001 failed and whether any regime remains where volume acceleration could still be useful. Do not mutate SMA/RSI. Conclude with a lesson or an explicit “no further test.”

**Must use JobService + planner decompose** (LLM or deterministic fallback, recorded). Must **not** be a new `PersistentWorker` type.

Expected steps Atlas chooses (not hard-coded in a worker): retrieve E001 JSON → inspect fold Δ → optional regime slice (E002 already exists; **do not rerun unless the job proposes it and sample exists**) → write conclusion as `ATLAS_HYPOTHESIS` or strengthen the negative lesson.

**Gate:** `job.jobs` row with `created_at` after this plan’s lock; planner-role **or** recorded deterministic fallback; artifacts in hypotheses/lessons.

AGENT-1 stays frozen. This is one supervised job, not a persistent operator agent.

---

## 8. Phase 4 — External knowledge acquisition (`CLC.B*`)

The goal is **not** “a book reader.” The goal is **knowledge acquisition from external sources** (books, PDFs, papers, YouTube, web, owner documents, repos, filings) entering the epistemic ladder.

Start only after Phase 1 gate. Phase 2/3 may proceed in parallel **after** CLC.5.

A trading book that claims “volume acceleration improves momentum” must become `AUTHOR_CLAIM`, retrieve E001 as contradiction context, and **not** become L2. Atlas’s conclusion is allowed to be: the author claimed X; Atlas’s own experiment did not support X under tested conditions.

1. Install Tesseract; keep `pdftoppm`. Operator page cap (50 default; explicit raise per ingest).  
2. Extract → sections (better than one blob) → `AUTHOR_CLAIM` findings with provenance.  
3. Claims **never** set L2. Promotion to hypothesis is explicit (job or operator).  
4. A claim that duplicates E001’s topic should retrieve E001 as contradiction context, not reopen SMA/RSI.

**Gate:** 20-page scanned PDF → ≥1 `AUTHOR_CLAIM` with page provenance; 0 SMA/RSI mutations; 0 L2 from claims.

A 500-page book is architecturally the same pipeline, not a separate product. Do not start it until this 20-page gate is green.

---

## 9. Phase 5 — Cross-domain (`CLC.X*`)

1. `ReasoningService.consult`: if `domain` set, still include `cross` rows whose **themes** match query tokens (`hidden_state`, `complexity`, …).  
2. Do not attach all 7 seed abstracts to every CIPLA tick.  
3. L2 from `cross` only if `ACTIVE_BELIEF` and matcher confidence ≥ threshold; else L1 cite.  
4. **Do not claim Atlas “learned” `hidden_state`.** It is still an operator seed until engineering evidence promotes a real child.

**Gate:** `consult(domain="market", query="hidden state predictability")` returns `seed.cross.hidden_state`. A market packet in a synthetic “opaque/high hidden-state” fixture cites it.

Engineering/Personal “become learners” is **out of scope** until this retrieve works **and** Phase 6 outcome contracts exist. Parsing MATLAB/PSpice/LabVIEW remains stubs — those are acquisition capabilities, not learning.

---

## 10. Phase 6 — Other labs as learners

After CLC.X retrieve works, **adapt the same closed-loop mechanism**. Not new brains. Not new databases. Not new LLMs. Different **outcome contracts**.

| Lab | Required contract before calling it a learner |
|-----|-----------------------------------------------|
| Research | Previous investigation changes the next (CLC.J1 is the first demonstration) |
| Engineering | Implementation / test / simulation result → experience → later design change |
| Personal | Goals, actions, outcomes, recurring-pattern validation (today: 0 system goals) |
| Books / sources | Claim → compare with existing knowledge → testable question (CLC.B) |

Do **not** start MATLAB / PSpice / LabVIEW readers as Phase 6. Those are acquisition. Without read → understand → evaluate → outcome → experience → future use they only add stored information.

**Gate:** one non-market lab shows retrieve → cite → bounded influence → persist against **its** outcome contract. Until then, that lab is a store, not a learner.

---

## 11. Hygiene (never the main path)

| Item | When |
|------|------|
| Fix `global_mind.py` `_llm_global_narrative` (`resp.text` + except) | After CLC.5, or same PR if it is a 5-line syntax/NameError blocking imports |
| Stop live DB pytest contamination | Separate; don’t block CLC |
| Expire 146 stale rationales | With CLC.R0 |
| `llama3` unused disk | Leave |

---

## 12. Day-2 milestone (copy this into the test docstring)

**Day 1 (already true in stores)**

- F-002118: Setup X performs badly in regime Y  
- E001: volume acceleration failed to add value after costs  

**Day 2**

Give Atlas a new candidate that matches those conditions.

Atlas must:

```text
retrieve relevant historical lessons
        ↓
put them into decision packet
        ↓
(optional) LLM reasons over them → rationale / UNREVIEWED
        ↓
deterministic decision engine + L0 gates
        ↓
decision
        ↓
persist experience_refs
```

**Pass**

- `experience_refs > 0`  
- F-002118 retrieved when setup/regime match  
- E001 retrieved when vol-accel / buy_name match  
- Packet score or caution **moved**  
- If LLM ran: rationale completed; else UNREVIEWED named  

That is the move from **memory** to **learning** — **in the market decide path**. It is not a certificate that every lab now learns.

---

## 13. Success / failure honesty

| We will call it success | We will not call it success |
|-------------------------|-----------------------------|
| Day-2 test green | More scientist notes |
| One live packet with refs | 60k LLM calls |
| One drained rationale | RAG answering the canary in chat |
| E001 cited on a buy_name explain line | New FEL experiment JSON |
| Consult includes matching `cross` | Seed belief count went up |

Learning audit L5 (`have: 0`) will stay 0 until a cited lesson is **validated on a later outcome**. CLC0 is the **prerequisite**, not a fake L5.

CLC.5 green does **not** mean Engineering, Personal, Research, or Books are intelligent. It means the **junction exists**. See §17.

---

## 14. Suggested implementation order (first three PRs)

1. **`lesson_influence` + consult retrieve + packet refs + hermetic Day-2** (CLC.1, .2, .3, .4, .5)  
2. **Live worker path + ranking bias replacement** (CLC.6)  
3. **R0 diagnose + one rationale drain + model-honesty strings** (CLC.R*)  

PR 1 is the whole game. If it slips, do not “compensate” with OCR or E003.

---

## 15. Open Items

| ID | Lane |
|----|------|
| `OI-CLC0` | **NOW · LOCKED** 2026-09-21 — this plan. Live 2026-09-22: Phase 1 green; CLC.R1 yellow |
| `OI-FEL0` E003+ | **BLOCKED** on sequence (CLC.R\* first). Day-2 is green. |
| `OI-SELF0` Phase 5 | **Amended** — only cited L2 as above |
| `OI-AGENT1` | Frozen; CLC.J1 is a supervised exception |
| Book/OCR | **AFTER** CLC.R1 + CLC.J1 (CLC.5/6 already green) |
| `OI-CF-SNAP0` | **AFTER CLC.J1** — post-decision counterfactual / opportunity-cost observation (not a trader) |

---

## 16. Operator lock checklist

Locked 2026-09-21 (operator review):

- [x] LLM never BUY/SELL  
- [x] SMA/RSI V1 remains live control  
- [x] L2 caps (±0.25 option / ±0.2 ranking)  
- [x] AUTHOR_CLAIM cannot L2  
- [x] No E003 until Day-2 green  
- [x] One reasoner + embed is the public story  
- [x] Day-2 test is the Phase 1 gate  
- [x] CLC.5 proves the **common junction**, not complete learning for every lab (§17)

**Lock:** 🔒 2026-09-21

---

## 17. Post-CLC applicability

CLC does **not** automatically activate all labs. It establishes the **common cognitive junction** that other labs subsequently plug into. Each lab still needs a domain-specific **outcome contract** and its own Day-2-style test.

| Lab | CLC dependency | What counts as learning | Not enough |
|-----|----------------|-------------------------|------------|
| **Market** | CLC.5 + CLC.6 | A retrieved lesson changes a later decide packet (cite + bounded L2 + `experience_refs`) | RAG canary, FEL JSON, consultation counts |
| **Research** | CLC.J1 | A previous investigation changes the next investigation’s plan or conclusion | Research-scientist sidecar counts |
| **Engineering** | CLC + **outcome contract** (test / review / simulation result) | A previous implementation or test result changes a later design recommendation | AST/graph/findings volume; pytest-contaminated repos |
| **Personal** | CLC + **goal/outcome contract** | A previous outcome changes a later recommendation (goals → action → result → pattern) | Fact store, 0 goals, mentor templates |
| **Books / sources** | CLC.B | An `AUTHOR_CLAIM` becomes evidence for a hypothesis (or contradiction vs E001); **never** L2 | Chunks + embeddings of a PDF |
| **Cross-domain** | CLC.X | A **validated** abstract lesson is retrievable in another domain | Operator seed `hidden_state` |

**Phase 6** (after CLC.X retrieve works): adapt the same closed loop; do not add brains, databases, or models. MATLAB/Simulink/PSpice/LabVIEW readers stay deferred until an engineering outcome contract exists — otherwise they only create more stored information.

Labs Integration north star still holds: data → experience → validated learning → retrievable tomorrow; the LLM is the interpreter; none of them is the trader. RL stays after that loop is proven.

---

## 18. CLC-adjacent — counterfactual / opportunity-cost observation (`OI-CF-SNAP0`)

Locked 2026-09-22: **after CLC.R1 + CLC.J1**, not before. This is **not** a new learning system and **not** a trading strategy.

Today Atlas can know “I did not buy HBLPOWER.” It cannot yet close:

```text
decision snapshot → later price + fundamentals
        ↓
counterfactual return + prediction error vs E[R]
        ↓
four-way classification (no hindsight)
        ↓
outcome → attribution → experience → candidate lesson → validation → future retrieval
```

**Reuse, do not fork:** `allocation_regret.py` (ICR.3, 1/5/20d chosen vs rejected) and `counterfactual_learning.py` (CF.1, +30d on buys). Densify those stores. Do not add a second OC engine.

**At each material decision (BUY, HOLD, reject), snapshot:**

- price, technicals, fundamental completeness, valuation, PLC.A, existing holdings, ranking, E[R]
- reasons for HOLD / BUY / rejection
- available `lesson_refs` / `experience_refs`

**Later (1d / 5d / 20d):** actual price, fundamental snapshot, `counterfactual_return`, prediction error (`actual − E[R]`).

**Four outcomes (required — a later up-move is not automatically a mistake):**

| Outcome | Meaning |
|---------|---------|
| Correct rejection | Subsequently performed poorly |
| Missed opportunity | Performed well **and** evidence available then supported the decision |
| Insufficient evidence | Performed well, but Atlas lacked information at decision time |
| Unavoidable / unknown | Outcome depended on information/events unavailable then |

`identifiable_at_decision` must stay honest. Price-up + deteriorating fundamentals is **not** evidence the original fundamental HOLD was wrong.

**Hard restriction:** opportunity_cost → observation → analysis → candidate → validation → possible lesson. **Never** `stock went up → increase BUY score`. L0–L3 stay intact. Advice-only until a cited, validated lesson is eligible for the existing bounded L2 caps.

**Separate:** opportunity cost (what happened to alternatives not chosen) vs prediction error (what Atlas expected vs what happened). Both are experiences for the **same** CLC junction.

Do not start this while CLC.R1 is yellow. The junction must first retrieve a lesson into a future decision; this layer then enriches the experience stream.
