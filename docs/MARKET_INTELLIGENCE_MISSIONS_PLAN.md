# Market Intelligence Program Plan

> **Status:** PLAN LOCKED · platform architecture settled · **Date:** 2026-07-24  
> **Trigger:** Richer paper trading → Programs of cooperating missions + shared Knowledge/Experience OS.  
> **Master:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)  
> **Parents:** [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) ·
> [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) (KV.0–KV.10 ✅) ·
> [`MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md`](MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md)  
> **Open item:** `OI-MI0` · expands **OI-MP2**

---

## 1. Verdict

**Market Intelligence is not a trading product.** It is the **reference Program** that *proves* the Atlas Platform — it must **not** dictate platform abstractions (solar-plant test: [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)).

```
Program → Mission → Worker
```

Same lifecycle as Engineering and Personal — only **domain adapters** change (MarketReader, Broker Profiles, fee tables).

```
Observe → Learn → Verify → World Model → Plan → Decide → Simulate
  → Measure → Reflect → Experience → Improve
```

(Policy constrains Decide; Capability Registry supplies readers/tools.)

All learning paths feed **one Knowledge Layer**. Missions consume via **Mission Context API** when shipped.

---

## 2. Platform vs Market Program

Platform OS layers live in the **settled** master: [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md).

This document only specifies the **Market Program** application:

```
Platform (shared)          Market Program (domain)
─────────────────          ───────────────────────
Knowledge OS               MarketReader adapters
Experience OS              Broker Profiles
Mission OS + Programs      Portfolio fee tables
Policy Engine              Interesting-event scores
Planning OS                Investment Mentor copy
Capability Registry        NSE/BSE/Yahoo/… adapters
World Models *framework*   Indian-market *model content*
Memory / Verification OS
```

### Same roles across Programs (pattern)

| Role | Market | Engineering | Personal |
|------|--------|-------------|---------|
| Observer | Market Observer | Repository Observer | Personal Observer |
| Domain learn | Company Intelligence | Architecture Intelligence | Personal Knowledge |
| Stream learn | News Intelligence | Technology Watch | Calendar / Mail Watch |
| Event research | Event Research | Bug Investigation | Personal Research |
| Decide / advise | Decision Simulation | Engineering Advisor | Personal Advisor |
| Book / memory | Portfolio Ledger | Engineering Memory | Personal Memory |
| Mentor | Investment Mentor | Engineering Mentor | Personal Mentor |

---

## 3. Live Learning → Verification (operator path)

Learning Reports correctly say **Verification: Not Executed**. That is by design (KV7): learn ≠ verify.

After a COMPLETE media.learn on `https://youtu.be/zHt5Mdr0QFk`:

**Chat / Job (recommended):**

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk
```

With budget-capped web corroboration:

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk with web search
```

**By asset** (from Learning Report Observations):

```text
Verify claims for asset_id 0b143356-d437-4e30-863f-1f1ec2b56bdd
```

**Continuous:** instantiate mission template `knowledge_verification` with `source_url` or `asset_id` filter.

**What to expect:** before/after confidence, optional `overall_trust` (KV10), contested if contradictions, still INSUFFICIENT/LOW if only YouTube L2 evidence (Q2 — single source ≠ HIGH).

---

## 4. KE quality ship-along (from 2026-07-24 re-review)

Latest COMPLETE report scored **~8.8/10** (was ~7.8). Claim linking **12/12**, orphans **0**, places/aliases fixed. **Weakest subsystem: relationships** (still sentence fragments).

These ship **with** Market Intelligence / Platform work (not a separate forever backlog):

| ID | Work | Why |
|----|------|-----|
| **KE.2.5** | True SPO only; reject clause fragments; lexicon-anchored subjects/objects | Graph edges, not prose |
| **KE.2.6** | Learning Report “Top Relationships” as Subject / Predicate / Object (+ optional extraction heuristic — **not** verification confidence) | Operator can judge SPO quality |
| **KE.2.7** | Ensure provenance stored on every candidate: `asset_id`, chunk/char offsets, speaker, timestamp, `extractor_version` (hide in UI if noisy) | Later verify + audit |
| **KG.1** | Knowledge graph construction over Claim↔Concept↔Entity↔SPO | V6 |
| **MCA.1** | Mission Context API — shared retrieval for all Programs | V7 |
| **WM.1** | World Models layer (market structure ≠ claim store) | V6.5 |
| **EX.1** | Experience OS as first-class (Observation→…→Lesson) | V8 / OI-MP1 |

**Do not invent Facts at extract** — `facts=0` on interviews remains correct until verification promotes trust.

Detail + checklist: [`MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md`](MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md) § “Second live review”.

---

## 5. Mission catalog (seven planned; one Program shipped)

| # | Mission | Kind | Cadence | Output |
|---|---------|------|---------|--------|
| **M1** | Market Observer | monitoring | continuous | Bars, move/events |
| **M2** | Company Intelligence | learning | daily/weekly | Filings / ratios (official first) |
| **M3** | News Intelligence | learning | hourly | News claims → verify |
| **M4** | Event Research | research | on trigger | Why-did-it-move Jobs |
| **M5** | Decision Simulation | simulation | continuous | Buy/Sell/Hold/Watch + journal |
| **M6** | Portfolio Ledger | simulation (book) | with fills | Fee/tax-aware sim ledger |
| **M7** | Investment Mentor | maintenance | weekly | Lessons + recommendations |

**Ship rule (Q1 locked):** *Plan seven. Ship one Program.* Templates + Program object exist; missions may be **disabled stubs** until capable. Architecture does not churn when capabilities appear.

Compat: old `paper_trading` remains a façade that can join the Program until deprecated.

---

## 6. Frozen decisions

| # | Decision |
|---|----------|
| **MI1** | P10 — simulation only; never broker login |
| **MI2** | One Knowledge OS (P11/P12) |
| **MI3** | Reuse VerificationEngine — no finance verifier |
| **MI4** | Official exchange + filings preferred; third-party only if ToS/API-compliant; normalize inward |
| **MI5** | No indiscriminate scraping |
| **MI6** | Event research = Job spawn, not hidden Decision side-effect |
| **MI7** | Fee/tax via **Broker Profile** — **Market Program config**, not a platform OS |
| **MI8** | Decision Engine = kernel service (platform) |
| **MI9** | UI: Program cockpit + cognitive lifecycle (platform UX) |
| **MI10** | Experience journal shape mandatory (OI-MP1) |
| **MI11** | **Programs** first-class grouping (platform) |
| **MI12** | **MarketReader** adapters in Market Program; Capability Registry advertises them |
| **MI13** | Event research is **intelligence-scored** (Market Program) |
| **MI14** | World Models **framework** = platform; market content = Program pack |
| **MI15** | Experience OS = platform; Mentor writes into it |
| **MI16** | Missions consume knowledge via **Mission Context API** (platform) |
| **MI17** | Reference Program ≠ platform source of truth (solar-plant test) |

---

## 7. Locked answers (operator 2026-07-24)

| Q | Answer |
|---|--------|
| **Q1** | Neither 3-only nor 7-all-at-once. **Plan 7 / ship 1 Program** (stubs OK). |
| **Q2** | Ledger **eventually separate (M6)** — reusable across investment / energy / crypto / carbon. May start as library behind M5, then promote. |
| **Q3** | **Never hardcode.** `MarketReader` + adapters (NSE, BSE, Yahoo, Polygon, AlphaVantage, CSV replay). |
| **Q4** | Configurable **Broker Profiles** (Zerodha, Groww, Angel, Paper Demo, Custom). |
| **Q5** | **Intelligence-driven** Interesting Events (volume, earnings, CEO, circuit, 52w, split, dividend, options, insider…) with score → spawn Job if worth it. Opt-in until tuned. |
| **Q6** | **Programs** console section (Market / Engineering / Personal). |

---

## 8. Interesting Events (M1 → M4)

Not merely `|Δprice| > 5%`.

Examples (scored, configurable): huge volume, earnings, CEO resigned, circuit breaker, 52-week high/low, split, dividend, unusual options, large insider trade.

```
Interesting Event (score ≥ threshold)
    → enqueue Research Job
    → extract claims → verify → update Knowledge
```

Operator does not have to ask.

---

## 9. World Models (domain pack on platform framework)

Platform owns the World Model **framework**. Market Program ships an **Indian markets pack** (exchanges, sectors, hours, settlement, corporate actions). Solar Program would ship irradiance/MPPT content — same framework.

---

## 10. Experience OS

```
Observation → Decision → Outcome → Reflection → Lesson → Experience
Knowledge + Experience → Reasoning
```

Mentor (M7) writes Experiences that bias future Decision context (OI-MP5).

---

## 11. Ship order

```
MI.0   Plan locked + platform master doc              ✅
KE.2.5–2.7  SPO + report structure + provenance       ✅
MI.1   Program UI + cognitive lifecycle + Context API spike ✅
MI.2   Materialize 7 templates (stubs OK); split paper_trading façade ✅
MI.3   MarketReader adapters + OI-D1 live when keys exist ✅
MI.4   News + Interesting-Event → research Jobs + verify
MI.5   Company / filings ingest (compliant)
MI.6   Promote Portfolio Ledger + Broker Profiles
MI.7   Investment Mentor + Experience OS deepening
WM.1   World Models (markets first)
KG.1   Knowledge graph (Claim↔Concept↔Entity↔SPO)
MCA.1  Mission Context API (all Programs)
```

---

## 12. Success criteria

1. Start **Market Intelligence Program** without raw JSON for happy path  
2. See Program members (including disabled stubs) + lifecycle stages  
3. After media.learn, **verify** claims and see trust / contested without DB  
4. Interesting Event can spawn research (when enabled)  
5. Decision Simulation cites context via shared API (when MCA.1 lands)  
6. Mentor weekly lesson changes future advice  
7. **No** broker credentials anywhere  

---

## 13. Checklist

- [x] Draft + operator Q1–Q6 locked  
- [x] Platform master doc  
- [x] KE.2.5–2.7 + graph/API/models noted as ship-along  
- [x] Verification how-to for operators (§3)  
- [x] Platform vs Market Program split (Broker Profiles domain-only)  
- [x] KE.2.5 SPO hardening + structured relationship preview  
- [x] KE.2.7 provenance completeness  
- [x] MI.1 Program UI  
- [x] MI.2 templates + façade  
- [x] MI.3 MarketReader adapters (asset_replay / yahoo opt-in / keyed skeletons)  
