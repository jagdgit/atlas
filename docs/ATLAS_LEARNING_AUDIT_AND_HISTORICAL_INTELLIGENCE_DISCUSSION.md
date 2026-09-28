# Atlas Learning Audit & Historical Intelligence

> **Status:** 🔒 **OPERATOR-LOCKED** 2026-08-23 · Amendment A (Auditor = instrument; destination = better Next-₹1 investor; multi-vintage historical lab)  
> **OI umbrella:** `OI-LEARN-AUDIT0` (Learning Auditor — instrument) · companion `OI-HIST-OPP0` (Historical Opportunity Lab — later)  
> **Parents (do not reopen / do not fork):**  
> [`ATLAS_NOW_CLOSED_LOOP_ROADMAP.md`](ATLAS_NOW_CLOSED_LOOP_ROADMAP.md) ·  
> [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md) ·  
> [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md) ·  
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) ·  
> [`ATLAS_CHAT_INFERENCE_CONTENTION_DISCUSSION.md`](ATLAS_CHAT_INFERENCE_CONTENTION_DISCUSSION.md)  
> **Destination (what Atlas is for):** Become a **better allocator of the next ₹1** — discover, compare, decide, learn.  
> **Instrument (what the Auditor is for):** Prove whether that is happening.  
> **Hard principle:** **Stored ≠ observed ≠ understood ≠ predicted ≠ learned ≠ improved.**

---

## 0. Destination vs instrument (Amendment A — critical)

| | Role |
|---|------|
| **Destination** | Atlas as investor-scientist: world → thesis → E[R] → Next-₹1 → outcome → learning → better future Next-₹1 |
| **Learning Auditor** | The **instrument** that proves (or falsifies) progress toward that destination |
| **Not the destination** | A prettier dashboard of row counts, LLM calls, or “audit theater” |

The Auditor exists so the operator never has to stare at thousands of DB rows and wonder whether Atlas is learning. Atlas must **prove** learning with evidence — or admit it has not.

**Next milestone (operator-facing):** not “Atlas made more trades,” but:

> Show five things Atlas genuinely learned; the evidence that caused each; how the prediction changed; whether subsequent outcomes improved; and whether Ollama contributed anything deterministic Atlas could not.

Until that report can be produced honestly, treat Atlas as:

> **A sophisticated experimental platform that is beginning to develop intelligence — not yet an intelligent investor.**

That is a diagnosis, not a criticism — and it sets the bar for OI-LEARN-AUDIT0.

---

## 1. Why this document exists

Atlas can already report activity:

> “154 consultations · 495 LLM inferences · 2 experiences · 18 fundamental records…”

That answers **throughput**. It does **not** answer:

> “Is Atlas actually becoming a better investor because of all this?”

This discussion locks:

1. The **destination architecture** (world → Next-₹1 → learning).
2. What counts as **learning** (vs a database row).
3. The Auditor as **instrument** (cannot declare success from row counts).
4. How **historical data** widens knowledge **without hindsight** (multi-vintage, not a Bosch detector).
5. How **Ollama** is used for the right work (bounded reasoning, not BUY/SELL).
6. What we **freeze**.

---

## 2. Ultimate capability (destination architecture)

```text
                    WORLD
                      │
          ┌───────────┼───────────┐
          ↓           ↓           ↓
    Historical     Current      Future /
    patterns       state        events
          │           │           │
          └───────────┼───────────┘
                      ↓
               Atlas Scientist
                 "What matters?"
                      ↓
               Candidate thesis
                      ↓
           ┌──────────┴──────────┐
           ↓                     ↓
     deterministic              LLM
     analysis                   reasoning
           │                     │
           └──────────┬──────────┘
                      ↓
             Expected return / risk
                      ↓
        name vs NIFTY vs sector vs peers
             vs incumbents vs CASH
                      ↓
                   Next ₹1
                      ↓
                   Outcome
                      ↓
                Attribution
                      ↓
                  Learning
                      ↓
           Better future decisions
```

This is closer to the original Atlas vision than a trading engine that accumulates rows.

**Economic center (unchanged):** Where should the next ₹1 go — why — what proves me wrong — what did I learn last time?

Not: “Is CIPLA technically buyable?”

That is how incumbent ratchet / CIPLA-style opportunity cost gets eliminated: unchosen names (including compounders) are ranked against holdings and cash, then fed into Next-₹1 / ACP.

---

## 3. The chain that must be completed

Every durable learning claim must progress (or honestly stall) through:

```text
DATA → EVIDENCE → HYPOTHESIS → PREDICTION → DECISION
  → OUTCOME → ATTRIBUTION → LEARNING → BELIEF/RULE UPDATE → NEXT ₹1
```

| Stage | Example | Not the same as |
|-------|---------|-----------------|
| **Data** | CIPLA PE = 36.1 | Evidence |
| **Evidence** | PE high vs sector/history | Hypothesis |
| **Hypothesis** | High valuation may cut forward E[R] | Learning |
| **Prediction** | Explicit E[R] / direction / horizon | A score in a packet |
| **Decision** | HOLD / DEPLOY / EXIT_REVIEW | A tick log |
| **Outcome** | Matured return vs cash / incumbent / challenger / NIFTY | MTM noise |
| **Attribution** | Why (helped/hurt/unknown) | Blaming the market |
| **Learning** | Before→after belief with confidence + falsifier | `experiences` row exists |
| **Belief/rule update** | Material strengthen/weaken/falsify | Soft advice that never binds |

**Rule:** If a record never progresses past “stored,” the Auditor must **not** count it as learning.

### 3.1 Learning statement shape

```text
LEARNING #017
Before:   belief B0
Evidence: …
Prediction: …
Decision: …
Outcome:  CIPLA X% · DEVYANI Y% · NIFTY Z%
Error:    …
Attribution: …
Update:   belief B1 (with falsifier)
Confidence: 0.71
Status: PROVISIONAL | SUPPORTED | WEAKENED | FALSIFIED
```

Reuse DI/LI/SELF — **no parallel learning database**.

---

## 4. OI-LEARN-AUDIT0 — Learning Auditor (instrument)

### 4.1 Job

Inspect existing stores and answer:

| # | Question |
|---|----------|
| 1 | What did Atlas **actually learn**? |
| 2 | What did Atlas **fail to learn**? |
| 3 | Is Atlas **getting better**? |
| 4 | Is the DB accumulating the **right** data (quality + decision-time integrity)? |
| 5 | What did the **LLM contribute**? |
| 6 | What should Atlas **learn next**? |

**Forbidden success criteria:** embeddings ↑, Ollama calls ↑, research jobs ↑, trades ↑.

### 4.2 Report sections (minimum)

**A. Learning statements** — numbered Learning Records (thin sample → `PROVISIONAL` + JIS hide).

**B. Known failure patterns** — IMPROVING / NOT SOLVED / PARTIALLY SOLVED (ratchet, missing E[R], news/policy sparse, LLM fail-at-decide, research-blocked DEPLOY still ranked, …).

**C. Rolling improvement** — prev window vs current: directional accuracy, E[R] calibration, relative ranking, **Next-₹1 vs cash / incumbent / best challenger**, opportunity cost, predictions→matured→attributed→beliefs updated.

**D. Data quality + decision-time integrity** — prices, fundamentals, news/policy, historical as-of-T, decisions only use `as_of ≤ decide_ts` (else `LOOKAHEAD`).

**E. LLM contribution scorecard** — not call counts:

```text
hypothesis → accepted/rejected → future observation → correct/incorrect → economic contribution
```

| Measure | Why it matters |
|---------|----------------|
| Relevant scientist/decide calls | Signal, not noise |
| Useful / validated / rejected hypotheses | Quality |
| LLM-induced decision changes | Did advice bind? |
| Of which later correct | Economic value |
| Contribution rate | One useful hypothesis can beat 495 empty calls |

**Baseline (later, measure-only):** deterministic-only vs LLM-assisted Next-₹1 / ranking.  
**Memory (measure-only):** with vs without experience retrieval.

### 4.3 Learning Health + weekly Learning Report

Separate from EOD fills email. Chat: “what did you learn this week?” / belief interrogation (why / confidence / falsifier / next test).

### 4.4 Implementation slices (no new DB)

| Slice | Deliverable | Status |
|-------|-------------|--------|
| **LA.0** | Honesty contract + Learning Record schema + “not learning” denylist | ✅ 2026-08-23 |
| **LA.1** | Daily `investment/learning_audit/{lab}/{day}.json` + evening lines + paper/overnight wire | ✅ 2026-08-23 |
| **LA.2** | Evening / weekly Learning Report section (densify beyond first lines) | ✅ 2026-08-23 |
| **LA.3** | LLM contribution join (fitness ↔ advice ↔ outcomes) | ✅ 2026-08-23 |
| **LA.4** | Rolling improvement + sample gates + LOOKAHEAD | ✅ 2026-08-23 |
| **LA.5** | Chat inherit | ✅ 2026-08-23 |

**Non-goals:** new strategies, capital increase, AtlasNet, blind concurrency bump, making the Auditor the product.

---

## 5. World evidence must converge (not siloed systems)

Do **not** permanently treat these as disconnected products:

News · Historical · Stock · Government · LLM

They converge into **evidence about an investment state**:

| Layer | Contents |
|-------|----------|
| **Company** | Revenue/margins/FCF/debt/ROCE/valuation/revisions/management/capex |
| **Industry** | Demand cycle, competitors, commodities, tech, capacity |
| **Government** | Budget, tax, duties, PLI, infra, regulation, rates, incentives |
| **World** | Crude, FX, geopolitics, global demand/supply chains/rates |
| **Market** | Price, momentum, RS, valuation regime, sector rotation |
| **Historical** | “When these co-occurred, what happened over H?” |

Then Ollama receives a **compressed, relevant evidence packet** — not millions of raw documents.

**LLM role (locked):**

```text
Data → deterministic facts → news/policy/history → bounded packet
  → Ollama → hypotheses / contradictions / explanations / E[R] reasoning
  → deterministic decision engine (admit/reject/unknown)
```

Never: `LLM → BUY/SELL`.

Use local Ollama **heavily for the right work** before assuming a bigger model is required. Measure contribution first (CHAT-INFER0 Stage 7 honesty).

---

## 6. Historical intelligence & opportunity discovery

### 6.1 Integrity vs discovery (honest)

| Capability | Band | Role |
|------------|------|------|
| Execution integrity (PLC, labs, flatten, FNO) | Strong | Don’t do stupid things |
| Next-₹1 / ACP / ICR | First-slices | Allocate & explain |
| Opportunity discovery (compounders) | **Weak** | Find wealth we do not own |

Integrity stays. Discovery is the missing layer **above** it.

### 6.2 Wrong vs right lesson

**Wrong:** “Bosch +240% over five years ⇒ buy Bosch.”  
**Right:** What was observable **before** the move? Did those features predict forward returns **out of sample** across many names?

Bosch is an **illustrative stress case**, not a live Atlas claim and not a teaching label.

### 6.3 OI-HIST-OPP0 — multi-vintage lab (Amendment A)

**Not now as a trading feature.** After LA.1–LA.3 so honesty scoring exists.  
**Do not jump to Bosch today.**

#### Anti-pattern: Bosch detector

Testing only “could Atlas have found Bosch?” risks overfitting one famous winner.

#### Required design: winners + false positives + losers

```text
Historical universe (500–1000 names)
        ↓
Freeze at T (blind to > T)
        ↓
Atlas selects top-K long-horizon candidates
  (quality / growth / FCF / debt / valuation / industry / policy / momentum → E[R])
        ↓
Hold conceptually for horizon H (e.g. 5y)
        ↓
Reveal outcomes at T+H
        ↓
Repeat vintages:
  2015→2020, 2016→2021, …, 2021→2026
```

**Real question:** Did Atlas **consistently** identify future winners *before they became obvious* — across vintages — while controlling false positives and including losers?

Example as-of table (illustrative):

| Candidate | Quality | Growth | FCF | Debt | Valuation | Industry | Policy | Mom | E[R] |
|-----------|---------|--------|-----|------|-----------|----------|--------|-----|------|
| Bosch | High | High | High | Low | Med | High | + | High | 18% |
| X | High | Med | High | Low | Low | Med | 0 | High | 15% |
| Y | Med | High | Med | Med | High | High | + | High | 13% |

Then reveal 3–5y outcomes. Attribute forecast errors. Missing capabilities become Learning targets — **never** hand-code “Bosch is good.”

Bosch on 2021-08-20 remains a **first serious stress test** of that lab — because failure tells us exactly what capability is missing — not because Bosch is special.

### 6.4 Continuous historical densify (always-on, especially off-market)

| Work | Purpose |
|------|---------|
| Scientist / BRE drain | REVIEWED research before RTH |
| Bars / fundamentals densify | Wider as-of-T states |
| Analogue retrieval into packets | Historical co-occurrence → outcomes |
| Opportunity Discovery (advice-only) | Unchosen vs book vs cash → Next-₹1 |
| Auditor refresh | Failures + LLM contribution |

---

## 7. Where Atlas is today (2026-08-23)

| Area | Band |
|------|------|
| Data / organization / execution integrity | ~80% |
| Allocation framework | ~60% |
| World awareness | ~30% |
| Prediction / attribution / proven learning | ~30–40% |
| LLM integration | ~40% |
| LLM **contribution** (proven) | ~20%* |
| Self-model / belief interrogation | ~20% |
| Opportunity discovery | **Weak** |

\*Unproven incremental economic value — not a verdict against Ollama.

**Diagnosis:** sophisticated experimental platform beginning intelligence — **not yet** an intelligent investor.  
**Direction:** correct (Next-₹1 closed loop).  
**Gap:** more plumbing than demonstrated intelligence — Auditor exists to close that honesty gap.

---

## 8. Locked operating sequence (keep — do not skip to Bosch)

```text
1. Bounce SCI-CHATMSG / off-hours research drain
2. LA.0–LA.1 Learning Auditor (instrument) first-slice
3. LA.2 Learning Report (≠ EOD fills)
4. LA.3 LLM contribution measurement
5. Densify recurring failures (ratchet, missing E[R], news/policy)
6. Historical analogue densify into evidence packets
7. Opportunity Discovery advice-only → Next-₹1
8. OI-HIST-OPP0 multi-vintage lab (Bosch = stress case, not detector)
9. Measure-only: LLM vs deterministic · memory on vs off
   ONLY THEN capital / strategy / AtlasNet (operator-gated)
```

**No extra capital** from this track until Next-₹1 consistency + learning evidence + operator unlock.

---

## 9. Freezes

| Freeze | Why |
|--------|-----|
| ❌ Make the Auditor the destination | Instrument only |
| ❌ “Learning” from row / LLM call counts | Hard principle |
| ❌ Teach “Bosch good” / single-name detector | Hindsight / overfitting |
| ❌ Jump to HIST-OPP0 before LA.1–LA.3 | Cannot score honesty |
| ❌ LLM → BUY/SELL | Deterministic admits advice |
| ❌ Parallel learning DB / new strategies as substitute | Coherence |
| ❌ More real capital / AtlasNet / blind concurrency | Gated |

---

## 10. Success conditions

1. Operator can get **five genuine Learning Records** with evidence, prediction change, and outcome link (or honest “none yet”).
2. Failure patterns have IMPROVING / NOT SOLVED status.
3. Rolling Next-₹1 quality measured (or honest unknown under sample gate).
4. Decision-time integrity flagged; lookahead rare/explicit.
5. LLM contribution rate measured; baseline experiment started.
6. At least one **multi-name, multi-vintage** point-in-time run without leakage (when HIST-OPP0 opens).
7. Belief interrogation works: believe / why / confidence / falsifier / next test.

---

## 11. Explicit non-goals this phase

- Vanity NIFTY beat before Learning Records exist.
- Capital upsizing because overnight research ran.
- Replacing Judgment **Belief Revisions/week** — Auditor **feeds** it.
- Opportunity Discovery product UI before LA.1–LA.3.
- Treating a single Bosch retrospective as “skill proven.”

---

## 12. Acceptance for plan lock

Operator confirms:

1. **Destination** = better Next-₹1 investor; **Auditor** = instrument that proves it.  
2. **Stored ≠ learned ≠ improved** remains law.  
3. Sequence stays: drain → LA.0–1 → report → LLM contribution → failures → analogues → discovery → **multi-vintage** HIST-OPP0 (Bosch stress, not detector).  
4. No capital unlock from this document alone.  
5. Next milestone = **five genuine learnings with evidence**, not more trades.

---

*Drafted 2026-08-23 · Amendment A same day (destination vs instrument · multi-vintage anti-detector · five-learning milestone). Registry: [`OPEN_ITEMS.md`](OPEN_ITEMS.md) `OI-LEARN-AUDIT0` · `OI-HIST-OPP0`.*
