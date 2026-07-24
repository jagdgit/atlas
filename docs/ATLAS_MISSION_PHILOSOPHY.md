# Atlas Mission Philosophy

> **Audience:** architects and operators defining *what every mission must be*.  
> **Not:** APIs, YAML knobs, or UI how-tos — see [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md) for those.  
> **Parent constitution:** [`ATLAS_OS_ROADMAP.md`](ATLAS_OS_ROADMAP.md) (P5–P14).  
> **Platform (settled):** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) — Programs → Missions → Workers; OS layers.  
> **Status:** foundational · **Date:** 2026-07-24  
> **Code mirror:** `atlas/missions/philosophy.py`

---

## Two questions Atlas must answer

| Layer | Question | Status today |
|-------|----------|--------------|
| **Layer 1 — Learning** | *Can Atlas learn?* | Strong — media → extract → KB; repos → engineering knowledge; owner archive → personal knowledge |
| **Layer 2 — Learning Governance** | *Did Atlas actually learn?* and *Did Atlas become better?* | Thin — pieces exist (Learning OS, experiences, self-improvement); no universal mission loop or daily governance report |

These are different questions. Shipping more extractors improves Layer 1. Governance improves Layer 2.

```
Layer 1                          Layer 2
────────                         ────────
Observe → Extract → Store        Evaluate → Reflect → Improve
"we ingested knowledge"          "we got smarter (or we didn't)"
```

**Do not invent a second Knowledge OS.** Governance sits on Learning OS + Decision Engine + Experiences + Reports (P11/P13/P14).

---

## Mission Operating Model

Not every mission is equal. Classify every template:

| Mission kind | Goal | Never stops? | Examples (today) |
|--------------|------|--------------|------------------|
| **learning** | Build knowledge / experience | ✅ | `owner_knowledge`, `repository_learning` |
| **monitoring** | Watch a stream; alert | ✅ | `technology_watch`, `security_monitoring`, `patent_watch` |
| **research** | Answer / deepen a question | ❌ (can complete) | `research` |
| **simulation** | Practice decisions safely | ✅ | `paper_trading` |
| **maintenance** | Improve Atlas itself | ✅ | `self_improvement` |
| **career** | Recommend opportunities | ✅ | `job_hunting` (P14: never apply) |

**Finite vs continuous** is part of the kind, not an afterthought. Research may finish. Owner Knowledge never does.

---

## Universal cognitive lifecycle

Every mission — regardless of kind — must expose where it is on this loop:

```
1. Observe
2. Learn
3. Decide          (may be "n/a" for pure learning/monitoring)
4. Record Why      (P9 — always)
5. Evaluate Outcome
6. Reflect         → Lesson Learned
7. Improve         → future decisions / policies / strategies
```

Operator-facing example:

```
Paper Trading
  Observation   ✓
  Reasoning     ✓
  Simulation    ✓
  Reflection    Waiting
  Improve       Waiting
```

Runtime mission statuses (`draft → active → …`) remain the **ops** lifecycle.  
This loop is the **cognitive** lifecycle. Both must exist; neither replaces the other.

### Experience journal shape (mandatory for decision-bearing missions)

Do **not** journal only:

> Bought Tata Motors

Journal:

| Field | Example |
|-------|---------|
| Observation | RSI oversold; price below 200 DMA |
| Reasoning | Mean-reversion setup within risk limits |
| Decision | Buy (sim) |
| Outcome | −6% |
| Reflection | Ignored earnings tomorrow |
| Lesson | Always check earnings calendar before entry |

Outcome without Lesson = history. Lesson without Improve = unused wisdom.

Paper trading today remembers sell outcomes as Experiences (`_remember_outcome`).  
**Gap:** reflection/lesson are thin; structured Observation→Lesson is the required shape going forward (see OI-MP1).

---

## Layer 1 pipelines (already the pattern)

```
Video / Media     → Transcript → Knowledge Extraction → Knowledge Base
Repository        → Architecture / Patterns           → Engineering Knowledge
Personal Archive  → Docs / Chats / Notes              → Personal Knowledge
Market (observe)  → OHLC / Indicators                 → Market Memory
```

Knowledge remains **global** (P12/P13). Mission ids are provenance, not ownership.

---

## Layer 2 — what "governance" means

Governance answers, without the operator asking *"did you learn?"*:

- What was newly learned (concepts, patterns, experiences)?
- What failed to learn (caps, STT failures, empty extracts)?
- What conflicts appeared?
- What decisions were made and how they turned out?
- What lessons will change future behavior?

### Daily Learning Report (target product)

```
Daily Learning Report
  Videos learned              5
  Repositories touched        2
  New concepts               81
  New engineering patterns   12
  Failed learning             3
  Knowledge conflicts         4
  Portfolio performance    +2.1%
  Lessons learned             7
```

This is a **governance report**, not a research answer and not a per-video Learning Report.  
Tracked as **OI-MP3**.

**Shipped (MP3):** `GET /v1/governance/daily` + mission template `learning_governance` (daily worker). Aggregates concepts/entities/relationships, lessons, contested findings, decision capability gaps, optional sim portfolio return.

---

## Paper trading — correct idea, wrong packaging (today)

One mission currently does: feed → indicators → decide → virtual fill → experience.

That is valuable because it teaches **decision making**, not because of stocks.

### Recommended split (OI-MP2) — three cooperating missions

| Mission | Loop | Decisions? |
|---------|------|------------|
| **Market Watch** | Market → OHLC → Indicators → Store | ❌ observation only |
| **Market Research** | News / company / macro → Knowledge | ❌ learning only |
| **Decision Simulation** | Market + Research + Portfolio → Decision → Outcome → Lesson | ✅ sim only (P10) |

Only **trade execution** is simulated. Feeds, news, fundamentals, and portfolio books should eventually be real (OI-D1). History alone is backtest; live observation is adaptation.

**Expanded target (discussion):** seven cooperating missions (Observer, Company, News, Event Research, Decision, Ledger, Mentor) as the Market Intelligence proving ground — see [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) (`OI-MI0`). Ship via a smaller first split (OI-MP2) unless Q1 chooses otherwise.

Until the split ships, `paper_trading` remains the flagship simulation mission and must grow its **Reflect → Improve** stages.

---

## Missions that learn from Missions

Missing piece today: meta-learning.

```
Paper Trading        → Experiences     → Decision Engine bias / strategy lessons
Repository Learning  → Patterns        → Engineering Intelligence
Owner Knowledge      → Preferences     → Personal Intelligence
Self-Improvement     → Eval deltas     → Atlas Maintenance
```

Workers already produce artifacts. A thin **Mission Learning** convention (OI-F4 / OI-MP5) standardizes:

`Recommendation → Outcome → Difference → Lesson → Future Decisions`

without inventing a new intelligence (P5).

---

## Long-term missions (named, not scheduled)

### Personal Intelligence
Emails / calendar / documents / notes → Personal Knowledge (extends `owner_knowledge`).

### Engineering Intelligence
Not embeddings-only:

```
Repository → Architecture → Patterns → Design Decisions
           → Known Bugs → Performance History → Engineering Memory
```

Answers *why* code was written, not only *what*.

### Engineering Mentor Mission (OI-MP4)
Periodically answers:

- What patterns improved over six months?
- What mistakes keep repeating?
- Where has Atlas accumulated the most technical debt?
- Which architectural decisions proved successful?

This is learning **engineering judgment** — closer to the long-term partner goal than more fact extractors.

---

## Map: builtins → philosophy

| Template | Kind | Never stops? | Strongest lifecycle stages today | Weakest |
|----------|------|--------------|----------------------------------|---------|
| `owner_knowledge` | learning | ✅ | Observe, Learn, Record | Evaluate / Reflect / Improve |
| `repository_learning` | learning | ✅ | Observe, Learn, Record | Reflect / Improve (as judgment) |
| `research` | research | ❌ | Observe, Learn, Decide (what-next) | Reflect across runs |
| `paper_trading` | simulation | ✅* | Observe→Decide→Evaluate | Reflect / Improve depth; live Observe (OI-D1) |
| `technology_watch` | monitoring | ✅ | Observe, Decide (priority), Record | Learn→Improve loop |
| `security_monitoring` | monitoring | ✅ | Observe, Decide, Record | Learn→Improve loop |
| `job_hunting` | career | ✅ | Observe, Decide, Record (P14) | Outcome feedback (no apply) |
| `self_improvement` | maintenance | ✅ | Evaluate, Decide, Improve (gated) | Broad Reflect |
| `patent_watch` | monitoring | ✅ | — stub — | all |
| `hello_watcher` | maintenance | ✅ | Observe (heartbeat) | n/a |

\*Continuous intent; fixture replay may exhaust (ops `completed`).

Code source of truth for this table: `atlas/missions/philosophy.py`.

---

## Frozen decisions

| # | Decision |
|---|----------|
| **MP1** | Every mission declares `mission_kind` + `never_stops` + cognitive lifecycle stage map |
| **MP2** | Layer 1 ≠ Layer 2; governance reports are first-class |
| **MP3** | Decision-bearing missions use the Experience Journal shape (Observation→…→Lesson) |
| **MP4** | Paper trading splits into Watch / Research / Simulation (planned); one mission until then |
| **MP5** | Do not expand media extractor types to satisfy governance — use verification + mission lifecycle (aligns KE14) |
| **MP6** | Missions teach missions via Experiences / Lessons — no new "meta intelligence" (P5) |
| **MP7** | Simulated = execution only; observation inputs should become real (OI-D1) |

---

## What to build next (priority)

1. **OI-MP1** — Experience journal fields on paper-trading (and convention for others)  
2. **OI-MP3** — Daily / periodic Learning Governance Report  
3. **OI-D1** — Live market observation for simulation missions  
4. **OI-MP2** — Split paper trading into three templates when Watch + Research feeds exist  
5. **OI-F4 / OI-MP5** — Cross-mission Recommendation→Lesson convention  
6. **OI-MP4** — Engineering Mentor mission (after Engineering Intelligence depth)  
7. **OI-KE0 V5** — Claim verification queue (Layer 2 for media knowledge)

---

## Explicit non-goals

- Collapsing Chat / Jobs / Missions into one surface  
- Real-money trading or auto-apply to jobs (P10 / P14)  
- Per-mission knowledge silos  
- A second consolidator / graph DB just to “look mission-ish”  
- Perfecting heuristics in extractors instead of governance  

---

## Related docs

| Doc | Role |
|-----|------|
| `ATLAS_OS_ROADMAP.md` | Constitution (P5–P14) |
| `MISSIONS_OPERATOR_GUIDE.md` | How to run templates |
| `MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md` | Layer 1 media learning (V4) |
| `PHASE_D_PLAN.md` | Decision Engine + paper trading spine |
| `OPEN_ITEMS.md` | OI-MP*, OI-D1, OI-F3, OI-F4 |
