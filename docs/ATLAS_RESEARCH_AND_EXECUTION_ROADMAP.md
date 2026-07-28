# Atlas Research & Execution Roadmap — Final Lock

> **Status:** 🔒 **FINALIZED** (operator lock 2026-07-28)  
> **Purpose:** Single implementation order across three independent streams — do not reopen architecture; ship in phased order.  
> **Streams:**
> - [`IRA_NEXT_LEAP_EVIDENCE_PLAN.md`](IRA_NEXT_LEAP_EVIDENCE_PLAN.md) — **truthfulness of evidence** (`Evidence`)  
> - [`OPS_STARVATION_CLEANUP_AND_MARKET_FOCUS_PLAN.md`](OPS_STARVATION_CLEANUP_AND_MARKET_FOCUS_PLAN.md) — **truthfulness of execution** / ARMF (`OI-OPS1`)  
> - [`SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md`](SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md) — **truthfulness of reasoning** (`OI-SI0`)  

---

## 0. Why this order (locked)

```text
Evidence Plan
        │
        ▼
Research produces correct facts
        │
        ▼
ARMF (A → B → C)
        │
Research actually gets CPU / LLM / ticks
        │
        ▼
Sector Intelligence (SI.1 → SI.6)
        │
Research asks the correct questions
```

| Stream | Responsibility | Why not reorder |
|--------|----------------|-----------------|
| **Evidence** | Facts & provenance | Already mid-implementation; stopping halfway leaves IRA inconsistent |
| **ARMF** | Observable + fair execution | Can land incrementally; unblocks all later research volume |
| **Sector Intelligence** | Analytical lens / questions | Creates *more* research work — without ARMF that work waits |

**Do not** start Sector Intelligence before ARMF Phase A–C.  
**Do not** interrupt Evidence to begin ARMF mid-sprint — finish Evidence, then ARMF immediately.

---

## 1. Sprint plan (locked)

### Sprint 1 — Finish Evidence Plan (do not interrupt)

**Goal:** Freeze a stable evidence foundation for IRA.

Complete / freeze:

- Operator snapshots  
- Incremental refresh  
- Evidence hierarchy  
- Evidence sufficiency  
- Valuation path (method honesty)  
- Claim → Evidence links  

**Exit:** Evidence Plan marked **shipped / frozen**; no new SI or ARMF C work until this exit.

---

### Sprint 2 — ARMF Phase A + Phase B (immediately after Sprint 1)

**Goal:** Make Atlas **observable** and remove zombie noise — low risk, high leverage.

| Phase | Delivers |
|-------|----------|
| **A** | Why didn’t Market tick? Host Guard vs budget vs LLM vs disk? Glossary, filters, banners, degraded service name, program health v0 |
| **B** | Cleanup toolkit — retire `hello_watcher` / dead no_progress with dry-run |

**Exit:** Ops answers detective questions without archaeology; starved list not dominated by zombies.

---

### Sprint 3 — ARMF Phase C (real behavior change)

**Goal:** Capacity policy above Host Guard.

Implement:

- Program capacity shares + **borrowing**  
- Resource profiles + work classes  
- **LLM / inference / embedding slots**  
- At-risk detection, deadlines, aging  
- Program health (mature)  
- Preferred ticks **4** / hard **5** (this host)  
- **Research Progress** as scheduler input (see §2)  
- **Research Velocity** KPI on Ops (see §2)  

Host Guard remains final veto.

**Exit:** Market / Eng / Personal cannot be totally starved; idle capacity is borrowed; non-LLM realtime not blindly blocked by heavy LLM when split is possible.

---

### Sprint 4 — Sector Intelligence SI.1 → SI.6

**Only after** Evidence frozen **and** ARMF A–C landed.

| Stage | Work |
|-------|------|
| **SI.1** | Business Identity Engine (mandatory before MVR) |
| **SI.2** | Sector packs v1 (India) |
| **SI.3** | Research Strategy Generator + question mix |
| **SI.4** | Valuation path branching on gaps |
| **SI.5** | Distinctiveness on awareness |
| **SI.6** | Comparative engine (later) |

**Exit:** Hospital vs capital-goods dossiers ask different questions; “sector unknown” rare/explicit.

---

## 2. Final ARMF additions (locked into OI-OPS1)

### 2.1 Research Progress as a schedulable input

Dossier / company research coverage (or section progress) feeds the scheduler:

```text
Company A   95% complete  →  low marginal value of more ticks
Company B   12% complete  →  high attention
```

Avoid spending hours moving 95% → 96% while another name sits at 10%.

Phase C must expose a progress signal (IRA coverage / MVR remaining / strategy checklist) into Candidate Selector scoring.

### 2.2 Research Velocity KPI

Ops (and program health) must show knowledge produced, not only CPU/workers/ticks:

| Program | Example KPI |
|---------|-------------|
| Market | Dossiers advanced / day; news claims ingested; thesis revisits |
| Engineering | Repos observed / mentor lessons |
| Personal | Facts confirmed / drafts |

**Primary question:** *Did Atlas produce more knowledge today?*

### 2.3 Goal → Objectives → Mission → Worker (Phase F, design locked)

```text
Program Goal          e.g. Research NIFTY50 this week
        ↓
Objectives            5 new companies, 20 news updates, 2 thesis revisions
        ↓
Missions              admitted work units
        ↓
Workers               ticks that satisfy objectives
```

Ship after Phase C is stable (existing ARMF Phase F). Do not block Sprint 3 on full Goals OS.

---

## 3. Separation that must stay clean

| Stream | Truthfulness of… |
|--------|------------------|
| Evidence Plan | **Evidence** |
| ARMF | **Execution** |
| Sector Intelligence | **Reasoning / questions** |

Evolve each without tangling the others.

---

## 4. Explicit non-goals for this roadmap

- Starting SI before ARMF A–C  
- Pausing Evidence mid-flight to build ARMF  
- Raising tick concurrency to chase 28 cores  
- Weakening Host Guard  
- Mixing SI into the Evidence sprint  

---

## 5. Open items

| ID | Role in this roadmap |
|----|----------------------|
| Evidence (IRA Next Leap) | Sprint 1 — finish & freeze |
| `OI-OPS1` | Sprints 2–3 — ARMF A/B then C |
| `OI-SI0` | Sprint 4+ — after ARMF C |

---

## 6. Operator lock checklist

- [x] Finish Evidence first (no interrupt)  
- [x] ARMF A+B immediately after Evidence  
- [x] ARMF C before any SI implementation  
- [x] SI.1 only when evidence + scheduler are trustworthy  
- [x] Research Progress + Research Velocity added to ARMF  
- [x] Goal→Objectives hierarchy deferred to Phase F but designed now  
- [x] Three-stream separation permanent  

**Next concrete action:** operate under paper trading (leave-running). ARMF Phase D+E frozen; C10 + Phase F deferred. Evidence + ARMF A–C + SI.1–6 frozen.
