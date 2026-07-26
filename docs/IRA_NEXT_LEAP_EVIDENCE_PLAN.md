# IRA Next Leap — Evidence Quality Plan

> **Status:** 🔒 **LOCKED for implementation** (operator lock 2026-07-26)  
> **Parent:** [`INVESTING_RESEARCH_AGENT_PLAN.md`](INVESTING_RESEARCH_AGENT_PLAN.md) (Phases A–E shipped)  
> **Goal:** Raise **investment usefulness** and **research maturity** by feeding the existing reasoning spine with **progressively richer, trustworthy evidence** — not by making Atlas “sound smarter.”  
> **Non-negotiables (unchanged):** P10 · MI4/MI5 · CapabilityGap honesty · coverage ≠ confidence ≠ research quality · timing ≠ thesis · MVR ≠ buy · no ToS scraping · never invent line items · IR-RO11 host-first · **Evidence before eloquence**

---

## 0. Locked operator decisions

| Decision | Lock |
|----------|------|
| Evidence path (30 days) | **A — Operator snapshots only** (ladder layer 1). Licensed API later as same architecture, better input. |
| Auto refresh | **Yes — incremental only.** Snapshot fields invalidate/strengthen named sections; no full rebuild. |
| MoS v1 | **Trailing FCF + PE + price** enough for initial MoS (label method + valuation confidence). Multi-year statements required to elevate research quality to **substantive** and valuation confidence. |
| Deep mode | **Operator may always force.** Auto-deep remains **quality-gated**. |

### Evidence ladder (not A/B/C silos)

```text
1  Operator Snapshot          ← locked now
2  Operator Statements (multi-year)
3  Official Filing References
4  Licensed Fundamentals
5  Extracted Financial Statements
```

Atlas climbs the ladder. New layers do not redesign the spine.

### Design rule (years payoff)

**Every new piece of evidence declares which dossier sections it invalidates or strengthens.**

| Evidence | Strengthens / refreshes |
|----------|-------------------------|
| Cash-flow / FCF / PE / price / shares | Cash Flow · Valuation · MoS · Thesis (stance/summary patch) |
| Debt / ROE / ROIC / margins | Financial Health · Profitability · (Risks if leverage stress) |
| CEO resignation / governance note | Management · Risks · Thesis weaken — **not** full rebuild |
| Working-capital figures | Financial Health · Cash Flow · thesis execution assumptions |

---

## 1. Diagnosis (locked)

Architecture/honesty are strong. Maturity is limited by **inputs**.  
ThesisOutcome → Experience is how “senior” judgment arrives — not prompts.

**Do not:** make Atlas sound smarter without more evidence.  
**Do:** Operator → Snapshot → Evidence → Research Memory → Valuation → Thesis.

---

## 2. Axes of awareness (four + sufficiency)

| Axis | Meaning |
|------|---------|
| **Coverage** | Depth-weighted fraction of DD surface examined |
| **Confidence** | Belief quality on examined parts |
| **Research quality** | Shallow vs deep overall (`basic`…`deep`) — later: EvidenceQuality × Coverage × Freshness |
| **Evidence sufficiency** | *Per question / per decision need* — not another 0–100 score |

### Evidence sufficiency (F0+)

```text
Cash Flow     → missing | weak | sufficient
Management    → missing | weak | sufficient
Valuation     → insufficient | weak | sufficient
Decision      → watch | size_allowed (policy)
```

Answers: “Do I have enough evidence to answer **this** question?” — prevents treating all gaps as equal.

### Missing inputs priority (F0)

| Tier | Examples |
|------|----------|
| **Critical** (blocks MoS / DCF) | FCF, shares outstanding, current price *(and/or PE for multiples MoS)* |
| **Important** | ROIC, debt/equity, margin trend, growth assumption |
| **Optional** | Insider buying, ESG, dividend history |

### Research questions lifecycle

```text
Answered | Open | Blocked | Deferred
```

Deferred = consciously postponed (e.g. macro sensitivity) — Planning OS queue.

---

## 3. Evidence hierarchy (formalize in F2)

| Level | Example | Default weight |
|-------|---------|----------------|
| **A** | Audited annual report | highest |
| **B** | Quarterly filing | |
| **C** | Investor presentation | |
| **D** | Conference call | |
| **E** | News report | |
| **F** | Operator note / snapshot | honest mid — tagged operator |
| **G** | AI inference | lowest — never alone for confidence ≥ medium |

UI target: `Management confidence=medium · evidence=A,B,D` not only `Management=medium`.

### Critical evidence (anti-checklist)

A real thesis is **not** the sum of 100 fields. Some findings **invalidate** the thesis regardless of coverage:

- Management lied about cash → thesis falsified  
- Debt covenant breached → DCF irrelevant  

Track `critical_flags[]` on dossier; they outweigh completed checklists.

---

## 4. Work packages

### F0 — Instrument ✅

| ID | Item |
|----|------|
| **IRA.22** | Awareness: missing Critical / Important / Optional + evidence_sufficiency |
| **IRA.22b** | Field → section impact map; incremental refresh only |
| **IRA.22c** | Valuation method label + valuation confidence (Simple Multiple / Low, …) |

### F1 — Operator snapshots ✅

| ID | Item |
|----|------|
| **IRA.23** | Market UI research snapshot form |
| **IRA.23b** | Per-field evidence confidence: verified \| estimated |
| **IRA.23c** | POST snapshot → incremental sections → thesis patch |
| **IRA.24** | Filing refs UI + API (ladder layer 3) ✅ |
| **IRA.24b** | Multi-year statement schema — later |

### F2 — Claim ↔ evidence + scheduler ✅ (v0)

| ID | Item |
|----|------|
| **IRA.25** | Claims with hierarchy levels A–G |
| **IRA.25b** | Confidence capped without evidence pointers |
| **IRA.26** | Question scheduler / next_work; freshness prioritizes open work |
| **IRA.26b** | `critical_flags` short-circuit (blocks paper buys) |

### F3 — Management pack · F5 — Outcome priors · F4 — Licensed client

| Slice | Status |
|-------|--------|
| **F3** Management evidence pack + checklist API/UI | **Done** — `POST /v1/market/research/{symbol}/management` |
| **F5** ThesisOutcome → section priors + ranking + next_work | **Done** — `outcome_priors` on dossier; bias map + scheduler |
| Deep auto quality-gated; operator `force=true` always | **Done** |
| **F4** Licensed fundamentals client | **Deferred** — only after F1 consistently useful; adapter = better input, same architecture |

### Sector Intelligence Leap (post F3/F5)

| Slice | Status |
|-------|--------|
| Rich Sector Intelligence Packs (KPIs, drivers, falsifiers, risks, valuation methods, moat) | **Done** — `defence`, `healthcare`, `manufacturing`, `saas_it`, `banks` |
| Apollo vs MTAR distinct theses / questions / risks / base cases | **Done** |
| Thesis drivers (positive / concern / unknown) + distinctiveness metric | **Done** |
| Sector unknown → business coverage ≤10% | **Done** |
| Coverage layers: evidence vs reasoning | **Done** |

Unchanged order from prior proposal: **F4 only after F1 consistently useful**; adapter = better input, same architecture.

---

## 5. MoS / valuation labeling (locked)

**Phase 1 (now):** MoS from trailing FCF and/or PE + price when present; operator assumptions explicit.

```text
Valuation
  method: simple_multiple | dcf_stub | hybrid | insufficient
  method_confidence: low | medium | high
  missing: { critical[], important[], optional[] }
```

**Later:** 5-year DCF (medium); hybrid DCF+relative+ROIC (high) — only with multi-year evidence.

---

## 6. Deep mode (locked)

| Path | Rule |
|------|------|
| Operator force | Always allowed |
| Automatic deep | Quality-gated (`developing`+ or equivalent) |

---

## 7. Acceptance — F0+F1 done

1. Operator pastes PE/FCF/price/shares from Market UI without curl.  
2. Fields tagged `source=operator_snapshot`, `as_of`, `evidence_confidence=verified|estimated`.  
3. Only impacted sections refresh; business/moat untouched unless impacted.  
4. Missing inputs shown as Critical / Important / Optional.  
5. Evidence sufficiency visible for cash flow / management / valuation / decision.  
6. Method leaves `insufficient` when critical inputs present; still WATCH if MoS policy requires.  
7. Still P10; never invent fundamentals.

---

## 8. Explicit non-goals

Scraping · inventing IV · prompt-only senior tone · Research OS · rushing licensed adapter · checklist-as-thesis without critical evidence.

---

*Locked. Implement F0 → F1 next.*
