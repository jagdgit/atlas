# Belief Revision & LLM Intelligence — FINALIZED PLAN

> **Status:** 🔒 **OPERATOR-LOCKED** 2026-08-10 (amendment A: Curiosity · Counterfactual · Uncertainty · semantic-belief ownership)  
> **OI umbrella:** `OI-BRE0`  
> **Companions:** `OI-EVID-NET0` · `OI-WSO0` · `OI-COG-BUDGET0` · `OI-LLM-OS0` · `OI-MEM-LLM0` · `OI-META-COG0` · `OI-CURIOSITY0` · `OI-CF0` · `OI-UNCERT0` · `OI-MKT-COV` (perception)  
> **Does not reopen:** Strategy V1 control · DI/LI/LQ architectures (reuse seams) · RLD D1–D6 · AtlasNet gates  
> **North star:** Atlas becomes an AI that **develops judgment** — not a better paper-trading bot.  
> **Horizon check:** architecture intended to evolve credibly over **1–3 years** (see §2.1).

**Evidence / history:** this file supersedes the discussion draft of the same name.  
**Related:** [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md) · [`OPEN_ITEMS.md`](OPEN_ITEMS.md)

---

## 0. Locked question

Not: “How do I make Atlas trade?”  
Not: “How do I make Atlas use LLMs more?”

**Yes:**

> How does Atlas become an AI that develops judgment?  
> What role should the LLM play inside Atlas’s brain?

| Today | Locked target |
|-------|----------------|
| Executes missions | Forms **beliefs** |
| Records trades | **Explains why** it traded |
| Stores research | **Changes its mind** when evidence changes |
| Generates reports | Develops **judgment** |
| Remembers events | Learns **patterns** |

---

## 1. Permanent architecture (do not reopen)

### 1.1 Cortex / nervous system

```text
                 LLM CORTEX
         Understand • Reason • Compare
         Reflect • Revise • Learn
                  ▲
                  │
         World State Objects (beliefs)
                  ▲
                  │
       Deterministic Nervous System
     Observe → Store → Execute → Measure
```

| Deterministic forever | LLM-centered (cortex) |
|----------------------|------------------------|
| Prices, ledger, fees, taxes | Research, sector/business understanding |
| Scheduling, Host Guard, queues, retries | Thesis construction, contradiction detection |
| Risk limits, paper execution, KPIs | Belief revision, lesson extraction |
| Dataset / experiment tracking | Mentor dialogue, cross-domain reasoning |
| Strategy V1 **control** execution | Valuation *interpretation* (not PE arithmetic) |

**LLM-centered, not LLM-everywhere.**

### 1.2 Cognitive loop (permanent)

```text
Observe → Represent → Understand → Reason → Decide → Reflect → Revise → Learn
```

Reusable pattern across Market / Career / Engineering / Personal:

```text
Deterministic → Evidence Pack → LLM Understand → LLM Reason
    → Deterministic Decide → LLM Reflect → LLM Revise
```

### 1.3 Learning event (permanent)

> New evidence + existing belief + comparison + updated belief.  
> Code / timers / emails are **not** learning events.

### 1.4 Every mission must leave a cognitive output (permanent)

Operational output alone is insufficient.

| Mission family | Operational (keep) | Cognitive (required) |
|----------------|--------------------|----------------------|
| Research | Dossier | WSO update · belief Δ · open questions · confidence · memory candidate |
| Paper / decision sim | Buy/sell/hold | Frozen rationale · expected outcome · falsifiers · future evidence schedule |
| Career | Job recommendation | Skill-gap hypothesis · career belief update · long-term strategy note |
| Engineering | Design/review artifact | Belief about approach · validation evidence · procedure candidate |
| Mentors / evening | Report | Mind-change · evidence delta · calibration slice |

If every mission leaves cognition, Atlas **compounds**.

### 1.5 Coding is substrate, not competition

Persistent WSO, revision history, provenance, confidence, lessons, experiments, outcomes, and memory layers are what let LLM reasoning **compound**. Without them Atlas is “ChatGPT with tools.”

### 1.6 Freeze policy (next cognition window)

**Freeze / deprioritize:** strategy optimization, new indicators, new ranking factors, NN/RL, advanced trading statistics, portfolio-optimization research, infrastructure vanity (extra dashboards/KPI categories/templates/queues beyond Resource OS needs).

**Allowed platform work:** bugfixes, Host Guard/safety, perception (CAP/EVID-NET), and thin seams required for WSO/BRE.

**Horizon:** cognition-heavy for the **next several weeks to ~3–4 months**; revisit freezes only after Phase 3 (Belief Revision) is live and producing real mind-changes.

### 1.7 Semantic belief ownership (permanent — amendment A)

> **Deterministic code may execute actions, but only the LLM may create or revise semantic beliefs.**

| Deterministic may | Only LLM may |
|-------------------|--------------|
| Calculate (PE, P&L, RSI, coverage) | Say “this business is becoming stronger” |
| Schedule / queue / checkpoint | Say “management quality improved” |
| Execute fills / risk limits | Say “the moat weakened” |
| Detect threshold crossings | Say “I was wrong because I over-weighted policy tailwinds” |
| Store evidence packs & unknowns lists | Author thesis / belief text / revision narrative |

This keeps Atlas from collapsing back into a rule engine with fluent labels.

### 1.8 Three permanent mechanisms (amendment A — lock before much more code)

#### A. Active Curiosity Engine · `OI-CURIOSITY0` (highest of the three)

BRE revises when evidence changes. **Curiosity** notices what Atlas does **not** know and actively seeks it.

```text
WSO.unknowns[]  →  (Cognitive Budget allows)  →  queued research task
  Entity / Goal / Evidence needed / Priority
```

Example: belief “APOLLOHOSP has strong pricing power” @ 0.62 with unknowns occupancy / ARPOB / expansion capex / debt → research mission “determine occupancy trend” (quarterly presentation, management commentary, segment metrics).

**Rule:** every WSO holds `unknowns[]`; unknowns **automatically** generate research missions when budget allows. That is what makes an agent feel alive.

#### B. Counterfactual Learning · `OI-CF0`

After every **important** decision, ask: *What would have happened if I had done nothing (or chosen an alternative)?*

Example — bought EICHERMOT; +30d:

| Path | Return |
|------|--------|
| Actual | +8% |
| Hold cash | +0% |
| Buy NIFTY ETF | +2% |
| Buy top-ranked alternative | +11% |

Learn whether the decision beat **available alternatives**, not only whether P&L was positive. Professional decision systems improve this way.

#### C. Uncertainty Ledger · `OI-UNCERT0`

Confidence alone is not enough. Persist **sources** of uncertainty on the WSO:

| Dimension | Example levels |
|-----------|----------------|
| Data uncertainty | high / medium / low |
| Model uncertainty | … |
| Execution uncertainty | … |
| Macro uncertainty | … |
| Governance uncertainty | … |

Later: “Most mistakes occur when governance uncertainty is high” — more valuable than a higher win rate.

---

## 2. What a “real AI agent” means here

| Property | Atlas today | Target |
|----------|-------------|--------|
| Acts autonomously | Partial | Yes |
| Maintains goals | Partial | Yes |
| Remembers past | Yes | Better (layered memory) |
| Forms beliefs | Weak | Yes (WSO) |
| Revises beliefs | No | Yes (BRE) |
| Plans future actions | Partial | Yes |
| Explains reasoning | Basic | Yes (decide-time + packets) |
| Learns from outcomes | Weak | Yes |
| Improves judgment | No | Yes (calibration + meta-cognition) |

### 2.1 Credible horizon (operator confidence — locked)

| When | Realistic target |
|------|------------------|
| **~1 month** | Reliable autonomous **research assistant** (perception + WSO + curiosity queue) |
| **~3 months** | Agent that can **explain, defend, and revise** investment theses |
| **~6 months** | Cross-domain assistant that **remembers prior reasoning** and applies it |
| **~12 months** | Genuinely useful long-term **decision partner** |

Far more valuable than “an AI that trades stocks.”

---

## 3. Permanent phase order

```text
Phase 1  Reliable perception     (know what happened)
Phase 2  Representation          (WSO + Uncertainty Ledger)
Phase 2b Active Curiosity        (unknowns → research missions)
Phase 3  Belief Revision         (change mind with evidence)
Phase 3b Counterfactual Learning (decision vs alternatives)
Phase 4  Memory distillation     (episodic → semantic → procedural)
Phase 5  Cross-domain cognition  (one brain)
Phase 6  Meta-cognition          (reasoning attribution)
… later  Strategy experiments → AtlasNet (gated)
```

### Phase 1 — Reliable perception · `OI-MKT-COV` + `OI-EVID-NET0`

Finish: market capture, symbol aliases, **session freshness**, fundamentals (FCF), real news, timeline integrity.

Without perception, reasoning is fake. Live gap (2026-08-10): bars stuck on `2026-08-07`; dead tickers 404; Yahoo 429; FCF thin; RSS off — see §8.

**Done when:** last bar = last NSE session for ≥95% of membership; aliases resolve or explicit unknown; open books have PE+FCF+D/E or explicit unknown; news lane non-seed or honest unknown.

### Phase 2 — Representation · `OI-WSO0` + `OI-UNCERT0`

World State Objects for every important entity: company, strategy, career goal, engineering project.

Fields (company example): business/sector understanding, named beliefs + confidence, thesis, falsifiers, **unknowns[]**, **uncertainty ledger** (data / model / execution / macro / governance), evidence ids, revision history, linked decisions/outcomes.

**Semantic belief text** is written/revised only by the LLM (§1.7). Deterministic code may initialize empty shells and attach measured fields.

**Done when:** every open-book name has a WSO with unknowns + uncertainty dimensions; evening can print mind-change/evidence delta from structure alone (even if all `unchanged`).

### Phase 2b — Active Curiosity · `OI-CURIOSITY0`

Unknowns on WSOs enqueue research tasks under Cognitive Budget (not every unknown every night).

**Done when:** open-book unknowns produce durable research queue entries; completed research feeds evidence packs (not silent drops).

### Phase 3 — Belief Revision · `OI-BRE0` + `OI-COG-BUDGET0` + `OI-LLM-OS0`

Evening heart:

- What did I believe yesterday?  
- What evidence arrived today?  
- Did confidence change?  
- What remains unknown?  
- What should I investigate tomorrow?  

Three windows: **morning** (hypotheses / evidence needed) · **decide** (async rationale + falsifiers) · **evening** (revise + lesson). Batch-first; never real-time LLM; Cognitive Budget gates passes. **Only LLM creates/revises semantic beliefs** (§1.7).

**Done when:** ≥1 lab shows cited strengthen/weaken over a week; empty-delta days say so honestly.

### Phase 3b — Counterfactual Learning · `OI-CF0`

On important decisions (material buys/sells), schedule +30d (and optional +7/+90) counterfactual panels: cash · index · top alternative · (optional) do-nothing hold of prior book. Deterministic computes returns; LLM may narrate *decision quality vs alternatives* (semantic).

**Done when:** closed material decisions have a counterfactual record; evening/weekly can show “beat / matched / lost to alternative.”

### Phase 4 — Memory distillation · `OI-MEM-LLM0`

Episodes → concepts → procedures (BATCH). Mentors/research must **read** these layers.

### Phase 5 — Cross-domain cognition · `OI-LLM-OS0` / BRE.5

Same brain notices shared reasoning patterns across Market / Career / Engineering / Personal.

### Phase 6 — Meta-cognition · `OI-META-COG0` (after BRE)

Not only *what* I believe — **why** that belief, which **reasoning pattern** produced it, and whether that pattern is historically reliable.

Example: “Strong brand → pricing power” historically 61% → reduce confidence on future brand-based theses.  
This is **reasoning attribution**, distinct from trade attribution.

---

## 4. Cognitive Budget (locked)

Not every ticker nightly.

| importance × novelty × uncertainty | `llm_budget` |
|------------------------------------|--------------|
| high | up to 3 passes |
| medium | 1 pass |
| low | **0** (deterministic Represent only) |

Queue: open books + Tier-A with evidence_delta, ordered by budget, hard nightly pass cap. Checkpoint per WSO; pause on RAM.

---

## 5. Atlas IQ (judgment, not only returns)

Calibration of high-confidence predictions, overconfidence gap, belief-change rate, lesson reuse, falsifier hit rate. Separate from Trading Evidence maturity (RLD split remains).

---

## 6. Implementation slices (engineering order)

| Slice | OI | Ships |
|-------|-----|-------|
| **CAP.1** | MKT-COV | Aliases (`ZOMATO→ETERNAL`, `TATAMOTORS→TMPV`, `NIFTY→^NSEI`, …); session-fresh ≠ `FRESH_DAYS`; stop Yahoo hammer in cooldown |
| **E0–E2** | EVID-NET0 | Seed≠evidence; curated RSS enable; Screener FCF cadence |
| **BRE.1** | WSO0 + UNCERT0 | WSO store + unknowns + uncertainty ledger + evening mind-change / evidence delta (no LLM semantic text yet, or LLM-seeded once) |
| **CUR.1** | CURIOSITY0 | Unknowns → research queue under Cognitive Budget |
| **BRE.2** | BRE0 + COG-BUDGET0 | Evening LLM revise when budgeted + delta (**only LLM revises semantic beliefs**) |
| **CF.1** | CF0 | +30d counterfactual panels on material decisions |
| **BRE.3** | LLM-OS0 | Decide-time async rationale into packet |
| **BRE.4** | LLM-OS0 | Morning hypothesis / evidence-needed BATCH |
| **BRE.5** | LLM-OS0 | Global WSO + mentors from revision history |
| **MEM.1** | MEM-LLM0 | Episodic → semantic / procedural |
| **IQ.1** | BRE0 | Calibration section |
| **META.1** | META-COG0 | Reasoning-pattern ledger (after BRE stable) |
| **GENE** | GENE0 | GENE.1 assemble ✅; lesson→next densify remaining |

Strategy V1 remains **control**. LLM recommends; deterministic executes.

---

## 7. Locked decisions (B1–B26)

| ID | Decision | Status |
|----|----------|--------|
| B1 | Learning event definition | 🔒 |
| B2 | Cortex / nervous; LLM-centered not everywhere | 🔒 |
| B3 | 8-stage cognitive loop | 🔒 |
| B4 | World State Objects | 🔒 |
| B5 | Deterministic vs LLM forever split | 🔒 |
| B6 | Strategy V1 frozen; pause strategy/NN/RL work | 🔒 |
| B7 | Phase order: perception → WSO(+UNCERT) → Curiosity → BRE → CF → memory → cross-domain → meta | 🔒 |
| B8 | Three LLM windows; batch-first; never real-time | 🔒 |
| B9 | Cognitive Budget | 🔒 |
| B10 | Seed news never revises beliefs | 🔒 |
| B11 | Evening always: mind-change + evidence delta | 🔒 |
| B12 | Understanding > action as primary LLM output | 🔒 |
| B13 | Cross-domain same architecture | 🔒 |
| B14 | Episodic → semantic / procedural | 🔒 |
| B15 | Atlas IQ includes calibration | 🔒 |
| B16 | Coding = compounding substrate | 🔒 |
| B17 | Session-fresh + aliases P0 before revise-on-today | 🔒 |
| B18 | Every mission leaves cognitive output | 🔒 |
| B19 | Freeze infrastructure vanity; cognition-heavy window | 🔒 |
| B20 | Meta-cognition after BRE (reasoning attribution) | 🔒 |
| B21 | No NN / AtlasNet until genealogy + BRE samples | 🔒 |
| B22 | Open-question defaults in §9 adopted unless overridden | 🔒 |
| B23 | **Only LLM may create/revise semantic beliefs** (§1.7) | 🔒 |
| B24 | Active Curiosity Engine (`OI-CURIOSITY0`) — unknowns → research | 🔒 |
| B25 | Counterfactual Learning (`OI-CF0`) — decision vs alternatives | 🔒 |
| B26 | Uncertainty Ledger (`OI-UNCERT0`) — structured uncertainty sources | 🔒 |

---

## 8. Perception baseline (locked awareness — 2026-08-10)

| Issue | Finding |
|-------|---------|
| Session bars | 192 durable files; last date **2026-08-07**; Mon session missing; not NSE holiday |
| Freshness | `FRESH_DAYS=5` can report grade B while missing today |
| Aliases | 404: `ZOMATO.NS`, `TATAMOTORS.NS`, `HBLPOWER.NS`, `NIFTY` vs `ETERNAL` / `TMPV` / `^NSEI` |
| Yahoo | ~143×429 cooldown; paper still logs cooldown gaps |
| Fundamentals | FCF **2/18** |
| News | RSS defaults all disabled; seed headlines non-evidence |

---

## 9. Defaults adopted for former open questions

| # | Topic | Locked default |
|---|--------|----------------|
| 1 | Nightly queue | Open books + Tier-A; hard queue / pass cap |
| 2 | Confidence | Named beliefs 0–1 **and** overall `thesis_strength` 0–10 |
| 3 | Falsified | Auto soft-advice; operator confirm before hard exit reason |
| 4 | Decide-time LLM | **Async** — never block sim fill (`llm_rationale` or `llm_pending`) |
| 5 | Model host | Local Ollama first |
| 6 | WSO storage | Shared interface + domain payloads; one revision-log shape |

---

## 10. Remaining ambiguities (resolve during implementation, not blockers to start)

These do **not** reopen architecture. They need operator/product choices as slices ship.

| ID | Ambiguity | Options | Suggested default when coding |
|----|-----------|---------|-------------------------------|
| **A1** | How many RSS feeds to enable in E1 week 1? | PIB only · PIB+SEBI · wait for verified equity news RSS | Start **PIB only** if URL returns XML; else operator-supplied equity RSS allow-list entry |
| **A2** | `HBLPOWER` canonical Yahoo id? | Manual map · drop from universe · mark delisted | Probe once off-cooldown; else `identity_unknown` + exclude from live chart |
| **A3** | Parallelism: CAP.1 vs BRE.1 | Strict serial · parallel | **Parallel allowed** — CAP.1 + BRE.1 schema; **BRE.2 waits** on E0 + some real deltas |
| **A4** | Cognitive-output retrofit | All missions at once · Market first · template-by-template | **Market paper + research + evening first**; Career/Engineering in BRE.5 |
| **A5** | Platform freeze exceptions | Bugs only · + Resource OS tuning · + UI polish | **Bugs + Host Guard/safety + perception only** |
| **A6** | WSO for closed positions | Keep forever · archive after N days · drop | Keep **≥1 year** or until lesson distilled |
| **A7** | Soft-bias from BRE into Decision Engine | Off · advice-only · soft-bias on | **Advice-only** until calibration sample gate |
| **A8** | Meta-cognition pattern taxonomy | Free text · controlled vocabulary | Start **free text + tags**; vocab after 50+ revisions |
| **A9** | Screener FCF cadence | Daily open books · weekly universe | **Daily open books**; weekly rest |
| **A10** | When is Phase 1 “done enough” for BRE.2? | Strict §3 Done when · pragmatic open-books only | **Pragmatic:** open books session-fresh + aliases for those names + E0; universe-wide grade can lag |
| **A11** | Curiosity: max research tasks / night | 1 · 3 · 5 | **3** under Cognitive Budget |
| **A12** | CF horizon set | +30 only · +7/+30/+90 | **+30** required; +7/+90 optional |
| **A13** | CF “top alternative” definition | Rank#1 that day · best same-sector · operator pin | Rank#1 **available** that day (excluding self) |
| **A14** | Uncertainty dimensions editable by rules? | Levels from missing-data heuristics · LLM only | Deterministic may set **data** uncertainty from gaps; LLM sets narrative dimensions |

---

## 11. Explicit non-goals (locked)

- Optimizing SMA/RSI/ATR/ranking for “edge” during this window  
- Neural nets, RL, AtlasNet training  
- LLM rewriting ledger, fees, or V1 silently  
- Revising beliefs from seed/placeholder news  
- Infrastructure-heavy dashboards/KPI sprawl as a substitute for cognition  
- Claiming Atlas is already intelligent because reports improved  

---

## 12. First implementation kickoff

| Slice | Status |
|-------|--------|
| CAP.1 | ✅ code 2026-08-10 |
| E0 | ✅ code 2026-08-10 |
| BRE.1 | ✅ code 2026-08-10 (WSO shells; no LLM semantic text) |
| CUR.1 | ✅ code 2026-08-10 |
| BRE.2 | ✅ code 2026-08-10 (budgeted LLM; hermetic skip paths) |
| CF.1 | ✅ code 2026-08-10 (+30d cash/index/alt; evening section) |
| E1 | ✅ code 2026-08-10 (PIB RSS allow-list; SEBI/RBI stay off) |
| E2 | ✅ code 2026-08-10 (open-books-only FCF daily; Sunday IST weekly universe) |
| BRE.3 | ✅ code 2026-08-10 (async decide-time rationale sidecar; never blocks fill) |
| BRE.4 | ✅ code 2026-08-10 · **AttributeError fixed 2026-08-11** (ChatMessage path) |
| BRE.5 | ✅ code 2026-08-10 (global WSO + mentor advice-only digest) |
| MEM.1 | ✅ code 2026-08-10 (episodic→semantic/procedural distill) |
| IQ.1 | ✅ code 2026-08-10 (calibration section: LQ.5 + revision flip rate) |
| META.1 | ✅ code 2026-08-10 (reasoning-pattern ledger; free-text tags + reliability) |
| GENE.1 | ✅ code 2026-08-10 (assemble + honest gaps + evening + API + parent stamp) |

Hermetic: … · `tests/test_mem1_iq1.py` · `tests/test_meta1_reasoning_patterns.py` · `tests/test_gene1_genealogy.py`.

**Cognition kickoff window (CAP.1 → GENE.1) complete** for Market Program (scaffolding).

**2026-08-11 pivot:** scaffolding ≠ judgment. Densify under [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md) (`OI-JDG0`) — historical bars, evidence, real BRE cortex passes, JIS — before any strategy/NN expansion.

**2026-08-11 evening progress:** Judgment Month day-0 ops complete (J1 kicked · BRE.4 fixed · hourly digests + ledger UI live). **J2/J3 densify landed** (open-book critical fields · evening four-answer mind-change). **J4 densify landed** (curiosity→IRA). **Amendment C:** DCA + JIS Belief Revisions today/7d **code landed** (`daily_cognitive_agenda.py` · evening/morning reports). Next: live verify morning agenda · real BRE.2 revises · full JIS calibration when sample gate · only then J5.
