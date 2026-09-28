# Atlas — Operational Trading Loop + F&O Universe

> **Status:** 🔒 **LOCKED 2026-09-18 — implementing P0 NSE vertical slice + L26–L37 + hourly block**  
> **Date:** 2026-09-18 (evening correction: NSE is P0, not postponed)  
> **Codename:** `OI-TRADE-LOOP0` (under `OI-LAB-LOOP0` / `OI-FEA0` / `OI-FNO-CONTRACT` / `OI-FUND-INTEL0`)  
> **Weekend proof (discussion, no code until lock):** [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md) — NSE vertical slice **with financial/as-of correctness** (L26–L35), hourly FI block, LIVE STAMP N1.  
> **Purpose:** Lock *what to fix* in the existing trading loop so SMA candidates can obtain evidence, and so the F&O lab can generate clean experiences across index underlyings — **without** loosening PLC.A, enabling live orders, or activating RL.  
> **Parents (do not reopen):**  
> [`ATLAS_LABS_INTEGRATION_AND_LEARNING_FEEDBACK_DISCUSSION.md`](ATLAS_LABS_INTEGRATION_AND_LEARNING_FEEDBACK_DISCUSSION.md) ·  
> [`ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md`](ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md) ·  
> [`ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md`](ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md) ·  
> [`ATLAS_LIVE_MARKET_AND_WEB_EVIDENCE_PLAN.md`](ATLAS_LIVE_MARKET_AND_WEB_EVIDENCE_PLAN.md) ·  
> [`ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md`](ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md) ·  
> [`SCREENER_FUNDAMENTALS_IMPORT.md`](SCREENER_FUNDAMENTALS_IMPORT.md) ·  
> [`ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md`](ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md) ·  
> [`OPEN_ITEMS.md`](OPEN_ITEMS.md)

**Explicit principle:**

> Atlas does not need more AI. It needs the existing candidate → evidence → authorization → paper fill → experience loop to be **observable and completable**. Zero fills because PLC.A is honest is acceptable. Zero fills because FEA never sees the candidate is not.

**L1–L11 locked 2026-09-18.** A–F plumbing is in tree. **L11 is amended:** Fundamental Intelligence **vertical slice (NSE/XBRL + calc)** is now P0 of this phase — not postponed. Universe ingest still later. See [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md).

---

## 0. What we agree (do not debate again)

| # | Agreement |
|---|-----------|
| A1 | Do **not** loosen PLC.A / WATCH / MoS to make the dashboard look busy. |
| A2 | Do **not** let LLM authorize BUY/SELL. Do **not** activate RL (LAB-LOOP0 Step 12 stays frozen). |
| A3 | Do **not** scrape Screener HTML. Operator CSV/XLSX is **bootstrap / verification**, not the permanent operating mechanism. |
| A4 | Zerodha is LTP/OHLC/volume. Never treat market data as PE/FCF/ROE/D/E. |
| A5 | Web search is not the PE/FCF filler. LLM does not guess missing statements. |
| A6 | Success ≠ “did it trade today?” Success = universe → candidates → evidence coverage → authorized names → paper fills → outcomes → learning, **honestly labeled at each drop**. |
| A7 | Step 11 restart canary is **LIVE COMPLETE** (2026-09-18 bounce×2: `F-002118` retrieved, LLM cited `[1]`). Do not bounce again for Step 11. |
| A8 | F&O Phase 3a = NIFTY + BANKNIFTY + FINNIFTY + MIDCPNIFTY, same resolver, paper, no writing. Stock F&O is Phase 3b. |
| A9 | F&O experiences stay isolated from cash-equity FEL. No second F&O system. |
| A10 | Objective: more **valid, diverse, reconstructable experiences** — not more trades, not guaranteed fills. |
| A11 | This phase can make Atlas **capable** of paper trades. It does not make Atlas a good/profitable trader. |
| A12 | Learning now = experience → FEL. RAG/LLM already remember **validated findings** (Step 11). LLM is not the trader. RL frozen. |
| A13 | Fundamentals: acquire **raw facts**, Atlas **calculates** PE/ROE/D/E/FCF with TTM/avg-equity/D/E-map/`available_at`. NSE/XBRL is P0 **vertical slice** (HBLPOWER first). **Sector/identity** complete via their own paths. Universe crawl later. |
| A14 | No new paid API. No Screener HTML. No LLM-invented statements. Confirm NSE machine-readable access; do not scrape result pages as the engine. |

---

## 1. Where we actually are (running system, 2026-09-18)

Classify every piece. **Code exists ≠ live-proven.**

| Area | Classification | Evidence |
|------|----------------|----------|
| SMA/RSI candidate generation | **LIVE-PROVEN** | 18 Sep packets: `buy:HBLPOWER`, `buy:YESBANK`, `buy:JUBLPHARMA`, `buy:COALINDIA`, `buy:IDEA` |
| PLC.A | **LIVE-PROVEN** | Same names blocked `fundamentals_incomplete` / research / AVOID. Gate is doing its job |
| Swing paper fills | **RUNNING, STARVED** | 0 fills, cash ₹55,477, plan 0/5 |
| FEA worker | **SCHEDULED / TICKING, ZERO ACQUISITIONS** | Worker exists; Yahoo gate idle path. Not “worker missing” |
| Yahoo fundamentals | **BROKEN / STORMING** | `yahoo_rate_gate.json`: `consecutive_blocks=1524`, `last_block_status=429`, `backoff_s=900` |
| UQ | **RUNNING, WRONG MATERIALITY** | Swing lab: 35 `NOT_WORTHWHILE`, 5 `PENDING` all `TATACHEM` |
| D/E acquisition | **CODE GAP** | PLC.A requires `debt_to_equity`; UQ/`_UQ_CODE` do not emit `debt_missing` |
| Zerodha feed | **LIVE-PROVEN** | After bounce: `READY`, token valid, LTP/hist PASS |
| Zerodha → bar_store | **CODE + PARTIAL LIVE** | Persistence wired; keep proving provider stamps on dated files |
| F&O NIFTY ATM CE/PE | **LIVE-PROVEN** | Fill `NIFTY26SEP23350PE`; resolver `NIFTY26SEPFUT` + ATM 23350 |
| F&O 4-index universe | **CODE IN TREE, NOT LIVE-STAMPED** | `INDEX_UNIVERSE` = NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY; same resolver; seed instruments all four. `phase1_nifty_only` **removed**. Live `investment/fno/contracts/` still **NIFTY-only** as of 18 Sep. Stock F&O still Phase 3b. Live stamp is **P1** (does not preempt NSE). |
| Experience / reward / FEL | **LIVE PATHS** | `blocked_buy` JSONL; E001 rejected; E002 queued |
| Findings RAG + LLM | **LIVE-PROVEN** | Step 11. LLM → trade remains forbidden |
| Chunk embed drain | **RUNNING** | Backfill scheduled; not the P0 |
| RL | **FROZEN** | Correct |

**Status rewrite vs LAB-LOOP0:**

```text
Step 11 = LIVE COMPLETE
Steps 1–10 = implementation present; several still need production evidence
Step 12 = FROZEN

Immediate phase name:
  Atlas Trading Lab — data-plane repair + F&O index-universe expansion
Not: learning stage / RAG stage / RL stage
```

---

## 2. The swing problem (P0)

SMA is not broken. The **candidate → evidence → authorization** path is starving it.

### 2.1 18 Sep drop (packets + session notes)

| Symbol | SMA | Final | Missing / reason |
|--------|-----|-------|------------------|
| HBLPOWER | BUY | PLC.A | pe, roe, debt_to_equity, sector — **no UQ** |
| JUBLPHARMA | BUY | PLC.A | pe, roe, debt_to_equity — **no UQ** |
| YESBANK | BUY | PLC.A | pe, roe, debt_to_equity — **no UQ** |
| COALINDIA | BUY | PLC.A | roe, debt_to_equity (PE present) — **no UQ** |
| IDEA | BUY | research_hold | `thesis_watch_insufficient` |
| WELCORP | BUY | lab_policy AVOID | fundamentals **present** (screener 2026-09-03) |
| PATANJALI | none | engine_hold | not a data bug |
| TATACHEM | mixed | engine / research | **5 PENDING** pe/roe/fcf/mos/identity |

Last Screener import: **2026-09-03**, 19 symbols. Planned SMA names are mostly **absent** from the store.

### 2.2 The intended FEA chain (keep this)

```text
technical BUY
      ↓
completeness
      ↓
missing PE / ROE / D/E / FCF / …
      ↓
Evidence Planner
      ↓
Yahoo (paced) ──► Screener operator export ──► filings (later)
      ↓
validate + provenance
      ↓
fundamentals store → IRA → MoS → PLC.A
      ↓
BUY or HOLD  (honest)
```

FEA **non-goal** remains: do not loosen WATCH/MoS/PLC.A.

### 2.3 The actual chain (live)

```text
SMA BUY HBLPOWER
      ↓
PLC.A incomplete
      ↓
UQ created?  → often NO (pruned, or never material)
      ↓
FEA drains only remaining PENDING (TATACHEM)
      ↓
Yahoo 429  (consecutive_blocks=1524)
      ↓
0 fields acquired
      ↓
dashboard: 0 fills
```

That is an **infrastructure failure**, not a strategy verdict.

---

## 3. Five localized breaks (do not rebuild FEA)

These are the forensic points. Fix these; do not write a new fundamentals product.

### 3.1 Yahoo 429 storm — shared gate not exclusive

**File:** `atlas/investment/yahoo_fundamentals.py` (`YahooRateGate`)  
**Live:** `investment/fundamentals/yahoo_rate_gate.json`

| Field | Value |
|-------|--------|
| consecutive_blocks | 1524 |
| last_block_status | 429 |
| backoff_s | 900 |

A correct system: one 429 → **stop all Yahoo fundamental probes** → wait → one retry → resume or extend.

Today: FEA, enrich, and other jobs can all tick the same gate. Blocks climb. FEA then idles on cooldown **or** someone else hits Yahoo anyway.

**P0-1:** One shared exclusive lock for **fundamentals** Yahoo (not LTP/chart live marks). While cooldown: FEA `idle: yahoo_cooldown — try Screener import`. No parallel enrich. Success resets `consecutive_blocks`.

Do **not** disable live-mark Yahoo priority for RTH charts if that path is separate (`YAHOO_PRIORITY_LIVE_MARKS`). Do not point PE/FCF at Zerodha.

### 3.2 UQ materiality prune kills SMA candidates

**Files:**  
`atlas/investment/uncertainty_queue.py` `prune_non_material_pending`  
`atlas/workers/paper_trading.py` (~1425–1581)

Material set today:

```text
Next-₹1 destination  ∪  open holdings
```

Then:

```text
prune_non_material_pending(material_symbols)
→ PENDING outside that set = NOT_WORTHWHILE
```

Swing book is **flat**. Next-₹1 is often cash. So HBLPOWER / YESBANK / JUBLPHARMA / COALINDIA — the names SMA actually wanted — are **not material** and get pruned (35 `NOT_WORTHWHILE` vs 5 TATACHEM `PENDING`).

That definition was written for Next-₹1 capital advice, not for “PLC.A needs PE on this SMA BUY.”

**P0-2 — new materiality (proposed lock):**

```text
UQ material =
    Next-₹1 destination
  ∪ open positions
  ∪ current SMA / engine BUY candidates this tick
  ∪ planned BUY candidates (session plan)
  ∪ PLC.A-blocked names this IST day (blocked_buy)
```

Priority (drain order, not prune):

1. Open-book / SMA BUY + PLC.A incomplete  
2. Planned BUY  
3. Next-₹1 destination  
4. Open holds  
5. Background (never prune 1–2)

Keep `NOT_WORTHWHILE` for true watchlist spam. Do **not** enqueue the whole NIFTY50 every tick.

### 3.3 D/E is required by PLC.A and missing from UQ

| Layer | D/E? |
|-------|------|
| PLC.A (`plc_buy_gates.py`) | **required** `debt_to_equity` |
| FEA policy `ACQUIRABLE_FIELDS` | includes `debt_to_equity` |
| `FIELD_TO_UQ_CODE` | **no** `debt_to_equity` |
| completeness `_UQ_CODE` | pe, fcf, mos, roe, identity, pb — **no debt** |
| UQ `MATERIAL_UNKNOWN_CODES` | **no** `debt_missing` |

COALINDIA can have PE and still die on ROE+D/E, and **no D/E task is created**.

**P0-3:** Add `debt_missing` ↔ `debt_to_equity` end-to-end: completeness → UQ material → FEA drain → store → PLC.A re-read. Do not invent D/E.

### 3.4 TATACHEM UQ lifecycle

Five PENDING: `pe_missing`, `roe_missing`, `fcf_missing`, `mos_unknown`, `identity_unknown`.

Need to distinguish on the **next** live tick (after P0-1/2):

| Field | Likely class |
|-------|----------------|
| pe / roe / fcf | Yahoo 429 → no acquire |
| mos_unknown | IRA compute, not Yahoo fetch — may sit PENDING forever |
| identity_unknown | Must **DONE** if identity pack is AVAILABLE; else stay PENDING with last_error |

**P0-4:** Close UQ when the store already has the field or the field is not acquirable (mos → compute/IRA, not Yahoo). Identity: if AVAILABLE, mark DONE.

**P0-5:** Every UQ row: `attempt_count`, `last_attempt_at`, `last_error`, `provider`, `status`. Distinguish waiting vs broken.

### 3.5 FEA drain set is narrower than PLC.A

Worker note: `no PENDING UQ pe/fcf/roe tasks`. Drain maps via `CODE_TO_FIELD`. Mos/identity are not Yahoo acquires. D/E never queued (3.3).

**Do not** make FEA fetch MoS from Yahoo. MoS stays IRA.

---

## 4. What Atlas should show (pipeline KPI)

Replace “0 fills” as the only operator sentence.

```text
SWING PIPELINE (IST day)
Universe                N
SMA / technical BUY     N
PLC.A complete          N
PLC.A incomplete        N   ← evidence acquisition
Research HOLD           N
MoS unavailable         N
MoS negative            N
Lab policy AVOID        N
Authorized BUY          N
Paper fills             N
```

Per blocked name:

```text
SYMBOL   SMA   PLC.A   MISSING        UQ          RESEARCH   MoS    FINAL
HBLPOWER BUY   fail    pe,roe,d/e,sec NONE        —          —      plc_a_hold
```

This is a **diagnostic**, not a new trading brain. Prefer evening / session notes / ops JSON first; UI second.

**Do not implement the dashboard in the first P0 slice** unless the data contract (`swing_pipeline.json`) is trivial to emit from existing packets + UQ + PLC.A tags.

---

## 5. Screener import (controlled probe, not the architecture)

Operator export for the **blocked SMA names** is still the fastest way to prove:

```text
fundamentals_incomplete → row present → IRA → MoS → PLC.A re-eval → BUY or HOLD
```

That is a **verification experiment**, not “Atlas will be fed CSV forever.”

After import, **do not stop at “CSV imported.”** Require: store row → completeness → PLC.A tag change on the next swing tick (or a dry replay). If PLC.A still says incomplete, the consumer (wrong symbol key, stale cache, IRA not refreshed) is the bug.

Yahoo remains preferred network source **when the gate is healthy**. Filings stay deferred.

---

## 6. F&O universe (parallel track, not “later after RL”)

### 6.1 Current contract (why one underlier)

| Piece | Behavior |
|-------|----------|
| `fno_contract.py` `UNDERLYING` | `"NIFTY"` |
| `is_phase1_underlying` | NIFTY aliases only |
| reject | `phase1_nifty_only` for BANKNIFTY / FINNIFTY / MIDCPNIFTY |
| ATM | same expiry as nearest FUT, strike step 50, CE+PE, **no writing** |
| Live 18 Sep | `NIFTY26SEPFUT` + ATM 23350 CE/PE; paper PE fill |

`portfolios.py` **already seeds** NIFTY **and** BANKNIFTY for empty F&O books. The resolver then rejects BANKNIFTY. That is a connect bug relative to the seed, not “we forgot BANKNIFTY exists.”

### 6.2 Revised lock (proposed) — replace LAB-LOOP0 L28 “NIFTY only”

**F&O Phase 3 — index universe, paper only**

| Allowed now | Later | Still forbidden |
|-------------|-------|-----------------|
| NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY | selected liquid stock FUT/opt after a liquidity gate | live orders, option **writing**, LLM→trade, mixing F&O into equity FEL, inventing tokens |

Per underlier, reuse the **same** resolver (no second system):

```text
underlier
  → Kite NFO instrument master
  → nearest unexpired FUT (token, expiry, lot)
  → ATM CE + PE (same expiry, family strike step)
  → paper 1 lot, premium debit, no index-proxy marks on options
```

Persist **per underlier** (`NIFTY.json`, `BANKNIFTY.json`, dated). Do not persist the full options chain.

Strike steps are **family-specific** (NIFTY 50, BANKNIFTY historically 100 — read from the dump, do not hardcode one step for all).

Liquidity (Phase 3a minimum): skip a contract if LTP missing. Do **not** invent a full OI/spread engine in the first slice.

Stock F&O = **Phase 3b**, after four index underlyings produce reconstructable experiences.

### 6.3 Isolation (unchanged)

- Cash names never enter the F&O book (Bosch rule).  
- F&O paper fills never go into equity FEL datasets.  
- Experience row must carry `underlying`, `tradingsymbol`, `expiry`, `strike`, `right`, `lot_size`, `strategy_version`, `laboratory_id`.

### 6.4 Why expand now

Waiting for “perfect learning” before generating F&O diversity starves FEL. Collect **clean** index-F&O experiences now; learn later. Do not expand until P0-1/2 are at least **in code** so we are not debugging Yahoo 429 and four underlyings on the same night with no isolation.

**Proposed schedule:** F&O Phase 3a **in parallel** with FEA P0, after Yahoo gate is exclusive (so F&O LTP does not share the fundamentals 429 storm). Zerodha quote path for NFO is already separate from Yahoo PE.

---

## 7. RAG / LLM (closed for this phase)

| Concept | Status |
|---------|--------|
| STORED | Finding `F-002118` |
| EMBEDDED | `finding_embeddings` |
| RETRIEVABLE / RETRIEVED after restart | Hit #1 |
| SENT TO LLM / USED IN ANSWER | Cited `[1]` |
| USED IN TRADING DECISION | **No** — correct |

Do not build more RAG. Do not start another Step 11 bounce. Embed backfill may continue in the background.

---

## 8. Two parallel workstreams (locked order inside each)

```text
              DATA REPAIR                    F&O INDEX UNIVERSE
             /            \                         |
            ↓              ↓                        ↓
     Yahoo exclusive    UQ materiality        Parameterize underlyings
     gate (P0-1)        + D/E (P0-2/3)        NIFTY..MIDCPNIFTY
            ↓              ↓                        ↓
            └──────┬───────┘                  ATM CE/PE per family
                   ↓                                ↓
            SMA BUY → UQ → FEA                      paper experiences
                   ↓                                (lab-isolated)
            PLC.A honest BUY/HOLD
                   ↓
            swing pipeline JSON
                   ↓
                 FEL later (still cash vs F&O split)
```

**P1 after P0:** Zerodha → dated bar_store proof if still thin; swing pipeline on evening mail; stock F&O liquidity gate.

**Not this phase:** RL, LLM trading, PLC.A off, Screener scrape, BANKNIFTY writing, mixing labs in FEL.

---

## 9. Implementation slices (only after §14 lock)

Do not start until the operator table is checked.

### Slice A — Yahoo exclusive fundamentals gate

- Shared lock for FEA + `fundamentals_enrich` + any other PE/FCF Yahoo caller  
- Cooldown → zero network; journal once per cooldown, not 1524  
- Tests: two workers cannot both increment `consecutive_blocks` during cooldown  

### Slice B — UQ materiality for lab decisions

- Extend material set (P0-2)  
- Stop pruning SMA/PLC.A-blocked names  
- Tests: HBLPOWER SMA BUY → UQ pe/roe/debt **PENDING**, not NOT_WORTHWHILE, even if Next-₹1 is CASH and book is flat  

### Slice C — D/E in the acquisition chain

- `_UQ_CODE["debt"] = "debt_missing"`  
- `MATERIAL_UNKNOWN_CODES` + `FIELD_TO_UQ_CODE`  
- FEA drain already has `CODE_TO_FIELD["debt_missing"]` — wire the emitters  
- Tests: COALINDIA missing D/E → task created → (fake Yahoo) row → PLC.A field present  

### Slice D — UQ diagnostics + lifecycle

- attempt/error/provider on task  
- mos_unknown not sent to Yahoo  
- identity DONE when AVAILABLE  

### Slice E — Swing pipeline artifact

- `investment/decisions/pipeline/{lab}/{ist_date}.json` from existing packets + UQ  
- No UI required in this slice  

### Slice F — F&O Phase 3a

- Replace `is_phase1_underlying` with `is_index_underlier(family)`  
- Config list: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY  
- Honor `portfolios.py` seed instead of rejecting BANKNIFTY  
- Strike step from instrument dump / family table  
- Tests: BANKNIFTY nearest FUT not `phase1_nifty_only`; cash BOSCH still rejected; equity FEL still excludes F&O  

### Slice G — Operator Screener probe (ops, not code)

- Import blocked names  
- Prove PLC.A tag change  
- Document in this file’s evidence appendix  

---

## 10. Tests that must exist before calling a slice done

| Slice | Test |
|-------|------|
| A | Cooldown blocks second fundamentals Yahoo caller; live-mark path not required to share that lock |
| B | Flat swing book + SMA BUY HBLPOWER → UQ created; prune does not close it |
| C | `debt_missing` round-trip; PLC.A sees D/E after store write |
| D | identity AVAILABLE closes `identity_unknown`; mos not Yahoo |
| E | Pipeline JSON counts plc_a_incomplete vs engine_hold |
| F | Four index FUT resolvers; NIFTY ATM still works; no cash in F&O book |

---

## 11. Changes that must not be made

- Disable or soften PLC.A / WATCH / MoS / thesis AVOID  
- LLM or Next-₹1 placing orders  
- RL / PyTorch / new learning product  
- Screener HTML scrape  
- Silent Yahoo substitute for Zerodha LTP  
- Treat Zerodha as PE/FCF  
- Dump trades into pgvector  
- Smash findings into chunks  
- Mix F&O P&L into equity FEL  
- Option writing  
- Live broker orders  
- Stock F&O without a liquidity gate (Phase 3b)  
- “Fix” swing by forcing fills on incomplete evidence  
- Universe-scale NSE crawl or HTML scrape of result pages  
- A second paid fundamentals API  
- Store vendor PE as unquestioned truth (Atlas calculates; Yahoo/Screener cross-check; `fundamental_conflict` on mismatch)  

---

## 12. Files likely to change (after lock)

| Slice | Files |
|-------|--------|
| A | `yahoo_fundamentals.py`, FEA worker, `fundamentals_enrich` worker, `test_yahoo_rate_gate.py` |
| B | `uncertainty_queue.py`, `paper_trading.py` (material set), `test_parallel_intelligence_tracks.py`, `test_lab_loop0_blocked_buy.py` |
| C | `evidence_completeness.py`, FEA policy, **NSE/XBRL provider + D/E calc** (after weekend lock) |
| D | `uncertainty_queue.py`, FEA runner |
| E | `session_notes.py` or small `swing_pipeline.py`, evening header |
| F | `fno_contract.py`, `zerodha_feed.py` option listing, `paper_trading.py` overlay, `portfolios.py` notes, `test_lab_loop0_fno_contract.py` |

---

## 13. How we will know it worked

**Equity (one name, e.g. HBLPOWER):**

```text
SMA BUY
  → PLC.A blocked (honest)
  → UQ pe/roe/debt/fcf PENDING (not pruned)
  → FEA → NSE/XBRL (Yahoo fallback) → parse → Atlas calc
  → store + provenance
  → IRA / completeness
  → PLC.A re-evaluates
  → BUY or HOLD
```

If the last line is HOLD for MoS/research/AVOID, **that is success**. If it stays `fundamentals_incomplete` with a full row, **that is a consumer bug**.

**F&O:**

```text
BANKNIFTY → FUT token/expiry → ATM CE/PE → paper state → experience
(same for FINNIFTY / MIDCPNIFTY)
NIFTY path still works
cash still rejected
```

**Not the test:** “Atlas traded.”

---

## 14. Operator lock

| ID | Decision | Lock |
|----|----------|------|
| **L1** | PLC.A / WATCH / MoS / live orders / RL / LLM-trade unchanged | **LOCKED 2026-09-18** |
| **L2** | UQ materiality includes SMA BUY + PLC.A-blocked + plan names | **LOCKED** |
| **L3** | Shared exclusive Yahoo **fundamentals** gate | **LOCKED** |
| **L4** | `debt_missing` completeness → UQ → FEA | **LOCKED** |
| **L5** | UQ attempt/error/provider + close stale mos/identity | **LOCKED** |
| **L6** | Swing pipeline JSON this phase (UI later) | **LOCKED** |
| **L7** | F&O Phase 3a: four index underlyings, paper, no writing, same resolver | **LOCKED** |
| **L8** | Stock F&O **not this phase** | **LOCKED** |
| **L9** | Screener import = probe/bootstrap, then prove PLC.A re-eval — not the permanent engine | **LOCKED** |
| **L10** | Step 11 closed; no RAG/RL work in this phase | **LOCKED** |
| **L11** | Fundamental Intelligence **vertical slice (NSE/XBRL + Atlas calc + hourly FI mail)** is P0; universe/taxonomies-at-scale still later | **AMENDED 2026-09-18 evening** |

A–F plumbing is in tree. Next work (after [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md) **§15 lock**): **NSE/XBRL vertical slice + correctness (L26–L35) + hourly FUNDAMENTAL INTELLIGENCE block.** Do not start universe downloaders.

---

## 15. Decision log

| Date | Decision | Notes |
|------|----------|-------|
| 2026-09-18 | Discussion opened | After forensic: FEA ticks but 0 acquire; UQ prune; D/E gap; Yahoo 1524×429; F&O NIFTY-only by code; Step 11 live |
| 2026-09-18 | Step 11 closed | Bounce×2: retrieve + LLM cite |
| 2026-09-18 | **Correctness before §15 lock** | Sector/identity, TTM EPS, avg equity, D/E map, filing selection, `available_at`, negative tests, 18-Sep candidate replay. Still **no code** until weekend-discussion §15 lock. |

---

## 16. Learning (two meanings — do not mix)

| Type | Path | This phase |
|------|------|------------|
| **A — scientific trading learning** | paper → experience → outcome → reward → FEL → hypothesis → walk-forward → finding | **Enable by supplying clean experiences** (equity + four index F&O). Do not wait for a perfect learner first. |
| **B — LLM remembers learning** | validated finding → embedding → RAG → LLM → research/context | **Already live-proven** (Step 11). Do not rebuild. LLM still does not BUY/SELL. |

RL remains frozen until enough Type-A data exists to ask “what strategy survives?”

---

## 17. Fundamental Intelligence (vertical slice this weekend; universe later)

Screener stays a **verification instrument**. Yahoo stays a **paced fallback**. **NSE/XBRL is primary raw evidence** for the vertical slice:

```text
NSE XBRL / filings / Yahoo statements
        → raw evidence (kept)
        → canonical facts (period, scope, unit, source)
        → Atlas calculates PE / ROE / D/E / FCF
        → cross-check Yahoo/Screener (conflict ≠ silent overwrite)
        → IRA → PLC.A
```

Full design: [`ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md`](ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md). Weekend proof: [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md).

**This weekend does not:** scrape NSE HTML as the engine, parse XBRL at universe scale, add Postgres fact warehouses, or replace FEA with a second product. **This weekend does:** HBLPOWER (then 1–2 more) NSE → facts → calc → PLC.A, and **hourly mail showing the counts**.

---

## 18. One-line north star for this phase

> Make a technical BUY that is missing PE/ROE/D/E/FCF become a UQ task, obtain **NSE filing evidence**, calculate the metrics with provenance, and let PLC.A decide BUY or HOLD — and let the F&O lab resolve BANKNIFTY the same way it already resolves NIFTY — without ever pretending missing data is a strategy result. The hourly email is how we see whether that happened.
