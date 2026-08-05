# Career Intelligence Plan

> **Status:** PLAN LOCKED · **Date:** 2026-08-03  
> **Locked by:** Operator review (architecture 9.8 / philosophy 10 — Career Research layer + Company entity reuse required).  
> **Trigger:** Operator request to improve LinkedIn + job search without making LinkedIn browser automation Atlas’s primary design.  
> **Parents:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) · [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) · [`ATLAS_OS_ROADMAP.md`](ATLAS_OS_ROADMAP.md) (P10/P14) · [`PHASE_C_PLAN.md`](PHASE_C_PLAN.md) C.7–C.8 · [`PHASE_D_PLAN.md`](PHASE_D_PLAN.md) D.8 · [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) (pattern to mirror) · ARMF / Host Respect  
> **Open item:** `OI-CI0`  
> **Program home (PERMANENTLY LOCKED):** Personal Intelligence (`personal_intelligence`) — Career is a **domain facet inside Personal**, never a fourth top-level Program.

---

## 0. Permanent locks (constitution for this plan)

| Lock | Decision |
|------|----------|
| **L-PI** | Career lives under Personal Intelligence forever: Health · Finance · **Career** · Learning · Relationships as Personal facets — **not** Personal / Engineering / Market / Career as peer Programs. |
| **L-SENSOR** | Browser (and every board adapter) is a **sensor**: produces Assets → Evidence → Knowledge → Events — **never Decisions**. Atlas-wide philosophy, not Career-only. |
| **L-SPLIT** | Career Observer **discovers only**. Career Research **deepens**. Career Advisor **decides/recommends**. Never fuse observe→recommend in one worker. |
| **L-COMPANY** | One **Company** entity shared across Market, Engineering, Personal, and Career — never four parallel “Google” records. |
| **L-P14** | `can_write_linkedin=False`; `can_apply=False` through CI.4; CI.5 only behind OI-D4 + per-action approval. |
| **L-EXPORT** | Export-first. CI.1c (Atlas Career Browser) deferred until CI.1–CI.2 are useful. No Firefox hijacking; no LinkedIn passwords in `.env`. |
| **L-ARMF** | Career Observer / Research are **BATCH**, low-priority under ARMF / Host Guard — never starve Market/interactive work. |

---

## 1. Verdict

**Do not build “LinkedIn automation.” Build Career Intelligence.**

```
Sensors (LinkedIn export, Naukri, Greenhouse, company careers, GitHub Careers, …)
        ↓
   Career Knowledge Graph  (+ shared Company entities)
        ↓
   Career Research  (companies, culture, salary, engineering quality, stability)
        ↓
   Evidence + verify
        ↓
   Reasoning (Opportunity Score, skill gaps, strategy)
        ↓
   Career Advisor → recommendations / watchlist / materials / learning plans
        ↓
   Operator acts
        ↓
   Career Memory + Interview Intelligence → Experience OS → Improve
```

Same spine as Market / Investment Intelligence:

```
Observe → Research → Verify → Decide → Learn
```

| Level | Name | Atlas stance |
|-------|------|--------------|
| **L1** | Autonomous LinkedIn browser agent | **Not primary.** Thin optional sensor later — never the product. |
| **L2** | Human-assisted export / Atlas Career Browser | **CI.1 first** (export); **CI.1c later** (dedicated browser profile). |
| **L3** | Career Intelligence Agent | **CI.2 → CI.2.5 → CI.3 → CI.4** — KG + Research + multi-source + Experience. |

---

## 2. What already exists (reuse)

| Surface | Reuse as |
|---------|----------|
| Personal Observer (`owner_knowledge`) | You → `personal.facts` + timeline seed |
| Career Advisor (`job_hunting` / JobWatcher) | Evolve into **Advisor only** (stop being the sole ingest path) |
| Personal Mentor | Weekly strategy; consume Career Experience |
| `job_postings` reader + decision rule + jobs panel | Feed normalization + early ranking |
| LinkedIn coach + draft + learn-cv | Profile tips / clipboard materials |
| Browser (read-only) | Sensor substrate for CI.1b / CI.1c |
| Company Intelligence (Market) | **Shared company entity** Career Research deepens — does not fork |
| Experience OS + `outcome_feedback` | Career Memory / Interview Intelligence |

**Gaps this locked plan closes:** empty Advisor sources; observe+decide fused; no CKG / career domain; no Career Research layer; no market-demand analytics; no interview WHY loop; weak preference→Experience learning; no Learning↔Career bridge; company identity not shared.

---

## 3. Target architecture (Personal facet)

```
Personal Intelligence
│
├── Personal Observer          → profile, CV, archive, skills, timeline
├── Career Observer   (NEW)    → sensors → raw postings / profile snapshots → CKG (discover only)
├── Career Research   (NEW)    → companies + roles deepened (shared Company entity)
├── Career Advisor    (evolved)→ Opportunity Score, briefs, watchlist, materials, learning plans
└── Personal Mentor            → weekly judgment from Career Experience + goals
```

**Advisor never reads raw sensor dumps as truth.** It reads **Career Research outputs + CKG** (as Investment Advisor reads researched companies, not tick tapes alone).

### 3.1 Sensors → Assets → Knowledge (Atlas-wide)

Every browser / board adapter must emit:

| Output | Store |
|--------|-------|
| Raw capture | Asset (`job_postings`, `linkedin_profile`, `company_page`, …) |
| Claims | Candidates → findings (`domain=career` or company facts) |
| Provenance | Evidence / supporting refs |
| Lifecycle | Events (first_seen, closed, salary_changed) |

**Not:** immediate Decision Engine calls from the browser tool.

### 3.2 Shared Company entity (L-COMPANY)

```
Company(canonical_id)
    ├── Market Intelligence   (filings, sector, valuation signals)
    ├── Engineering Intelligence (tech stack, open-source, architecture — when known)
    ├── Career Research       (culture evidence, hiring, salary bands, learning opportunity)
    └── Personal / Career     (operator interest, applications, interviews)
```

Career must **resolve or create** the same company identity Market uses — never `employer_name` string silos as the long-term key.

---

## 4. Career Knowledge Graph (CKG)

### 4.1 Domain

- Add `career` to Knowledge `ALL_DOMAINS` + Personal retrieval maps.
- Jobs / market signals → findings `domain=career`.
- Company facts stay on the **shared company** identity (Market/Career co-own; no duplicate company graphs).

### 4.2 Entities

| Entity | Role |
|--------|------|
| **Job** | Finding / opportunity (`career.job.1`) |
| **Company** | Shared platform entity |
| **Recruiter / Hiring manager** | Optional person entities linked to company + job |
| **Skill** | Normalized skill entity (demand stats live here) |
| **Application / Interview** | Outcomes → Experience OS (not only job metadata) |

### 4.3 Job payload (`career.job.1`)

`company_id`, `role`, `salary`, `skills[]`, `location`, `remote`, `url`, `source`, `description_hash`, `status`, `first_seen`, `last_seen`, `identity_key`, optional recruiter/tech/culture tags.

Operator overlay (Career Memory): `operator_status` ∈ `none|saved|ignored|applied|interviewing|rejected|offer|accepted` + **why** notes.

### 4.4 Career Market (not only jobs) — Missing 1

CKG must support **market aggregates**, e.g.:

- Skill demand: Python 81%, Docker 72%, K8s 48%, LLMs 22%, Power Systems 4% (over rolling window of observed postings).
- MoM deltas: “Python demand +12% this month.”
- Salary band distributions by role/location/sector.

Stored as `career.market_signal` findings (time-bounded), not recomputed only in the UI.

### 4.5 Opportunity Score — Missing 5

Replace thin fit-only ranking with:

```
OpportunityScore =
  Fit
+ Salary growth potential
+ Learning value
+ Career impact
+ Location fit
+ Company stability  (from Career Research + Market)
+ Operator interest  (Career Memory)
+ Future network value
```

Weights are config + learned soft bias (CI.4); always explainable (P9).

### 4.6 Career Timeline — Missing 4

First-class **Career Timeline** under Personal (extends `personal.facts` timeline / professional):

```
2017 Electrical → Research → Peak Energy → Atlas → AI → Patent → Principal track → Goals
```

Advisor recommendations must be **trajectory-aware**, not isolated posting matches. Goals are operator-confirmed facts.

---

## 5. Career Research Mission (CI.2.5) — NEW LAYER

Exact analogue of Investment / Company research.

**Goal:** Deepen companies (and critical roles), not only list jobs.

```
Career Observer (jobs + employer names)
        ↓
Career Research
        ↓
  Find / resolve Company
  Culture evidence (appropriately sourced)
  Engineering quality signals
  Salary / leveling
  Leadership / products
  Stability
  Learning opportunities
        ↓
  Research pack / findings on shared Company
        ↓
Career Advisor (Opportunity Score uses research)
```

| ID | Work |
|----|------|
| CI.2.5.1 | Template `career_research` + worker (BATCH, never_stops or queue-driven) |
| CI.2.5.2 | Input: company_ids / tickers / names from CKG jobs lacking research freshness |
| CI.2.5.3 | Reuse Company Intelligence readers/assets where they exist; add career-specific claim types |
| CI.2.5.4 | Output: verified/candidate company findings + “research sufficiency” for Advisor |
| CI.2.5.5 | CapabilityGap when Glassdoor-like sources are ToS-blocked — honest, no silent scrape |

**Career Observer must not recommend. Career Research must not apply. Career Advisor must not scrape.**

---

## 6. Interview Intelligence & Career Memory — Missing 3 & 7

### 6.1 Career Memory

Every operator action on an opportunity:

| Status | Learned signal |
|--------|----------------|
| Ignored | Low interest / mismatch — capture optional WHY |
| Saved | Positive interest |
| Applied | Commitment |
| Interviewing | Process stage |
| Rejected | **Require WHY** (prompt): system design / Python / communication / salary / experience / culture / other |
| Offer / Accepted | Strong positive outcome |

WHY is mandatory on reject (and encouraged on ignore) → Experience OS `domain=career`.

### 6.2 Interview Intelligence

After N interviews, Atlas aggregates failure/success modes:

- Missing System Design, weak Python, communication, salary, experience gaps  
- Feeds skill_gap findings + **Learning Plans** (Missing 6) + Mentor notes  

This is **Experience OS → Career Experience → Preferences → Behavior → Outcome → Learning** (CI.4), not a boolean “saved job” flag.

---

## 7. Learning Plans — Missing 6

When top Opportunity Score jobs repeatedly require skills you lack:

```
Career Advisor / Research
        ↓
Learning Program (Personal Learning facet)
        ↓
  Skill modules → projects → certification → resume/LinkedIn draft update tips
```

Career and Learning **feed each other**. No silent LinkedIn edits — drafts + Confirm facts only.

---

## 8. Phased delivery (LOCKED ORDER)

```
CI.0  Hygiene
  ↓
CI.1  Career Observer (export-first discover → CKG)
  ↓
CI.2  Career Knowledge Graph depth (+ Career Market signals, Timeline, Opportunity Score v1)
  ↓
CI.2.5 Career Research Layer   ← NEW (Observe → Research → Decide)
  ↓
CI.3  Multi-source adapters (boards + major company career sites)
  ↓
CI.4  Experience learning (Career Memory, Interview Intelligence, preference soft-bias)
  ↓
CI.5  Gated automation (OI-D4) — non-LinkedIn forms only when explicitly enabled
```

**CI.1c** (Atlas Career Browser assist) remains **optional**, scheduled **after CI.2** usefulness is proven — not on the critical path above. Still before or parallel to CI.3 if export coverage is insufficient.

### CI.0 — Hygiene · **IN PROGRESS / shipping**

| ID | Work | Status |
|----|------|--------|
| CI.0.1 | Strip hash-noise skills from drafts + ranking | ✅ `atlas/personal/skill_hygiene.py` |
| CI.0.2 | Wire ≥1 `job_postings` source / sample fixture | ✅ `POST /v1/personal/career/import-feed` + sample JSON |
| CI.0.3 | Honor `max_recommendations` in JobWatcher | ✅ fan-out notify |
| CI.0.4 | Career tab share LinkedIn export + jobs JSON | ✅ Console Career panel |
| CI.0.5 | Operator guide + LinkedIn export unpacker (ready for 24h download) | ✅ `linkedin_export.py` + ingest-export API |

### CI.1 — Career Observer

| ID | Work | Status |
|----|------|--------|
| CI.1.1 | LinkedIn export ingest → profile snapshot asset + coach | ✅ `ingest_linkedin_export` + `linkedin_profile` asset |
| CI.1.2 | `career_observer` template/worker: feeds → candidates `domain=career` (**no recommend**) | ✅ worker + BATCH profile |
| CI.1.3 | JobWatcher Advisor-only + Career Memory company filter | ✅ `use_career_watchlist` |
| CI.1.4 | Watchlist + operator_status API | ✅ `GET\|POST /v1/personal/career/watchlist` |
| CI.1.5 | Morning brief endpoint | ✅ `GET /v1/personal/career/brief` |
| CI.1.ARMF | `service_class=BATCH`, low arbiter priority | ✅ `career_observer` resources |

**Operator ingest (one step):** when ready, paste export path in Career → **Ingest export**, or:

```bash
curl -X POST "$ATLAS/v1/personal/linkedin/ingest-export" \
  -H "content-type: application/json" \
  -d '{"path":"/home/jagd/Downloads/Basic_LinkedInDataExport_08-03-2026.zip"}'
```

That single call coaches + registers a profile snapshot + **creates/updates Career Observer** with the path (and tries to wire Advisor to `linkedin_export_jobs`). No separate step 2.

### CI.1c — Atlas Career Browser (deferred)

Operator-launched profile / CDP; allowlisted nav/read; deny submit/edit/message; no system Firefox hijack; no password store.

### CI.2 — CKG depth

| ID | Work | Status |
|----|------|--------|
| CI.2.1 | `career` domain + coverage | ✅ `ALL_DOMAINS` + personal retrieval |
| CI.2.2 | Job dedup / supersession | ✅ `atlas/career/ckg.py` |
| CI.2.3 | **Career Market** aggregates | ✅ `skill_demand` + `GET /v1/personal/career/market` |
| CI.2.4 | **Opportunity Score v1** | ✅ explainable components in Advisor |
| CI.2.5 | **Career Timeline** + goals | ✅ `GET /v1/personal/career/timeline` |
| CI.2.6 | Skill-gap findings | ✅ `GET /v1/personal/career/gaps` |
| CI.2.7 | Shared **company_id** resolution | ✅ `company_id_for` / `resolve_company` |

### CI.2.5 — Career Research

| ID | Work | Status |
|----|------|--------|
| CI.2.5.1 | Template `career_research` + worker (BATCH) | ✅ |
| CI.2.5.2 | Input company_ids / names / watchlist | ✅ |
| CI.2.5.3 | Reuse Company Intelligence where present | ✅ resolve + seed facts |
| CI.2.5.4 | Research pack + sufficiency | ✅ |
| CI.2.5.5 | CapabilityGap for blocked sources | ✅ boards + research honesty |

### CI.3 — Multi-source adapters

| ID | Work | Status |
|----|------|--------|
| CI.3.1 | `JobBoardAdapter.discover(CareerQuery)` | ✅ `atlas/career/boards.py` |
| CI.3.2 | Fixture / Greenhouse / Lever seeds | ✅ hermetic |
| CI.3.3 | Indeed / Naukri / Wellfound CapabilityGap | ✅ honest blocks |
| CI.3.4 | `POST /v1/personal/career/discover` | ✅ |

### CI.4 — Experience learning

| ID | Work | Status |
|----|------|--------|
| CI.4.1 | Career Memory WHY (watchlist statuses) | ✅ CI.1.4 + brief |
| CI.4.2 | Interview Intelligence aggregates | ✅ |
| CI.4.3 | Soft bias via Opportunity interest/stability | ✅ score components |
| CI.4.4 | Learning Plans from gaps | ✅ |
| CI.4.5 | Daily brief includes market + lessons | ✅ enhanced brief |

### CI.5 — Gated actions

| ID | Work | Status |
|----|------|--------|
| CI.5.1 | Gated non-LinkedIn apply intent API | ✅ `POST /v1/personal/career/gated-apply` |
| CI.5.2 | LinkedIn Easy Apply always CapabilityGap | ✅ |
| CI.5.3 | Live form submit still disabled | ✅ intent_recorded only |

---

## 9. Mission / worker map (target)

| Member | Discovers | Researches | Decides |
|--------|-----------|------------|---------|
| Personal Observer | You | — | — |
| **Career Observer** | Jobs + profile snapshots | — | **Never** |
| **Career Research** | — | Companies / roles | **Never** |
| **Career Advisor** | — | Consumes research | Recommend / watchlist / materials / learning plans |
| Personal Mentor | — | — | Strategic advice from Experience |

---

## 10. Lock checklist (APPROVED 2026-08-03)

1. **[x]** Plan status → **PLAN LOCKED**.  
2. **[x]** Start **CI.0 → CI.1 → CI.2 → CI.2.5 → CI.3 → CI.4 → CI.5** (Career Research before broad adapters).  
3. **[x]** Defer **CI.1c** until export + CKG are useful.  
4. **[x]** Career permanently under **Personal Intelligence** (L-PI).  
5. **[x]** Apply / LinkedIn-write out of scope for CI.0–CI.4.  
6. **[x]** Shared Company entity across Market / Engineering / Personal / Career (L-COMPANY).  
7. **[x]** Browser = sensor Atlas-wide (L-SENSOR).  
8. **[ ]** Operator supplies LinkedIn export via **one** Career ingest call *(ready on disk; self-ingest when you choose — wires Observer automatically)*.

---

## 11. Acceptance vision (end of CI.3 + CI.2.5)

Operator asks:

> Find the five best R&D roles in renewable energy and AI that fit my trajectory, explain Opportunity Score, skill gaps, draft materials, research those companies, and monitor until closed.

Atlas: CareerQuery → Observer sensors → CKG + Career Market → Career Research on companies → Advisor top 5 with evidence → Learning Plan if gaps → Memory of what you do next → never applies/edits LinkedIn.

---

## 12. Host / ARMF

Career Observer and Career Research: **BATCH**, conservative concurrency, defer under RAM/load pressure, one assist browser session max. Host stability > career throughput.

---

## 13. Open item

| ID | Status | Item |
|----|--------|------|
| OI-CI0 | 🔴 open | Execute locked plan CI.0→… ; close slices as shipped |

---

*PLAN LOCKED 2026-08-03. Next implementation slice: **CI.0**.*
