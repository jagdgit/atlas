# Atlas — Fundamental Intelligence (canonical facts, not a PE fetcher)

> **Status:** 🔒 **N1 HBLPOWER LOCKED (golden replay 2026-09-19) — remaining = other names + edge cases, not universe ingest**  
> **Date:** 2026-09-19 (N1 locked; NSE remains P0 of TRADE-LOOP0)  
> **Codename:** `OI-FUND-INTEL0`  
> **Parent:** [`ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md`](ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md)  
> **Does not replace:** [`ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md`](ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md) (Phase 1 repair still required)  
> **Does start now (after lock):** one-company NSE/XBRL path + min canonical facts + TTM/avg-equity/D/E-map/`available_at` + sector/identity paths + hourly FI block. See [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md).

**One sentence:**

> Atlas should acquire raw financial evidence from exchange/company filings, store the original permanently, normalize it into its own canonical model, calculate PE/ROE/D/E/FCF itself, cross-check Yahoo/Screener, and refresh when new results are filed — not treat Screener CSV as the operating system.

Phase 1 of TRADE-LOOP0 **includes an NSE/XBRL vertical slice** so PLC.A can receive real evidence, not only Yahoo plumbing tests. Universe ingest, all taxonomies, and auto-refresh of the full book remain later stages. Do **not** build the giant warehouse Friday night.

---

## 0. What this is not

| Do not | Why |
|--------|-----|
| Scrape Screener HTML | No API; ToS; not a product backbone |
| Buy another API this sprint | Zerodha (market) + Yahoo/Screener/NSE (books) are enough to start |
| Scrape NSE result HTML as the engine | Use XBRL/CSV/machine-readable Integrated Filing; inspect access rules; prove 1 then 3 names before scale |
| Store only PE/ROE/D/E | Those are calculations, not evidence |
| Fetch ROE every 5 minutes | Accounting facts are filing-driven |
| LLM / RL filling missing numbers | Invented fundamentals poison PLC.A |
| Treat missing as 0 | UNKNOWN ≠ 0 |
| Mix standalone and consolidated unlabeled | Scope is part of the fact |
| Mix quarterly and annual unlabeled | Period is part of the fact |
| Let a vendor’s ratio be unquestioned truth | Atlas calculates; vendors cross-check |

---

## 1. Three levels of “fundamentals”

| Level | What | Examples | Clock |
|-------|------|----------|-------|
| **1. Raw financial facts** | What the company reported | Revenue, net income, CFO, CapEx, assets, liabilities, equity, borrowings, shares, reported EPS | Filing / result |
| **2. Derived metrics** | Atlas calculations | EPS, PE, ROE, ROCE, D/E, FCF, FCF yield, margins, growth | Recalc when facts **or** price change |
| **3. Decision metrics** | Combined with market/research/risk | MoS (IRA), thesis, PLC.A | Decision tick |

PLC.A still consumes PE/ROE/D/E. The change is **where those numbers come from**: calculated from Level 1, not fetched as opaque ratios.

PE is special: `Zerodha price + latest valid EPS`. It can move intraday **without** re-downloading statements.

ROE / D/E / FCF refresh when statements change, not on the 5-minute tape.

That is why the Yahoo 429 storm is partly architectural: Atlas was polling **slow** facts on a **fast** clock.

```text
MARKET CLOCK (seconds/minutes)          FUNDAMENTAL CLOCK (quarterly / event)
Zerodha LTP / OHLC / volume             NSE XBRL / filings / Yahoo statements
        │                                         │
        └──────────────┬──────────────────────────┘
                       ▼
                 Atlas engine
                       │
              PE (price × EPS)
              ROE / D/E / FCF (statement)
                       │
                      IRA
                       │
                     PLC.A
```

---

## 2. Source roles (locked)

| Source | Role | Never |
|--------|------|-------|
| **NSE XBRL / financial results** | Primary raw facts (vertical slice now; universe later) | HTML scrape of result pages as the engine |
| **Company annual reports / result PDFs** | Secondary document; keep raw | Unlabeled extract overwriting XBRL |
| **Yahoo** | Fallback raw + ratio **cross-check**; Phase 1 still the network path | Sole long-term truth |
| **Screener export** | Bootstrap, debug, periodic validation (operator CSV/XLSX) | Permanent feed; HTML scrape |
| **Zerodha** | Price, volume, identity/token | PE/FCF/ROE/D/E |
| **Paid statement API** | Optional later for normalized facts | Unquestioned vendor ratios |
| **Web search** | News/evidence | Filling PE/FCF |

When sources disagree: record `FUNDAMENTAL_CONFLICT` (period, scope, definition). Do **not** arbitrarily overwrite.

---

## 3. Canonical facts (the heart)

A fact is not `net_income = 850`. It is:

```text
symbol              HBLPOWER
canonical_field     NET_INCOME
value               850
unit                INR
scale               CRORE
period_start/end    …
period_type         FY | Q | TTM
scope               CONSOLIDATED | STANDALONE
source              NSE_XBRL | YAHOO | SCREENER_EXPORT | FILING | PROFILE
source_document     …
filed_at            …
available_at        …   ← when the market could have known this (broadcast/exchange time)
retrieved_at        …
raw_evidence_id     …
mapping_id          …
canonical_filing_id …
```

Preserve **raw** under `{data}/fundamentals/raw/{source}/{symbol}/{period}/` (hash + reference). Parsed rows without the original are not evidence.

**As-of:** PLC.A/replay carries `decision_at` and `evidence_as_of`. A fact with `available_at` after `evidence_as_of` **must not** enter that decision. Unknown `available_at` → do not invent; do not use for a decision that cannot be proven. See weekend discussion §5.

**Canonical vocabulary** (examples): `NET_INCOME`, `TOTAL_EQUITY` (begin and end for ROE), `TOTAL_DEBT` (`atlas.debt.total_borrowings.v1` — not total liabilities), `OPERATING_CASH_FLOW`, `CAPITAL_EXPENDITURE` (normalized positive outflow + original reported sign), `SHARES_OUTSTANDING`, `REVENUE`.

Provider names (`Profit for the Period`, `Total Borrowings`) map **into** these fields; the mapping is stored (`mapping_id`).

**Sector / identity** are PLC.A completeness fields, not XBRL P&L concepts. Own evidence path + provenance. Weekend N1 fails if they remain missing while ratios look complete.

**Company type / taxonomy:** NSE publishes different XBRL taxonomies (ordinary, banks, NBFC, insurers). Manufacturing D/E is not a bank schema. N4–N6 are stretch; HBLPOWER is ordinary industrial.

---

## 4. Atlas calculation engine (preserve existing derived FCF honesty)

| Metric | Intent | Store |
|--------|--------|--------|
| EPS | **TTM preferred** (four quarters, same scope, latest revision per quarter). FY fallback only when `eps_fy_fallback=true` on the row. **Never** a single quarterly PAT as annual EPS. Diluted shares when present. | `eps_basis=TTM\|FY` + inputs |
| PE | Zerodha LTP / chosen EPS | `eps_basis` required; not a filing field |
| ROE | Net income / **average** equity = (begin + end) / 2, same scope | beginning + ending equity facts or UNKNOWN |
| D/E | `atlas.debt.total_borrowings.v1` = ST + LT + current maturities. **Not** total liabilities, leases, or net debt unless a later definition_id | `definition_id` + components + exclusions |
| FCF | `normalize_capex()` → CAPEX positive outflow → **`CFO − CAPEX`**. Original reported sign kept. Negative FCF stays negative. Missing CFO or CapEx → UNKNOWN. | `value_type=derived` + `normalization=` |

Yahoo’s historical `CFO + CapEx` (CapEx reported negative) is the **same arithmetic** after normalization — not a second formula.

Validation: currency/unit/scale/period/scope; `Assets ≈ Liabilities + Equity` within policy; parser errors create RETRY, not silent zeros. **Negative tests** (malformed XBRL, wrong period, zero equity, liabilities-as-debt) are P0.

Cross-check: typed `conflict_type` (`PERIOD`, `SCOPE`, `UNIT`, `DEBT_DEFINITION`, `EPS_BASIS`, `SOURCE_STALENESS`, `CALCULATION`, `UNKNOWN`). Match within documented tolerance **and** same period/scope/definition → `VALIDATED`. Else `FUNDAMENTAL_CONFLICT`. Do not silent-overwrite.

Freshness: every derived metric carries `period`, `filed_at`, `available_at`, `retrieved_at`. PLC.A uses `evidence_as_of`. Missing stays UNKNOWN.

**Filing selection:** see weekend discussion §4 (scope, period, latest revision, audited when required, reject superseded, keep all raw, mark canonical).

---

## 5. Stages

| Stage | Work | When |
|-------|------|------|
| **1a** | TRADE-LOOP0 A–F plumbing (UQ, Yahoo gate, pipeline, F&O) | In tree |
| **1b** | **NSE/XBRL vertical slice** + min facts + EPS/PE/ROE/D/E/FCF calc + hourly FI block | **Now (P0)** — HBLPOWER then 3 names |
| **2** | Canonical facts store densify (file-backed; Postgres later) | After 1b live on 3 names |
| **3** | NSE adapter scale: 10 → 100 → universe; remaining taxonomies | After 1b proof — **not Friday universe crawl** |
| **4** | Calc densify (ROCE, margins, growth) | With or after 1b |
| **5** | Cross-check Yahoo/Screener; conflicts | After 1b |
| **6** | Filing refresh worker (event clock, not 5m) | After 3 |
| **7** | FEA fully routed through this engine | Starts in 1b (NSE preferred) |

**Measurable NSE progression:** 1 (HBLPOWER) → 3 → 10 → 100 → universe. Weekend bar = **1–3**.

---

## 6. FEA after this exists

```text
PLC.A D/E missing
  → UQ debt_missing
  → FEA
  → Fundamental Intelligence
  → already have current D/E? DONE
  → else acquire raw (NSE → Yahoo → Screener import)
  → calculate → validate → DONE
  → else PENDING reason=debt_evidence_unavailable
```

Yahoo becomes **secondary**, not the single point of failure that produced `consecutive_blocks=1524`.

---

## 7. Target operator sentence (vertical slice)

```text
PLC.A FUNDAMENTALS
PE … ✓   ROE … ✓   D/E … ✓   FCF … ✓   sector … ✓   identity … ✓
period …   eps_basis=TTM   primary NSE_XBRL   price Zerodha
available_at …   evidence_as_of …
calculated by Atlas   validation PASSED|CONFLICT|UNKNOWN
→ PLC.A evaluate → BUY or HOLD
```

Weekend success: **N1 HBLPOWER** (replay + NSE + all PLC.A fields including sector/identity). N2/N3 target. Hourly mail shows NSE success / parse fail / per-symbol missing + reason.

---

## 8. Modules

Start **small** next to existing FEA — do not replace `fundamental_evidence/` this weekend:

```text
atlas/investment/fundamentals/
    evidence/          raw store (keep original XBRL)
    providers/         nse_xbrl, yahoo, screener_export
    calculations/      EPS PE ROE D/E FCF
```

Yahoo + operator import remain fallbacks.

---

## 9. Locks for this document

| ID | Decision |
|----|----------|
| FI-1 | Screener is bootstrap/validation, not the permanent operating mechanism |
| FI-2 | Long-term: acquire facts, Atlas calculates ratios |
| FI-3 | Two clocks: market vs filing |
| FI-4 | No **universe** NSE crawl until 1–3 names proven; inspect access rules; no HTML scrape |
| FI-5 | No new paid API, no LLM/RL fill, no Screener HTML |
| FI-6 | **Superseded:** Stage 1b (NSE vertical slice) is TRADE-LOOP0 P0. Stages 3–7 universe/refresh still later |
| FI-7 | `available_at` on facts; no future-filing leak into earlier `evidence_as_of` |
| FI-8 | PE TTM preferred; FY fallback explicit; never quarterly-as-annual |
| FI-9 | CapEx normalized once; FCF = CFO − CAPEX (Yahoo CFO+CapEx is equivalent after sign) |
| FI-10 | Sector/identity are not XBRL statement facts; still required for PLC.A completeness |
