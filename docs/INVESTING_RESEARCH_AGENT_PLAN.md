# Investing Research Agent — Plan (Final)

> **Status:** 🔒 **LOCKED for implementation** (operator review ~9.7/10 · aligned 2026-07-26)  
> **Goal:** Atlas becomes a **true investing research agent** — hypothesis-driven, knowingly aware, learns from thesis outcomes over time, surfaces analysis in **UI + email**, and supports **on-demand research** for any symbol — still inside Market Intelligence, not a new OS.  
> **Parents:** [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) ·
> [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) ·
> [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) ·
> [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) ·
> [`RESOURCE_OS.md`](RESOURCE_OS.md) ·
> [`OPERATOR_COMMUNICATION.md`](OPERATOR_COMMUNICATION.md)  
> **Open item:** `OI-IRA0` — Investing Research Agent spine  
> **Non-negotiables:** P10 simulation-only · MI4/MI5 compliant sources · Capability-gap honesty · host-first Resource OS (IR-RO11)

---

## 0. Verdict (locked)

**Atlas today is an automated paper-trading spine with thin research features. This plan turns it into a long-term investment research platform that uses paper trading as its validation environment — without inventing a Research OS.**

Review scores (architecture fit / SoC / workflow / learning / scale / readiness) averaged **~9.7/10**. Build it.

---

## 1. Problem (honest gap)

### Desired loop

```text
Hypothesis / Research Question
        ↓
Evidence (incremental dossier sections)
        ↓
Business understanding → Valuation → Thesis
        ↓
Margin of safety gate → Decision (sim)
        ↓
ThesisOutcome → Experience → better next time
        ↓
UI + email show studied / decided / learned
```

### Today

```text
NIFTY50 + Yahoo bars → momentum/liquidity/ROE·D-E seed rank
        ↓
Daily plan → Decision Simulation → Ledger
```

Missing: questions, freshness, coverage, Research Memory, MVR gates, on-demand research UX, thesis-vs-outcome learning, research in reports.

---

## 2. Product — Investing Research Agent (IRA)

| Property | Meaning |
|----------|---------|
| **Hypothesis-driven** | Every research task answers explicit `ResearchQuestion`s |
| **Incremental** | Update stale dossier sections only |
| **Knowing** | Per-section confidence + provenance + gaps |
| **Aware** | `doing_now` / `blocked_on` / `known_unknowns` / `next` / **coverage %** |
| **Bounded** | **Minimum Viable Research (MVR)** unlocks decisions — not 100% field fill |
| **On-demand** | Operator can research any symbol (e.g. MTARTECH.NS) without waiting for watchlist |
| **Deciding** | Thesis + valuation + MoS (configurable) before buy |
| **Learning** | ThesisOutcome → Experience → ranking/plan priors over months |
| **Visible** | Market UI + morning/evening investor emails include analysis |

**House:** Market Intelligence Program (M0–M7 + M2b research worker). Domain-specific — solar-plant test passes.

---

## 3. Locked principles

| # | Principle |
|---|-----------|
| **IRA1** | P10 simulation only |
| **IRA2** | One Knowledge OS for claims/evidence |
| **IRA3** | Capability honesty — never invent fundamentals |
| **IRA4** | No high-stakes buy without **thesis** (when gates on) |
| **IRA5** | Margin of safety — or explicit “valuation unknown → watch” |
| **IRA6** | Awareness contract always queryable |
| **IRA7** | Host-first + IR-RO11 for research Jobs/ticks |
| **IRA8** | Universe expansion deliberate (not NIFTY50-blind forever) |
| **IRA9** | Technicals = timing only, never business substitute |
| **IRA10** | Operator pin / override / pause always wins |
| **IRA11** | **Hypothesis-driven** — Research Questions drive work |
| **IRA12** | **MVR before perfection** — decide when core sections pass, deepen continuously |
| **IRA13** | **Coverage ≠ confidence** — both must be shown; high confidence + low coverage = caution |
| **IRA14** | **Incremental dossiers** — never full rebuild by default |
| **IRA15** | **Learn from thesis truth**, not price alone |
| **IRA16** | **On-demand research** is a first-class operator action |
| **IRA17** | **Reports & UI** must include research analysis, not only fills |

---

## 4. Canonical flow (locked order)

```text
Research Question(s)          ← hypothesis
        ↓
Research Plan                 ← per-company roadmap
        ↓
Evidence / Research Memory    ← observation → interpretation → …
        ↓
Incremental Dossier sections  ← freshness-aware updates
        ↓
Business understanding
        ↓
ValuationCase                 ← strengthens/weakens thesis
        ↓
InvestmentThesis
        ↓
MVR + MoS gates
        ↓
Decision Simulation (P10)
        ↓
ThesisOutcome → Experience → Mentor
```

Valuation is **not** a mere afterthought gate — it informs the thesis. Implementation may ship schema objects in parallel; conceptual order above is locked.

---

## 5. First-class objects (Market Program domain)

| Object | Purpose |
|--------|---------|
| **`ResearchQuestion`** | Explicit hypothesis (“Is debt sustainable?”, “Is moat strengthening?”) |
| **`ResearchPlan`** | Per-symbol roadmap of steps (collect → cash flow → IV → management → risks → done) |
| **`ResearchMemory`** | Observation → interpretation → evidence → confidence → alternatives → decision note |
| **`CompanyResearchDossier`** | Incremental 10-category sections + per-section confidence/freshness/coverage |
| **`ValuationCase`** | Multiples + DCF scenarios + IV range + MoS |
| **`InvestmentThesis`** | Bull/base/bear · catalysts · falsifiers · horizon · linked questions |
| **`ResearchAwareness`** | Phase, doing_now, blocked_on, known_unknowns, next, confidence, **coverage** |
| **`ThesisOutcome`** | Held / weakened / falsified + which assumption failed |
| **`MinimumViableResearch`** | Checklist that unlocks “decision allowed” |

No new platform OS. Objects live under Market Program + Knowledge/Experience stores.

---

## 6. Research Questions (hypothesis-driven)

Examples:

- Can this company compound earnings for 10 years?  
- Is the debt sustainable?  
- Does management allocate capital well?  
- Is valuation attractive at current price?  
- Is the moat strengthening or eroding?  
- Why did margins improve?

**Rule:** Every research Job/tick cites ≥1 open `ResearchQuestion`. Closing a question writes `ResearchMemory` + may update a dossier section.

---

## 7. Dossier — completeness without endless research

### 7.1 Ten categories (full surface — continuous improvement)

Business Quality · Profitability · Financial Health · Cash Flow · Valuation · Growth · Earnings Quality · Management · Moat · Risks  
(+ secondary: technicals, dividends, shareholder metrics, efficiency, macro, sector packs, qualitative, MoS checklist)

### 7.2 Minimum Viable Research (MVR) — decision unlock

Decision Simulation may treat research as **sufficient** when these core sections are at least `present` (not necessarily high confidence):

| Section | Required for MVR |
|---------|------------------|
| Business (understandable) | ✓ |
| Management (signals) | ✓ |
| Debt / financial health | ✓ |
| Cash flow (or explicit gap → watch-only) | ✓ |
| Valuation (or explicit unknown → watch-only) | ✓ |
| Risks (top impairment risks named) | ✓ |

Everything else = continuous improvement. **Atlas must not block forever filling 100+ fields.**

### 7.3 Per-section confidence

Independent of overall:

```text
Moat: High · Management: Medium · DCF: Low · Industry: Very High
→ Overall: Medium (pulled down by valuation)
```

### 7.4 Freshness (per-section aging)

| Section class | Typical TTL (tunable) |
|---------------|------------------------|
| Business model / moat structure | 90–180 days |
| Management / governance | 30–90 days |
| Industry | 14–30 days |
| Financials / cash flow | 7–14 days (faster near results) |
| Valuation | 6–24 hours (price moves) |
| Macro | 1–7 days |
| Technicals (timing) | minutes–hours |

Stale sections → Research Plan schedules refresh — **incremental**, not full rebuild.

### 7.5 Coverage

```text
research_coverage = weighted_fraction of intended DD surface examined
research_confidence = belief quality on examined parts
```

Operator warning matrix:

| | Low coverage | High coverage |
|--|--------------|---------------|
| **High confidence** | Caution — overconfident thin work | Strongest |
| **Low confidence** | Early / blocked | Deep but uncertain |

---

## 8. Research Memory (why we believed)

Store richer than conclusions:

```text
Observation
  → Interpretation
  → Evidence (refs)
  → Confidence
  → Alternative explanations
  → Next check / Decision note
```

Example: “Revenue slowed” → industry vs inventory vs competition → Low confidence → need next quarter.

Enables honest later revisions (“we preferred inventory correction; next print falsified it”).

---

## 9. Awareness contract (extended)

```text
symbol / dossier_id
phase: queued | researching | mvr_ready | thesis_ready | decided | monitoring | blocked
doing_now
completed[]
blocked_on[]          # CapabilityGap | waiting_data | host_pressure | …
open_questions[]
research_plan_step
known_knowns / known_unknowns
section_confidence{}  # per category
freshness{}           # per category as_of / stale
confidence            # overall
coverage              # 0–100%
mvr_satisfied: bool
next
last_updated
trigger: watchlist | event | on_demand | scheduled_refresh
```

Surfaces: Chat · Market UI research panel · Ops/journal · Investor emails.

**Rule:** Cannot claim high confidence without naming `known_unknowns`. Cannot hide low `coverage`.

---

## 10. On-demand research (locked capability)

Operator must be able to say:

- UI: **Research this symbol** (path/ticker e.g. `MTARTECH.NS`)  
- Chat: `research MTARTECH` / `research MTARTECH.NS fully`  
- API: `POST /v1/market/research/{symbol}` with `{ mode: "mvr" | "deep", force?: bool }`

Behavior:

1. Create/attach `ResearchPlan` + seed `ResearchQuestion`s (MVR set by default).  
2. Enqueue durable work (Job and/or M2/M2b tick) under Resource OS.  
3. Stream/progress via Awareness API.  
4. Stop at MVR unless `mode=deep` or operator continues.  
5. Never invent missing filings — gap + optional best-effort web Job labeled low confidence.

Pinned symbols always win over auto watchlist (IRA10).

---

## 11. True learning over time

```text
Thesis + Decision + Fill
        ↓
Holding / exit / time checkpoint
        ↓
ThesisOutcome
  - held | weakened | falsified
  - which assumption failed
  - ResearchMemory revisions
        ↓
Experience OS + Investment Mentor
        ↓
Update ranking priors · sector risk · “do not repeat” rules
        ↓
Next Research Plan / Daily Plan cites the lesson
```

Cadence: tick/daily outcome checks; weekly Mentor rollup; monthly “what I learned” digest.

**Metric of success:** after N weeks, Atlas cites prior ThesisOutcomes in new theses (“Last time capital-allocation failed on X; checking Y”).

---

## 12. UI + email — research in the reports

### 12.1 Market UI

- Watchlist/plan rows: coverage %, overall confidence, MVR badge  
- Symbol **Research** panel: awareness, open questions, section freshness, thesis, valuation, memory trail  
- **Research** button (on-demand)  
- Learner book: “Studied / Decided / Learned” (not only positions)

### 12.2 Investor emails (extend existing morning/evening)

| Report | Add |
|--------|-----|
| **Morning** | Candidates with thesis one-liner + coverage/confidence + MoS if any |
| **Evening EOD** | Studied today · theses formed/updated · decisions vs thesis · open questions · lessons |
| **Trade email** | Link thesis id + key assumptions + falsifiers |
| **Weekly (new)** | Coverage progress · ThesisOutcomes · Mentor lessons |

Copy must distinguish **fact / estimate / gap**.

---

## 13. Architecture fit

```text
Chat / Market UI / API (on-demand)
        ↓
Market Intelligence Program
  M0 Universe + Rank
  M1 Observer
  M2 Company Intelligence     → dossier section writer
  M2b Research Worker (NEW)   → questions, plan, valuation, thesis, awareness
  M3 News → claims
  M4 Event Research → Jobs
  M5 Decision Simulation      → MVR + thesis + MoS gates
  M6 Ledger
  M7 Mentor                   → ThesisOutcome lessons
        ↓
Knowledge OS · Experience OS · Planning OS · Resource OS · Operator Communication
```

---

## 14. Implementation roadmap (final)

### Phase A — Spine (start here) · target: visible honesty + on-demand

| ID | Item | Outcome |
|----|------|---------|
| **IRA.1** | Dossier schema v0 | Sections + gaps + per-section confidence/freshness stubs |
| **IRA.1b** | ResearchQuestion + ResearchPlan + ResearchMemory schemas | Hypothesis-driven spine |
| **IRA.1c** | MVR checklist + coverage metric | Decision unlock ≠ 100% fill |
| **IRA.2** | Awareness API | `GET /v1/market/research/{symbol}` full contract |
| **IRA.2b** | On-demand start | `POST /v1/market/research/{symbol}` + Chat/UI hook |
| **IRA.3** | ValuationCase v0 (multiples-first; DCF stub) | Feeds thesis |
| **IRA.4** | InvestmentThesis v0 | Linked to questions + valuation |
| **IRA.5** | UI research panel + Research button | Operator-visible |
| **IRA.6** | Email: morning/evening research sections | Studied/decided/gaps |

**Phase A done when:** operator can on-demand research a non-NIFTY50 name, see awareness + coverage + gaps, and evening email mentions what was studied.

### Phase B — Depth & incremental refresh

| ID | Item | Outcome |
|----|------|---------|
| **IRA.7** | Incremental section updates + TTL freshness worker | No full rebuild |
| **IRA.8** | Expand screener/quality fields | ROIC, margins, FCF, CAGRs when supplied |
| **IRA.9** | Filings/news → ResearchMemory + dossier sections | Provenance preserved |
| **IRA.10** | Universe expansion | NIFTY100/500 or custom membership |

### Phase C — Gates & plan citation

| ID | Item | Outcome |
|----|------|---------|
| **IRA.11** | DCF scenarios + MoS % | ValuationCase complete v1 |
| **IRA.12** | Decision gates | `require_thesis`, `require_mvr`, `require_mos`, min coverage |
| **IRA.13** | Daily Plan cites dossier/thesis/coverage | Learner UI + API |

**Default for new India learner portfolios:** `require_mvr=true`, `require_thesis=true`; `require_mos=true` when valuation present else force Watch.

### Phase D — Long-horizon learning

| ID | Item | Outcome |
|----|------|---------|
| **IRA.14** | ThesisOutcome worker | Timed + on exit |
| **IRA.15** | Mentor writeback | Experience OS lessons |
| **IRA.16** | Ranking consumes research coverage/confidence | Prefer researched names |
| **IRA.17** | Weekly research learning digest email | What changed in beliefs |

### Phase E — Hardening

| ID | Item | Outcome |
|----|------|---------|
| **IRA.18** | Live compliant fundamentals adapter | Replace proxies where possible |
| **IRA.19** | Sector packs | Banks / SaaS / manufacturing |
| **IRA.20** | Technical pack labeled timing-only | Optional |
| **IRA.21** | Heavy research process isolation | **v0:** IR-RO11 budgets + cooperative yield on research workers (full OS process isolation remains Resource OS follow-on) |

---

## 15. Acceptance — “true research agent”

1. On-demand research works for arbitrary `.NS` symbols (MVR path).  
2. Awareness answers without hallucination; gaps explicit.  
3. Coverage and confidence both shown; high/low mismatch warned.  
4. MVR can unlock Watch/Buy path without 100% dossier.  
5. Thesis + valuation inform decisions; MoS configurable.  
6. ThesisOutcomes change later behavior (citable lessons).  
7. UI + morning/evening emails include research analysis.  
8. Host remains stable (Resource OS / IR-RO11).  
9. Still P10 — no live broker.

---

## 16. Explicit non-goals

- Research OS as a new platform layer  
- Filling every DD field before any conclusion  
- Scraping against ToS / inventing line items  
- Technicals overriding business quality  
- “Price up ⇒ good trade” as the learning signal  
- Raising concurrency to rush research without Ops evidence  

---

## 17. Relationship to existing plans

| Plan | Role |
|------|------|
| IL.* | Universe → rank → plan → sim front door — keep |
| MI M1–M7 | Worker house — keep; M2b deepens research |
| IR-RO11 | Memory budgets for research Jobs |
| OPERATOR_COMMUNICATION | Channel for research digests |
| This doc | **Research depth + awareness + learning + on-demand + reports** |

---

## 18. Near-term execution order (locked)

1. **IRA.1 / 1b / 1c** — schemas (dossier, questions, plan, memory, MVR, coverage)  
2. **IRA.2 / 2b** — awareness + on-demand API  
3. **IRA.3 → IRA.4** — valuation then thesis (conceptual order)  
4. **IRA.5 + IRA.6** — UI + email visibility  
5. Then Phase B–D as listed  

Do **not** wait for live NSE filing clients to start Phase A.

---

## 19. Operator lock (accepted)

- [x] Keep inside Market Intelligence (no Research OS)  
- [x] Awareness contract + coverage  
- [x] Hypothesis-driven Research Questions  
- [x] Freshness + incremental dossiers  
- [x] Research Memory  
- [x] MVR before endless completeness  
- [x] Valuation informs thesis  
- [x] On-demand research  
- [x] True thesis-outcome learning over time  
- [x] UI + investor emails include analysis  
- [x] **Proceed to implement Phase A**

---

*End of locked plan. Implement IRA.*; do not open a parallel stock-picker architecture essay.*
