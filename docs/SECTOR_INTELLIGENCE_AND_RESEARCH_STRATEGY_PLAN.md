# Sector Intelligence & Research Strategy — Design Plan

> **Status:** 🟢 **SI.6 FROZEN** (2026-07-28) — Opportunity Comparison (Why A vs B) · Sprint 4 complete for SI v1+compare  
> **Do not implement inside** [`IRA_NEXT_LEAP_EVIDENCE_PLAN.md`](IRA_NEXT_LEAP_EVIDENCE_PLAN.md) — Evidence Plan stays **correctness of evidence**; this plan is **correctness of questions / analytical lens**.  
> **Parents:** [`INVESTING_RESEARCH_AGENT_PLAN.md`](INVESTING_RESEARCH_AGENT_PLAN.md) ·
> [`IRA_NEXT_LEAP_EVIDENCE_PLAN.md`](IRA_NEXT_LEAP_EVIDENCE_PLAN.md) ·
> [`INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md`](INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md)  
> **Open item:** `OI-SI0`  
> **Downstream activation (🔒 LQ.1 ✅):** [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) — sector packs lead the **live** research question path (Apollo ≠ MTAR)  
> **Master sprint order:** [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md)  
> **Horizon:** permanent capability for 5–10 year differentiating research — not a patch for today’s Apollo/MTAR similarity

---

## 0. Locked permanent rule

**Atlas must never start due diligence until it first answers:**

> *What kind of business is this, and how should businesses of this type be analyzed?*

That single rule implies, over time:

- sector-specific KPIs  
- sector-specific risks  
- sector-specific valuation methods  
- sector-specific research questions  
- sector-specific thesis templates  

…while **keeping** existing IRA / MVR / awareness / evidence hierarchy / valuation engine / ThesisOutcome / learning loop unchanged in shape — we **insert intelligence before research starts**.

---

## 1. Problem (correctness, not completeness)

### What looks wrong

Apollo and MTAR (and similar pairs) produce dossiers that **feel interchangeable**: same universal questions, same “missing FCF / PE / shares” tone, weak sector story.

### The tempting wrong diagnosis

> “Both are missing FCF / PE / etc.”

Missing data is real. It is **not** why the outputs feel the same.

### The real diagnosis

Atlas is answering the **wrong question first**.

| Current pipeline (too early) | Human analyst pipeline |
|------------------------------|------------------------|
| Company → Generic DD template → Report | Company → **Business classification** → **Industry mental model** → **Sector DD** → Company research → Thesis |

Atlas is missing the **middle layer**: identity → lens → strategy → then evidence/MVR.

---

## 2. Root causes (locked analysis)

| # | Root cause | Effect |
|---|------------|--------|
| **RC1** | **Business Identity too weak** (e.g. Sector = Unknown) | Everything after becomes generic. Asking “can management allocate capital?” before knowing “hospital chain / occupancy-driven” is backwards. |
| **RC2** | **Universal questions dominate** | Trust / debt / FCF / valuation asked for every name. Pros spend most time on **sector-specific** questions (occupancy, ARPOB, order book, …). Universal should be ~**20–30%**; sector-specific should dominate. |
| **RC3** | **No Research Strategy** | Same workflow for every company. Need: detect type → select strategy → load sector pack → generate questions → then MVR. |
| **RC4** | **One confidence pipeline** | Business identity, sector membership, ratios, and thesis should **not** share one confidence knob. Different knowledge types, different sources. |
| **RC5** | **No “what makes this company special”** | Before valuation: why does it exist, competitive position, what creates value (Apollo network vs Infosys services vs MTAR precision). |
| **RC6** | **Wrong research order** | FCF/DCF too early. Order: Business → Industry → Economics → Management → Growth → Financials → Valuation. |
| **RC7** | **Missing evidence doesn’t change path** | “Need FCF” as warning only. Should branch: without FCF → DCF impossible → prefer multiples path (etc.). |
| **RC8** | **No comparative reasoning** | Single-name analysis. Later: “Why MTAR instead of Apollo?” — separate engine, not in SI v1 scope. |

---

## 3. Insertion architecture (nothing below is replaced)

```text
                Company
                    │
                    ▼
        Business Identity Engine          ← NEW (mandatory before MVR)
                    │
                    ▼
      Sector Intelligence Pack            ← NEW (KPIs, risks, questions, valuation lenses)
                    │
                    ▼
     Research Strategy Generator          ← NEW (path + question mix + valuation path)
                    │
                    ▼
             Universal MVR                ← EXISTING (shrunk to ~20–30% of questions)
                    │
                    ▼
       Sector-specific Research           ← NEW questions into existing IRA sections
                    │
                    ▼
             Investment Thesis            ← EXISTING
                    │
                    ▼
         Decision / Score / Sim / Learn   ← EXISTING (IIP / IRA / Thesis Tracker)
```

**MVR philosophy shift (locked intent):**

| Today (too gameable) | Target |
|----------------------|--------|
| MVR ≈ checklist completed → Research Ready | MVR ≈ **Business understanding** + **Evidence sufficiency** + **Valuation path exists** |

MVR still unlocks decisions — but unlock means *we know what kind of business this is, we have enough evidence for the chosen path, and a valuation method is available*, not *every universal field is filled*.

---

## 4. Business Identity Engine (mandatory stage)

### 4.1 Must answer before MVR

| Field | Example (Apollo) |
|-------|------------------|
| Business type | Hospital chain / healthcare services |
| Industry / sector labels | Healthcare Services (not Unknown) |
| Capital intensity | Capital-heavy (beds, facilities) |
| Key drivers | Occupancy, ARPOB, bed additions, mix |
| Revenue model sketch | Patient services + hospitals network |
| Distinctiveness seed | Scale / network density (hypothesis, not invention) |

### 4.2 Confidence separation (RC4)

| Knowledge type | Confidence source |
|----------------|-------------------|
| Business identity | Filing / company profile / operator classification |
| Sector membership | High once classified (or CapabilityGap if unknown) |
| Financial ratios | Evidence-dependent (Evidence Plan) |
| Thesis | Depends on identity + sector lens + evidence |

**Never** let “sector unknown” silently proceed into full generic MVR as if identity were solved.

### 4.3 Honesty

- If identity cannot be established → **CapabilityGap / blocked research strategy**, not fake “Healthcare?” guesses.  
- Operator may set/confirm identity (high leverage).  
- MKG / IIP themes may *suggest* identity; they do not invent supply chains or KPIs.

---

## 5. Sector Intelligence Packs

Durable packs (versioned JSON/YAML), not prompts alone.

Each pack includes:

| Element | Purpose |
|---------|---------|
| Identity patterns | How to recognize this business type |
| Mental model | 5–15 lines: how value is created / destroyed |
| KPI set | Sector-specific metrics (occupancy, order book, …) |
| Risk set | Sector-typical falsifiers |
| Question bank | Majority of research questions |
| Valuation lenses | Which methods fit (multiples families, when DCF is silly) |
| Thesis scaffolds | What a good sector thesis must mention |
| Evidence priorities | What to fetch first for this type |

### Seed packs (v1 India cash equity)

Hospital / healthcare services · Capital goods / precision eng · IT services · Banks/NBFC (light) · Consumer · Pharma · Energy/utilities · Generic **fallback** (explicitly labeled weak)

MTAR-like precision engineering should **not** share Apollo’s hospital pack.

---

## 6. Research Strategy Generator

After identity + pack:

```text
Detect Business Type
        ↓
Select Research Strategy
        ↓
Load Sector Pack
        ↓
Generate Question Mix (~20–30% universal / ~70–80% sector)
        ↓
Choose Valuation Path(s) given available / missing evidence
        ↓
Start MVR / IRA (existing)
```

### Strategy outputs (stored on dossier)

- `business_identity`  
- `sector_pack_id` + version  
- `question_plan` (ids + priority)  
- `valuation_paths` (primary / fallback)  
- `research_order` (Business → … → Valuation)  
- `blockers` (e.g. identity unknown)

### Path branching on missing evidence (RC7)

Example:

```text
Need FCF for DCF
  → if FCF absent: mark DCF path unavailable
  → activate Multiple / sector-relative path
  → do NOT pretend DCF MoS exists
```

Evidence Plan still supplies better FCF later; Strategy decides **what to do without it**.

---

## 7. Research order (locked preference)

```text
1 Business identity & distinctiveness
2 Industry / sector model
3 Unit economics / operating drivers (sector KPIs)
4 Management & capital allocation (in sector context)
5 Growth path (sector-shaped)
6 Financial statements / ratios
7 Valuation (only after path chosen)
```

Universal MVR questions remain, but **after** identity and **weighted** appropriately.

---

## 8. Distinctiveness (“why this company exists”) — RC5

Before valuation, dossier must attempt:

| Prompt | Output field |
|--------|----------------|
| Why does this firm exist? | `distinctiveness.reason_to_exist` |
| What competitive position? | `distinctiveness.position` |
| What creates value? | `distinctiveness.value_drivers` |
| What would falsify that? | `distinctiveness.falsifiers` |

Unknown → explicit gaps, not boilerplate “quality franchise.”

(Existing IRA thesis/distinctiveness fields should be **fed by** this stage, not invented in prose.)

---

## 9. Comparative reasoning (RC8) — SI.6

**Shipped (v0):** Opportunity Comparison Engine — `GET /v1/market/research/compare?a=&b=`.

Uses SI identity / packs / distinctiveness / valuation paths / dual confidence / optional holdings.
Frames research priority and lens honesty (“not interchangeable templates”). **Not a buy ticket** — MoS and evidence gates still apply.

| Module | Role |
|--------|------|
| `atlas/investment/research/compare.py` | Pure compare from awareness snapshots |
| `InvestmentResearchService.compare` | Loads awareness + optional holdings |
| Learner UI | Why A vs B row on IRA panel |

---

## 10. Relationship to other streams (do not mix)

| Plan | Responsibility | When |
|------|----------------|------|
| **Evidence Plan** | Quality & provenance of evidence | Sprint 1 — finish & freeze |
| **ARMF / OI-OPS1** | Observable + fair execution of research ticks | Sprints 2–3 — after Evidence |
| **Sector Intelligence** | Quality of **questions and analytical lens** | Sprint 4 — after ARMF C |
| **IIP** | Themes, discovery, MKG, scoring, portfolio, thesis tracker, news | Shipped (operate) |

Sector Intelligence consumes better evidence **and** stops asking the wrong questions when evidence is thin — but only after research ticks can actually run under ARMF.

---

## 11. Ship order (locked — see master roadmap)

| Stage | Work | Gate |
|-------|------|------|
| **SI.0** | This doc + `OI-SI0` | ✅ locked |
| **SI.1** | Business Identity Engine + dossier gate | ✅ frozen 2026-07-28 |
| **SI.2** | Sector packs v1 (India) + loader | ✅ frozen 2026-07-28 |
| **SI.3** | Research Strategy Generator + question mix | ✅ frozen 2026-07-28 |
| **SI.4** | Valuation path branching on gaps | ✅ frozen 2026-07-28 |
| **SI.5** | Distinctiveness block on awareness UI | ✅ frozen 2026-07-28 |
| **SI.6** | Comparative engine (Why A vs B) | ✅ frozen 2026-07-28 |

**Do not** start SI.1 while Evidence is mid-flight or before ARMF A–C. Sector Intelligence creates more research work; without ARMF that work waits.

Master order: [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md).

---

## 12. Success metrics (5–10 year direction)

| Metric | Target |
|--------|--------|
| Hospital vs capital-goods dossiers | Visibly different question sets & KPI focus |
| “Sector unknown” on liquid NSE names | Rare; explicit CapabilityGap when true |
| Universal question share | ≤30% of active research questions |
| Valuation method | Matches available evidence path (no fake DCF) |
| Distinctiveness | Present on awareness before MoS deep-dive |
| Evidence Plan | Remains the source of financial truth |

---

## 13. Explicit non-goals

- Replacing IRA / MVR / Thesis Tracker with a new OS  
- Scraping Screener HTML for sector pages  
- Inventing KPIs without evidence  
- Mixing SI implementation into the locked Evidence Plan sprint  
- Building “Why A vs B” before identity packs exist  

---

## 14. Operator lock checklist

- [x] Permanent rule: classify business & analysis lens **before** due diligence  
- [x] Insert identity → pack → strategy **above** existing IRA (do not rewrite spine)  
- [x] Universal questions minority; sector questions majority  
- [x] Separate confidence by knowledge type  
- [x] Missing evidence changes valuation **path**, not only warnings  
- [x] Evidence → ARMF A/B → ARMF C → SI (master roadmap)  
- [x] Comparative reasoning (SI.6 v0 — research framing, not buy ticket)

**Next action:** operate SI.1–6 under paper trading; optional ARMF C10 soft-focus polish or Phase D archive clarity. See [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md).