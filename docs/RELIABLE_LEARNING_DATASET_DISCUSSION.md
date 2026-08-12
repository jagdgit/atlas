# Reliable Learning Dataset v1 — Discussion & Market Coverage Plan

> **Status:** OPERATOR-LOCKED (D1–D6 ✅) — Phase **1A+1B ✅**; Phase **3 MTL densify ✅**; Yahoo IP-budget hard-pause + durable-prefer ✅; System vs Trading maturity split ✅; Phase **2 FCF** still Screener  
> **Date:** 2026-08-09  
> **IDs:** `OI-RLD0` · `OI-MKT-COV` · `OI-MTL0` · `OI-GENE0` · related follow-ons below  
> **Purpose:** Capture the evening-email review findings, the live root-cause investigation,
> and a phased improve/add/fix roadmap. D1–D6 locked; next = Phase 2 FCF densify → multi-day accel → Phase 4 evidence attribution → `OI-GENE0` before ML.

**Companion registry:** [`OPEN_ITEMS.md`](OPEN_ITEMS.md)  
**Honesty already shipped:** evening truth table, `RANKING: NOT YET TRUSTWORTHY`, news→unproven  
**North star (unchanged):** Atlas as a structured investment laboratory. Strategy V1 =
SMA/RSI + PLC exits = **control**. No live NN. No silent strategy mutation.

---

## 0. Bottom line (operator verdict)

| Claim | Verdict |
|-------|---------|
| Honesty / reporting layer | ✅ Working — keep |
| Atlas is learning to trade | ❌ Not yet |
| What Atlas is doing well | Recording the *conditions required* to eventually learn |
| Immediate blocker | **Market-data coverage for ranking** — not more report polish |
| Immediate non-goals | F&O, AtlasNet training, silent strategy rewrite |

One-line target:

> **Make Atlas see the 190-stock universe reliably first.**

Then V1 can generate diverse decisions → exits → timeline causes → Learning Intelligence →
only later AtlasNet.

---

## 1. What we verified on the live machine (2026-08-09)

### 1.1 Universe coverage ≠ market-data coverage

| Signal | Live value | Meaning |
|--------|------------|---------|
| Universe scanned | **190/190** | Membership / triage ladder written |
| Price coverage | **0.0%** | `last_price is None` on **all** 190 triage rows |
| Ranking scores | **0.500** everywhere | Cold-start fallback in `score_universe()` |
| Movements / acceleration | none / `pending_history` | No prior priced days |
| Watchlist `extra.provider` | `""` | M0 ran with empty provider |
| Watchlist `bars_symbols` | **0** | No OHLC collected for ranking |
| Watchlist `feed_failures` | **190** | Every symbol failed bar fetch |
| Feed failure reason (IU) | `no market_data asset named '….NS'` via **`default`/`asset_replay`** | Ranking never called Yahoo |

Evidence paths:

- `/data/atlas_data/investment/triage/market_intelligence/2026-08-09.jsonl`
- `/data/atlas_data/market/watchlists/market_intelligence.json` → `extra`
- `/data/atlas_data/market/feed_failures.jsonl`

### 1.2 Holdings have marks — ranking does not see them

Open-book / evening marks **do** use Yahoo (paper trading `live_provider=yahoo`,
investor-reports mark path hard-wires Yahoo). That is why the email can show:

- APOLLOHOSP ≈ ₹8,945  
- ASIANPAINT ≈ ₹2,735  
- EICHERMOT ≈ ₹8,020  

…while ranking prints `px=—` and coverage 0%.

```text
  Yahoo ──► paper_trading / investor_reports marks     ✅
  Yahoo ✗── Investment Universe (provider="")          ❌ → asset_replay → 0 bars
```

**Conclusion:** this is **not** “Atlas has no market data.”  
It is **“the ranking pipeline is not calling the same provider the ledger uses.”**

Preset already intends Yahoo for M0 (`programs.india_equity_learner_overrides()` sets
`investment_universe.provider = "yahoo"`), but the **running mission / published watchlist**
shows `provider: ""`. Template default in `builtins.py` is still `"provider": ""`.

### 1.3 What “price coverage” means today (honesty)

Computed in `triage_memory.coverage_from_rows()`:

> % of membership rows with non-null **`last_price`**  
> (`last_price` = last daily close from bars used for ranking)

It does **not** yet mean: N years of history, corporate-action integrity, volume completeness,
or readiness grade A/B/C/D. Those belong in the **data readiness contract** proposed below.

Cold-start scoring (`ranking.score_universe`): if fewer than ~25% of members have ≥5 bars,
every score is forced to **0.5** with `phase=learning` / `confidence=very_low`.

---

## 2. Agreed keep / don’t change

| Keep | Why |
|------|-----|
| `RANKING: NOT YET TRUSTWORTHY` + provisional list | Honesty working |
| Three-tier metrics: evaluations ≠ unique states ≠ trading experiences | Stops packet vanity |
| Strategy V1 = control (SMA/RSI + PLC exits) | Baseline for all future experiments |
| `train_allowed=False` / `live_nn_trading=False` with `total_closed=0` | Correct gate |
| Missing data ≠ zero | Already philosophy in several paths — keep |
| “Open observation only until exit/review vs thesis falsifiers” | Permanent |

| Do not start yet | Why |
|------------------|-----|
| AtlasNet training | No clean diverse outcomes |
| F&O | Premature vs equity sensor readiness |
| Silent strategy mutation | Breaks control-group science |
| Demoting news/sector because contribution≈0 | Coverage insufficient → **unproven**, not useless |

---

## 3. Discussion topics — improve / add / fix

### 3.1 OI-MKT-COV Phase A — unblock ranking (bugfix, high leverage)

**Proposal (discuss):**

1. **Default empty M0 provider → `yahoo`** when `market.yahoo_enabled` (match
   `opportunity_discovery` and program overrides).  
   Files: `workers/investment_universe.py`, optionally `templates/builtins.py`.
2. **Patch / re-apply live mission config** so running M0 isn’t stuck on `provider: ""`.
3. **Re-run Investment Universe tick**; expect `bars_symbols ≈ 190`,
   `price_coverage_pct ≥ 95`, scores leave flat 0.500 (needs ≥~25% with ≥5 bars).
4. **Do not** fake coverage by copying paper-trading `last_marks` into triage without
   bars — that would invent momentum/liquidity.

**Open questions for discussion:**

- Q1: Is Yahoo-as-default acceptable for production M0, or do we require an explicit
  operator toggle even when `yahoo_enabled`?
- Q2: After Yahoo works, do we still want a **durable OHLC store** before declaring
  OI-MKT-COV done? (Recommended: yes — see Phase B.)
- Q3: How to treat symbols with Yahoo 404 (e.g. renamed tickers like ZOMATO/TATAMOTORS
  aliases) — membership hygiene vs permanent gap?

### 3.2 OI-MKT-COV Phase B — Market Data Readiness contract (add)

Do **not** define success only as “95% last price.” Propose a per-symbol readiness card:

```text
Symbol
├── current / last close
├── OHLCV series
├── trading dates / missing-date %
├── history length (bars / calendar days)
├── corporate-action integrity (adjusted vs raw) — later
├── volume coverage
├── last successful update + provider
└── readiness grade
```

**Proposed grades:**

| Grade | Rule of thumb |
|-------|----------------|
| **A** | ≥99% priced + fresh bar + min history |
| **B** | 95–99% + min history + fresh |
| **C** | 80–95% |
| **D** | &lt;80% |

**Ranking trust gate (discuss):**

```text
price readiness ≥ B
AND minimum history (e.g. ≥60 daily bars or existing min_bars policy)
AND current bar fresh (e.g. last close ≤ 1 trading day stale when market open/closed rules apply)
→ else: NO TRUSTWORTHY RANKING (keep provisional list)
```

Report should distinguish explicitly:

| Metric | Meaning |
|--------|---------|
| Universe membership coverage | symbols known / scanned |
| **Latest mark coverage** | open book / EOD marks (Yahoo path that already works) |
| **Ranking bar coverage** | fraction with OHLC used by `score_universe` |
| **History readiness** | grade A–D + acceleration status |

**Open questions:**

- Q4: Persist bars under `/data/atlas_data/market/bars/{symbol}.jsonl` (or Asset store)?
- Q5: Refresh policy — full universe hourly vs deep watchlist aggressive / long-tail slower?
- Q6: Rate-limit / Host Guard interaction when pulling 190× Yahoo chart?

### 3.3 Fundamentals report rewrite (fix reporting) + FCF priority (improve)

Live ambiguity to remove:

```text
PE 18/18          vs   Watchlist gaps 5/5 missing PE/FCF/ROE
with_fcf = 2/18        PE miss=0  FCF miss=5
```

**Proposed evening layout:**

```text
ACTIVE BOOK / STORE FUNDAMENTALS
  PE        18/18
  FCF        2/18
  ROE        ?/18
  P/B        ?/18
  ROIC       ?/18
  Industry PE ?/18

ACTIVE WATCHLIST (deep)
  PE         5/5
  FCF        0/5
  ROE        0/5
```

No “missing PE/FCF” conflation when PE miss=0.

**Target packet fields (Phase 2 — discuss order):**

| Bucket | Fields |
|--------|--------|
| Valuation | PE, Forward PE, P/B, FCF, FCF yield, EV/EBITDA, Industry PE, Historical PE, DCF/MoS |
| Quality | ROE, ROIC, margins, debt, interest coverage, FCF conversion |
| Growth | Revenue / EPS / FCF CAGR |

**Rule:** missing → `unknown` / gap, **never** coerced to 0 for learning.

**Open questions:**

- Q7: Is FCF-first enrich for **open books + watchlist 5** enough for Phase 2, or do we
  require full 18-store completeness before ranking trust?
- Q8: Screener vs Yahoo vs operator CSV — priority provider ladder?

### 3.4 Attribution semantics — unknown ≠ learned (fix)

Today: `format_causal_learning_lines` titles section  
**“What Atlas learned (causes · DAV.1)”** and then prints  
`unknown: sector, news, policy, thesis`.

**Proposed split:**

```text
WHAT ATLAS LEARNED
  · (only helped/hurt with evidence)

WHAT ATLAS COULD NOT DETERMINE
  · No company-news evidence
  · No sector attribution
  · No policy attribution

DATA REQUIRED
  · Company news timeline
  · Sector timeline
  · Market regime
```

Infrastructure ✅ · Knowledge ❌ — keep that distinction in copy and metrics
(`attributed_trade_outcomes` vs `attributed_all_unknown`).

### 3.5 Email HOLD dump collapse (fix UI)

Truth table already collapses metrics; `format_decisions_section` still lists up to 40
near-identical HOLD rows.

**Proposed email shape:**

```text
Decision evaluations: 100
Unique decision states: 1
Trading experiences: 0

Dominant state:
  HOLD / switch_blocked_cold_start / fcf_missing
  Occurrences: 100
Affected (sample): EICHERMOT, CIPLA, BHARTIARTL, …

(Material buy/sell packets listed in full.)
```

**Open question:**

- Q9: Collapse in email only, or also soft-cap DB writes further (already 1/symbol/reason/day)?

### 3.6 Market Timeline (add — Phase 3)

For each open position, continuously align on timestamp:

```text
COMPANY TIMELINE
  Price ───────────────────────────>
  Technical (SMA/RSI/vol)
  Company events (earnings/guidance/…)
  Sector (index RS + sector news)
  Market (NIFTY / VIX / regime)
  News (company / sector / macro)
  Policy (gov / RBI / SEBI)
  Fundamentals deltas
  Atlas belief → confidence → decision → action
```

At revisit:

```text
What changed? → What did Atlas know? → What did Atlas believe?
→ What caused movement? → Was the decision correct?
→ Which component deserves learning?
```

This is the bridge from attribution **infrastructure** to attribution **knowledge**.

**Open questions:**

- Q10: New store vs densify existing open-book packs + observations + government intel?
- Q11: Minimum viable timeline = open books only, or full watchlist?

### 3.7 Genealogy (roadmap — before ML, after coverage)

`genealogy = 0.0%` today = almost no `parent_decision_id` links.

Needed chain (discuss, not Phase 1):

```text
Decision → evidence → feature → strategy → experiment → outcome → lesson → next decision
```

Track as **OI-GENE0** (proposed) — P2 after MKT-COV + timeline start; **before** AtlasNet.

### 3.8 Strategy evolution (keep deferred — Phase 5+)

```text
V1 (frozen control)
  → Experiment A/B (RS, valuation, news regime, …)
  → Outcomes + attribution
  → Statistical + walk-forward vs V1
  → Candidate → operator approval → V2
```

Atlas may *propose* “RSI useless in regime X” — never silently rewrite.

### 3.9 AtlasNet gate (keep — Phase 7)

Do not train merely because N≥500 trades. Dataset must also have:

- diverse regimes  
- clean packets + timestamps + provenance  
- meaningful outcomes  
- no duplicated observations / look-ahead  
- baseline beaten + walk-forward  

Current hard gate (`total_closed=0` → blocked) stays.

---

## 4. Recommended sequence (lock for discussion)

| Phase | Name | Outcome |
|-------|------|---------|
| **1** | **OI-MKT-COV** | Ranking sees Yahoo (or durable bars); readiness ≥B; scores leave 0.500; trust banner can clear when contract met |
| **2** | Fundamentals densify | Clear PE/FCF/ROE/… tables; FCF for open books + watchlist; missing≠0 |
| **3** | Market Timeline | Timestamp-aligned company/sector/market/news/policy/fundamentals/Atlas |
| **4** | Evidence-backed attribution | `unknown:*` → helped/hurt only with evidence; copy split learned vs undetermined |
| **5** | Strategy experiments | V1 frozen; controlled candidates only |
| **6** | Learning Dataset v1 complete | Evaluations / unique states / experiences clean + attributable |
| **7** | AtlasNet | Only when gates genuinely satisfied |

**Small honesty fixes that can ship alongside Phase 1 (low risk):**

- Fundamentals section rewrite (3.3)  
- Causal section rename/split (3.4)  
- Decisions email collapse (3.5)  

Discuss whether these ride with Phase 1 or wait for a thin “OI-RLD0.report” patch.

---

## 5. Proposed OPEN_ITEMS updates (after agreement)

| ID | Status intent | Notes |
|----|---------------|-------|
| `OI-RLD0` | 🟡 partial | Honesty metrics/ranking banner done; dataset readiness open |
| `OI-MKT-COV` | 🔴 → implement Phase A then B | Root cause: M0 provider empty → asset_replay |
| `OI-FUND-RPT` | 🔴 (new, small) | Split store vs watchlist fundamentals tables |
| `OI-ATTR-COPY` | 🔴 (new, small) | Learned vs could-not-determine |
| `OI-DEC-MAIL` | 🔴 (new, small) | Collapse dominant HOLD state in email |
| `OI-MTL0` | 🔴 (new) | Market Timeline Phase 3 |
| `OI-GENE0` | 🟡 GENE.1 ✅ | Decision genealogy assemble + parent stamp; lesson→next densify remaining |
| Strategy / NN | unchanged | V1 control; NN blocked |

---

## 6. Operator decisions — LOCKED 2026-08-09

| ID | Call | Rule |
|----|------|------|
| **D1** | ✅ APPROVED | M0 uses Yahoo when `market.yahoo_enabled` and provider empty/unset. Keep provider abstraction — do **not** hard-code Yahoo globally. |
| **D2** | ✅ APPROVED | Durable OHLCV + readiness ≥B required before `RANKING TRUSTWORTHY`. Phase 1A verifies live Yahoo coverage; Phase 1B unlocks trust. |
| **D3** | ✅ APPROVED | Fundamentals clarity + attribution semantics + HOLD-collapse ship with Phase 1A. |
| **D4** | ✅ APPROVED | Fundamentals priority = open books + current deep watchlist. Do not require full-store completeness for ranking. |
| **D5** | ✅ APPROVED | Open-book Market Timeline is Phase-3 MVP; expand to watchlist later. |
| **D6** | ✅ APPROVED | `OI-GENE0` registered as P2 roadmap; implement before serious ML/AtlasNet — not part of MKT-COV. |

**Implementation rule (locked):**

> OI-MKT-COV Phase 1A is the next code change. Do not add indicators, F&O learning,
> strategy changes, or AtlasNet work before Phase 1A is verified.
> UTS architecture stays finalized but is **not operationally meaningful** until
> market sensors (MKT-COV) feed real bars.

### Phase 1A acceptance (verified 2026-08-09)

- ✅ `bars_symbols = 187` (3 feed failures — renamed/404 tickers)
- ✅ `price_coverage_pct = 98.4`
- ✅ `provider = yahoo` (empty cfg resolved; abstraction kept)
- ✅ scores differentiated (top ≈0.61 … not flat 0.500); `phase=active`

### Phase 1B acceptance (verified 2026-08-09)

- ✅ Durable store `/data/atlas_data/market/bars/*.json` — **187** symbol files
- ✅ Readiness **grade B** (`priced 98.4%`, `history 97.9%`, `fresh 97.9%`, `ready 97.4%`)
- ✅ `durable_bars_ok=True` → ranking trust can clear when phase not cold-start
- Accel / rank Δ still `pending_history` until ≥2–3 triage days (UTS.B) — soft, not a D2 hard block

---

## 7. Explicit non-claims

This discussion does **not** claim:

- that Atlas has a trading edge,  
- that 8 attributions with all-unknown causes are “learning,”  
- that 178 packets are 178 experiences,  
- or that AtlasNet should be loosened to “learn faster.”

It claims only:

> Atlas’s honesty layer is good enough to show that **market sensors for ranking are the blocker**,
> and that the next engineering work should make Atlas **observe the universe** the way the
> ledger already observes open-book marks.

---

_When this discussion is accepted, freeze a short implementation plan (or promote sections into
`OPEN_ITEMS` + a thin `OI-MKT-COV` implementation note) and execute Phase 1A first._
