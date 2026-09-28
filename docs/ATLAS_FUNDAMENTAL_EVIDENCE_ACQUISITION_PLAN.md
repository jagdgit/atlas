# Atlas — Fundamental Evidence Acquisition (FEA)

> **Status:** First slice landed 2026-09-03 (`OI-FEA0`). TRADE-LOOP0 A–D plumbing in tree. **Next:** provider-agnostic FEA with NSE/XBRL primary (after weekend-discussion lock).  
> **Goal:** When swing completeness stops at a missing fundamental (e.g. FCF),
> Atlas plans acquisition, tries permitted sources with provenance, validates,
> stores, refreshes IRA, and re-runs completeness — **without** manual CSV for
> every gap, and **without** scraping Screener HTML.
> **Non-goal:** Loosen WATCH / MoS / authorization gates. LLM does not authorize.

---

## 1. Why

Atlas already answers *where the chain stopped* (`chain_stops_at: fcf`).
FEA answers *what to do next* without turning Atlas into a blind web scraper.

```
technical BUY
     ↓
completeness → FCF missing
     ↓
Evidence Planner
     ↓
Yahoo (paced) ──► Screener operator import ──► filings (later)
     ↓
validate + provenance
     ↓
fundamentals store → IRA → MoS → thesis → gate
```

Paid Infoway / other commercial APIs are **deferred** until this architecture
is proven on Yahoo + operator Screener + (later) filings.

---

## 2. Architecture

| Layer | Module | Role |
|-------|--------|------|
| Policy | `fundamental_evidence/policy.py` | Per-metric source hierarchy |
| Planner | `fundamental_evidence/planner.py` | Missing fields + allowed sources |
| Runner | `fundamental_evidence/runner.py` | Acquire → validate → UQ DONE → IRA → completeness |
| Worker | `workers/fundamental_evidence.py` | Drain PENDING UQ pe/fcf/roe (~20m, yield RTH) |
| Contract | `data_plane_contract.py` | Zerodha ≠ PE/FCF; observable `SYMBOL_EVIDENCE_VIEW` |

### Source policy (first slice)

| Metric | Preferred | Fallback | Never |
|--------|-----------|----------|-------|
| LTP/OHLC | Zerodha | bar_store | — |
| PE | store / Yahoo | Screener **export** | Screener HTML scrape |
| FCF | store / Yahoo (reported or derived) | Screener export | invent from rumor |
| ROE / debt | store / Yahoo / universe_seed | Screener export | Zerodha |
| MoS | IRA valuation | — | fetch from market feed |

Screener.in has no public API and ToS restrict automated copying. Atlas uses
**operator CSV/xlsx import** only (`screener_xlsx`, drop folder, Invest intel paste).

---

## 3. Derived FCF (honest)

**Locked formula (all providers):** normalize reported CapEx to a **positive economic outflow**, then `FCF = CFO − CAPEX`. Provenance keeps the original reported sign (`normalization=NEGATIVE_OUTFLOW_TO_POSITIVE` or `ALREADY_POSITIVE`).

Yahoo CapEx is typically **negative**. Then `operating_cash_flow + capital_expenditures` equals `CFO − |CapEx|` — **same number**, not a second policy. Do not keep two formulas in new code.

```json
{
  "metric": "fcf",
  "value": -509.62,
  "value_type": "derived",
  "formula": "cfo - capex_normalized",
  "inputs": {
    "operating_cash_flow": 3204.28,
    "capital_expenditures_reported": -3713.9,
    "capex_normalized": 3713.9,
    "normalization": "NEGATIVE_OUTFLOW_TO_POSITIVE"
  },
  "period": "2025-03-31",
  "provider": "yahoo_fundamentals"
}
```

Never pretend a derived value was “reported FCF”. Missing CFO or CapEx → UNKNOWN, not 0. Negative FCF stays negative.

---

## 4. Worker behavior

`fundamental_evidence` tick:

1. Yield during NSE RTH (live marks own Yahoo IP)
2. Hard-pause on Yahoo cooldown (429) — suggest Screener import, do not hammer
3. `list_tasks` PENDING → bundle pe/fcf/roe per symbol
4. `acquire_for_symbol` → `enrich_from_yahoo` → validate → mark UQ `DONE`
5. Optional `apply_operator_snapshot` (IRA) when valuation fields land
6. Re-run `evaluate_evidence_completeness` + `build_symbol_evidence_view`

**Runtime wiring (LAB-LOOP0 Step 1):** the template and program member shipped, but
a Market Intelligence program started *before* that member existed never got a
mission. Kernel start now calls `ProgramService.ensure_missing_enabled_members`
so bounce instantiates the worker. It still **yields in RTH** and still does
not loosen PLC.A.

Swing **gate unchanged**. Negative MoS → thesis AVOID → HOLD is a valid outcome.

---

## 5. Operator path (still required sometimes)

When Yahoo is cooling or FCF absent everywhere:

1. Stage ritual / rename `WELCORP.NS.xlsx` → drop import  
2. Or paste flat CSV into Invest intel  
3. Prefer `push_to_ira: true` so MoS refreshes  

See `SCREENER_FUNDAMENTALS_IMPORT.md`.

---

## 6. Next densify

**A–F plumbing is in tree.** Next (after weekend-discussion **§15** lock): FEA is **provider-agnostic** — NSE/XBRL primary raw, Yahoo secondary, Screener import, Zerodha = price only. Slice C becomes real D/E from NSE facts + Atlas calc. **Sector/identity** have their own FEA path (not XBRL). Hourly/evening mail must include the FUNDAMENTAL INTELLIGENCE block **with per-symbol missing/reason**. TTM EPS, average equity, D/E mapping, `available_at`, and negative XBRL tests are P0 with the slice.

**Canonical facts / calc:** [`ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md`](ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md) Stage 1b (HBLPOWER vertical slice). Weekend proof: [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md).

Still not this slice:

- Filings / XBRL **universe** ingest  
- Treating Yahoo ratios as truth (they are a cross-check; mismatch → `fundamental_conflict`)  
- Web search as PE/FCF fill  
- Commercial statement API  
- Screener HTML scrape  

---

## 7. Tests

`tests/test_fundamental_evidence_fea.py` — policy, plan, Yahoo acquire + UQ DONE,
derived FCF provenance, cooldown respect.

---

## 8. Bounce

After deploy: `sudo bash scripts/bounce_atlas_stab0.sh` so
`fundamental_evidence` registers. Confirm program member starts; during RTH
worker should yield; after close / cooldown clear it drains WELCORP `fcf_missing`.
