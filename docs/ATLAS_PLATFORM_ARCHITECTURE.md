# Atlas Platform Architecture

> **Status:** SETTLED (architecture) · implementation quality next · **Date:** 2026-07-24  
> **Purpose:** What Atlas *is*. Domain plans are chapters. Stop inventing new top-level concepts here — polish and implement.  
> **Audience:** architects / operators  
> **Solar-plant test:** every *platform* box must still make sense if Market → Solar Plant.

---

## 1. Verdict

Atlas is **one platform** with reusable OS layers. Market / Engineering / Personal are **Programs** (applications), not separate systems.

```
Program → Mission → Worker
```

is the operating hierarchy. Platform services sit *under* Programs; finance-specific pieces (Broker Profiles, NSE adapters) sit *inside* the Market Program.

**Architecture is largely settled.** Future work: implementation quality + filling planned OS gaps — not new top-level boxes unless they pass the solar-plant test.

---

## 2. Complete platform diagram

```
                    Atlas Platform
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
 Knowledge OS        Experience OS         Mission OS
    │                      │                      │
    ▼                      ▼                      ▼
 Memory OS          Verification OS        Planning OS
    │                      │                      │
    └──────────┬───────────┴───────────┬──────────┘
               │                       │
               ▼                       ▼
         Policy Engine          Capability Registry
               │                       │
               └───────────┬───────────┘
                           ▼
                    Intelligence Programs
    ┌──────────────────────┼──────────────────────┐
    ▼                      ▼                      ▼
 Market              Engineering            Personal
 (domain adapters)   (domain adapters)      (domain adapters)
```

Every box above the Programs line is **reusable**. Nothing there is finance-specific.

---

## 3. Hierarchy (keep)

| Level | Owns | Example |
|-------|------|---------|
| **Program** | Soft product grouping + program-level schedule | Market Intelligence |
| **Mission** | Long-lived role + config | Market Observer |
| **Worker** | Checkpointed tick | `market_observer` every 5m |

### Scheduler hierarchy (target)

```
Program Scheduler   (e.g. Program runs 24×7)
    ↓
Mission Scheduler   (e.g. News Intelligence hourly)
    ↓
Worker Tick         (e.g. every 5 minutes)
```

Today workers mostly own their own `interval_seconds`. Elevate to Program → Mission → Worker as mission count grows (`OI-PA-SCHED`).

**Shipped (SCHED.1):** `SchedulerHierarchyService` — cascade `worker_specs > mission cadence > program default`. APIs: `GET /v1/scheduler/hierarchy`, `POST /v1/scheduler/resolve`. Durable ticks remain on `scheduler.schedules`.

---

## 4. Platform OS layers

### 4.1 Core three (locked)

| OS | Role | Status |
|----|------|--------|
| **Knowledge OS** | Global findings, candidates, consolidator, graph, trust | Strong (KE + KV) |
| **Experience OS** | Observation→Decision→Outcome→Reflection→Lesson | ✅ EX.1 (`ExperienceOS` / `/v1/experience/*`) |
| **Mission OS** | Templates, workers, journals, configs, Programs | Strong (Phase A/D) |

### 4.2 Foundational services to complete / elevate

| Service | Role | Exists today? | Gap |
|---------|------|---------------|-----|
| **Verification OS** | UNVERIFIED → scored / contested; multi-dim trust | ✅ KV.0–KV.10 | Consume from Mission Context API |
| **Memory OS** | Explicit hierarchy (below) | ✅ MEM.1 | working → session → long_term; Knowledge/Experience stay separate OS |
| **Planning OS** | Goal → gather gaps → compare → risk → decide | ✅ PA.1 | Multi-step across Programs; hard Policy still OI-PA-POLICY |
| **Policy Engine** | Constraints & governance (caps, forbidden actions) | ✅ PA.2 | Soft prefer/avoid + hard forbid/limit; Decision Simulation blocks hard violations |
| **Capability Registry** | Discover readers/extractors/verifiers/tools | ✅ CAP.1 | Needs check + aliases; missions declare `MarketReader` etc. |
| **Decision Engine** | Kernel arbitration | ✅ Phase D | Keep kernel; Programs supply rules + context |
| **World Models** | Domain *structure* (not claim rows) | ✅ WM.1 | Framework + `indian_markets` + `solar_plant` stub packs |

### 4.3 Memory hierarchy (explicit)

```
Working Memory     ← today's research scratch / active tick context
    ↓
Session Memory     ← recent decisions & job workspace
    ↓
Long-term Memory   ← durable recall (existing memory service)
    ↓
Knowledge          ← consolidated findings (Knowledge OS)
Experience         ← lessons from outcomes (Experience OS)
```

Rule of thumb: scratch → working; important conclusion → Knowledge; repeated pattern → Experience.

**Shipped (MEM.1):** `MemoryOS` maps layers onto `memory.items` (`working` / `episodic`+session meta / `semantic`). APIs: `GET /v1/memory/hierarchy`, `POST /v1/memory/os/remember`, `POST /v1/memory/promote`. Mission Context includes `item_kind=memory`. Promoting into Knowledge/Experience is refused — those OS own writes.

### 4.4 Planning OS (gap)

Not the same as “reason once → Buy”.

```
Goal
  → Gather missing information
  → Compare alternatives
  → Estimate risk
  → (Policy check)
  → Decide / Act-or-Simulate
```

Useful for Market *and* Engineering *and* Personal. Research loop is an early instance; generalize as Planning OS (`OI-PA-PLAN`).

**Shipped (PA.1):** `PlanningService` (`GET/POST /v1/planning/plan`, tool `planning.plan`). Deterministic: Mission Context → gaps → alternatives → risks → soft Policy notes → recommended next (gather / simulate / research / verify). Event Research attaches `planning_action` when spawning Jobs.

### 4.5 Policy Engine (gap / elevate)

Separate from reasoning:

| Reasoning | Policy |
|-----------|--------|
| “Buy Tata looks attractive” | Max 5% position; never enter before earnings; max sector exposure; max drawdown |

Reuse across Programs (engineering: “never auto-push”; personal: “never send mail”). Build on existing Policy store; elevate to **Policy Engine** with hard/soft constraint evaluation (`OI-PA-POLICY`).

**Shipped (PA.2):** `PolicyEngine.evaluate` — soft (`prefer`/`avoid`/`trust`/`distrust`) + hard (`forbid`, `limit` with provenance caps). `POST /v1/policy/evaluate`. Decision Simulation refuses fills that hard-violate.

### 4.6 Capability Registry (invert dependencies)

```
Platform → Capability Registry → Readers / Extractors / Verifiers / Reasoners / Tools
```

Missions declare **needs** (`MarketReader`, `speech_to_text`) rather than importing concrete adapters. Aligns with P15 capability-gap honesty (`OI-PA-CAP` / roadmap §5.10).

**Shipped (CAP.1):** `check_needs` / aliases / `provider_for`; `POST /v1/capabilities/needs`, `GET /v1/capabilities/inspect`. Market Observer journals `capability_gap` when needs are missing. Built-in `MISSION_NEEDS` for Market Intelligence members.

**Shipped (OI-F5):** `CapabilityRegistry.self_report_gaps` + `GET /v1/capabilities/gaps` (+ `atlas capability-gaps`) merges catalog missing, mission need gaps, unhealthy providers, and the Decision Engine gap backlog (`GET /v1/decision/gaps`).

---

## 5. Platform vs Program (do not mix)

| Belongs on **Platform** | Belongs in **Market Program** |
|-------------------------|-------------------------------|
| Knowledge / Experience / Mission OS | Broker Profiles (Zerodha, Groww, …) |
| Verification / Memory / Planning / Policy | MarketReader adapters (NSE, BSE, Yahoo, …) |
| Capability Registry | Portfolio Ledger fee tables |
| Programs abstraction | Investment Mentor report shape |
| World Models *framework* | Indian market world-model *content* |
| Decision Engine | Strategy rules for equities |

**Solar-plant test:** replace Market with Solar Plant — Broker Profile fails (domain); Knowledge OS / Policy / Planning pass.

Market Intelligence is the **reference implementation Program**, not the source of platform vocabulary.

---

## 6. Programs (applications)

| Role | Market | Engineering | Personal |
|------|--------|-------------|---------|
| Observer | Market Observer | Repository Observer | Personal Observer |
| Domain learn | Company Intelligence | Architecture Intelligence | Personal Knowledge |
| Stream learn | News Intelligence | Technology Watch | Calendar / Mail Watch |
| Event research | Event Research | Bug Investigation | Personal Research |
| Decide / advise | Decision Simulation | Engineering Advisor | Personal Advisor |
| Book / memory | Portfolio Ledger | Engineering Memory | Personal Memory |
| Mentor | Investment Mentor | Engineering Mentor | Personal Mentor |

**Ship rule:** plan the full mission set per Program; enable gradually (stubs OK). Architecture does not change when a stub turns on.

---

## 7. Mission Context API

```
All learning paths → Knowledge + Verification + Graph + World Models
                         ↓
                  Mission Context API
                         ↓
              “Everything relevant to X”
```

Missions never depend on which extractor produced a finding.

---

## 8. Generation roadmap

| Gen | Capability | Status |
|-----|------------|--------|
| V4 | Typed knowledge extraction | ✅ |
| V5 | Verification + multi-dim trust | ✅ |
| V6 | Knowledge graph | ✅ KG.1 (derived) |
| V6.5 | World Models framework + first domain packs | ✅ WM.1 |
| V7 | Context API + Planning OS in mission loops | ✅ MCA.1 + PA.1 |
| V8 | Experience OS + Mentors → better decisions | ✅ EX.1 + MI.7 (OI-MP5 soft bias remains) |

---

## 9. Chapter index

| Chapter | Doc |
|---------|-----|
| This master | `ATLAS_PLATFORM_ARCHITECTURE.md` |
| Constitution | [`ATLAS_OS_ROADMAP.md`](ATLAS_OS_ROADMAP.md) |
| Mission philosophy | [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) |
| Media extraction | [`MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md`](MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md) |
| Verification | [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) |
| Market Program (proving ground) | [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) |
| Operator how-to | [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md) |
| Open items | [`OPEN_ITEMS.md`](OPEN_ITEMS.md) |

---

## 10. Implementation priority (not new concepts)

1. KE.2.5–2.7 — SPO quality, structured relationship preview, provenance  
2. Program UI + cognitive lifecycle (MI.1) ✅  
3. Mission Context API ✅ MCA.1 (`GET /v1/context`; Decision Simulation cites)  
4. Elevate Policy Engine + Memory hierarchy docs → code  
5. Planning OS ✅ PA.1 (`GET /v1/planning/plan`)  
6. Capability Registry enrichment ✅ CAP.1  
7. Scheduler hierarchy ✅ SCHED.1  
8. World Models framework ✅ WM.1  

Stop adding top-level OS names unless the solar-plant test forces it.
