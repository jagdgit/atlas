# Atlas Improvement Discussion & Implementation Plan

> **Status:** 🔒 **CONTRACTS LOCKED** · Phase 1 `OI-MDPH0` **in code** (MDPH.1–7 core + tests)  
> **Date:** 2026-09-03 (rev 2 — operator locks + MDPH extensions)  
> **Codename:** `OI-MDPH0` (Market Data Provider Health) + learning/lab integrity follow-ons  
> **Parents:** [`ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md`](ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md) ·  
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) ·  
> [`ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md`](ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md) ·  
> [`UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md`](UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md) ·  
> [`ATLAS_INCUMBENT_COMPETITION_AND_CAPITAL_REALLOCATION_PLAN.md`](ATLAS_INCUMBENT_COMPETITION_AND_CAPITAL_REALLOCATION_PLAN.md) ·  
> [`ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md`](ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md) ·  
> [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md)  
> **Does not reopen:** SMA/RSI control auto-mutation · inventing PE/FCF · browser automation of Zerodha login/2FA · adding capital · silent strategy V2 · RL / new signal zoo  
> **Unit of truth:** what Atlas actually saw → where capital goes competitively → what it proved it learned — not tick counts, IQ scores, or trade frequency

---

## 0. Locked north star

```text
Make Atlas trustworthy about what it saw
  → make it competitive about where capital goes
  → make it prove what it learned.

Not: make Atlas trade more.
```

**Contracts remain locked.** Phase 1 code lives under `atlas/investment/market_data_provider_health.py` (+ gate/API/UI/tests).
---

## 1. LOCKED decisions (operator 2026-09-03)

| Item | Decision |
|------|----------|
| Zerodha unavailable → intraday/F&O **pause** | 🔒 **YES** (not soft Yahoo degrade) |
| Silent Yahoo substitution for live-required | 🔒 **NO** |
| CYIENT cooldown as primary fix | 🔒 **NO** |
| Competition instead of cooldown | 🔒 **YES** |
| Five genuine learning records before claiming learning | 🔒 **YES** (see L0–L5 quality) |
| No strategy mutation / Strategy V2 | 🔒 **YES** |
| No additional capital | 🔒 **YES** |
| Human Zerodha 2FA only (no credential automation) | 🔒 **YES** |
| Live vs non-live split is a **lab contract**, not only a provider rule | 🔒 **YES** |

### Explicit lab-level `live_required` contract

```text
                    Provider Health
                         │
          ┌──────────────┴──────────────┐
          ↓                             ↓
   LIVE-REQUIRED                   NON-LIVE
   intraday / F&O                  swing / research / densify / fundamentals
          │                             │
       PAUSE if not READY            CONTINUE
       (no silent Yahoo)             (Yahoo / bar_store / Screener OK when labeled)
```

**Not:** “Zerodha down = Atlas stops everything.”  
**Yes:** live-required lanes pause; non-live lanes continue on labeled alternate sources.

Causal integrity: if Zerodha was required and Yahoo was used silently, a later learning record cannot answer *“was the decision made from the data source the experiment required?”*

---

## 2. Where Atlas actually is (context)

| Layer | State | Score |
|-------|-------|-------|
| Infrastructure / scheduler | Working | 🟢 |
| Paper trading safety | Mostly working | 🟢 |
| Market-data coverage | Improving, incomplete | 🟡 |
| Decision engine | Working, conservative | 🟡 |
| Learning system | Instrumented, barely proven | 🔴 |
| Intelligence / capital allocation | Emerging | 🟡/🔴 |

Activity (LLM calls, revisits, journal buckets, IQ) ≠ learning. **`learning_records = 0`** remains the headline honesty metric until L5 records exist.

---

## 3. Host restart forensics (2026-09-03 morning)

| Fact | Detail |
|------|--------|
| New boot | **2026-09-03 08:49 IST** |
| Previous session | Ended as **`crash`** (unclean) after ~12h44m |
| Journal | Stops ~08:46 mid-normal activity; **no** OOM / panic / soft-lockup found |
| Pattern | Multiple prior unclean `crash` endings over ~2 weeks |

**Interpretation:** hard hang / power glitch / forced cycle — **not** Atlas requesting reboot. Recurring unclean boots are a platform risk for tokens, paper books, and learning continuity.

### Post-crash reconciliation (acceptance — ADD)

```text
HOST CRASH
  ↓ system boots
  ↓ Postgres healthy
  ↓ Atlas services healthy
  ↓ Zerodha session state checked
  ↓ instrument master checked
  ↓ paper books reconciled
  ↓ scheduler state reconciled
  ↓ Atlas declares READY / DEGRADED / LOGIN_REQUIRED
```

Do not accept merely “process restarted.” Require **operating-state reconstruction**.

---

## 4. MarketDataProviderHealth (`OI-MDPH0`)

### 4.1 Intention

Atlas owns everything **around** auth. Human owns **only** login/2FA click.

```text
Pre-market probe (~08:00 IST)
  → token for IST day?
       YES + probes PASS → READY
       NO / fail auth → LOGIN_REQUIRED → CTA /zerodha/login
  → human authenticates once
  → callback → access_token stored (day-scoped)
  → LTP smoke + instrument VALID
  → READY → resume live-required workers
```

### 4.2 Status object

```text
Provider:              Zerodha
Trading date (IST):    2026-09-03
Status:                READY | LOGIN_REQUIRED | EXPIRED | DEGRADED | ERROR
Token valid:           YES/NO
LTP probe:             PASS/FAIL
Last successful LTP:   …
Last LTP as_of:        …
Last LTP received_at:  …
Freshness:             FRESH | STALE | UNKNOWN
Freshness threshold:   (config, e.g. max age_ms for LIVE_LTP)
Instrument master:     VALID | INVALID | STALE
WebSocket:             PASS/FAIL/N/A (later)
Login URL:             /zerodha/login
Required by labs:      [intraday live_required, fno live_required, …]
```

### 4.3 Data freshness contract (ADD — LOCK)

`READY` alone is insufficient. Provider healthy ≠ observation healthy.

Every live decision packet (and every market observation that can influence a decision) must carry:

```text
provider          = zerodha
provider_status   = READY
symbol            = CYIENT.NS
price             = …
as_of             = 09:27:14
received_at       = 09:27:15
age_ms            = 1000
market_session    = RTH
data_class        = LIVE_LTP
freshness         = FRESH | STALE | UNKNOWN
instrument_version / dump_date = …
```

Stale daily bars under Yahoo cooldown were already a data-plane failure mode; MDPH must not recreate “healthy provider, rotten observation.”

If `freshness = STALE` on a live-required path → treat like provider failure for that decision (`DATA_STALE` / `NOT_EVALUABLE`), not as a valid live fill input.

### 4.4 Provider provenance (MDPH.6 — strengthened)

Not only “Zerodha READY” on the packet header.

Every consumed market observation:

```text
source_provider   = zerodha
source_endpoint   = ltp | quote | ohlc | …
provider_status   = READY
retrieved_at      = …
as_of             = …
instrument_token  = …
instrument_version= …
```

Six months later Atlas must answer: *what exact data did it see when it predicted?*  
Ties to ACP provenance: candidates → E[R] → evidence → technical/research → scientist → decision.

### 4.5 State-transition rules (ADD — LOCK)

Deterministic controller, not ad-hoc status strings.

| From | Trigger | To |
|------|---------|-----|
| (none) / boot | Missing token for IST day | `LOGIN_REQUIRED` |
| `LOGIN_REQUIRED` | Successful callback + LTP PASS + instrument VALID | `READY` |
| any | Token present but auth/session rejected | `EXPIRED` → treat as login needed |
| `READY` | Transient LTP failure (single) | candidate `DEGRADED` → **reprobe** (do not thrash) |
| `DEGRADED` | Reprobe majority PASS (e.g. ≥2/3) | `READY` |
| `DEGRADED` | Persistent failures | `ERROR` |
| `ERROR` | Successful re-auth and/or sustained reprobe PASS | `READY` |
| `READY` | Midnight IST day roll | `EXPIRED` / next-day `LOGIN_REQUIRED` |

**Hysteresis:** one HTTP blip must not cascade chaos. DEGRADED pauses live-required lanes while recovery probes run.

### 4.6 Mid-session recovery / reprobe (MDPH.7 — ADD)

```text
READY → LTP failures → DEGRADED
  → reprobe every N seconds/minutes
  → PASS → READY → resume live workers
  → persistent FAIL → ERROR → remain paused + notify
```

Purpose of MDPH is to remove the morning ritual **and** the mid-day “is Zerodha back?” ritual.

### 4.7 Decision invalid because data unavailable (ADD — LOCK)

Operational failure ≠ investment failure.

If CYIENT looks best but provider is down / data STALE:

```text
decision_status = NOT_EVALUABLE
reason_code     = PROVIDER_UNAVAILABLE | PROVIDER_LOGIN_REQUIRED | …
```

**Not** a CYIENT prediction with unknown outcome.  
**Not** a “missed opportunity” investment learning row by default.

#### Reason codes (minimum)

| Code | Class |
|------|--------|
| `PROVIDER_LOGIN_REQUIRED` | operational |
| `PROVIDER_DEGRADED` | operational |
| `PROVIDER_ERROR` | operational |
| `DATA_STALE` | operational |
| `INSTRUMENT_STALE` / `INSTRUMENT_INVALID` | operational |
| `SESSION_CLOSED` | operational / session |
| `INSUFFICIENT_EVIDENCE` | investment |
| `NO_ALLOCATION_EDGE` | investment |
| `THESIS_REJECTED` | investment |
| `CHALLENGER_NOT_BETTER` | investment |
| `CASH_BEST` | investment |

Learning Auditor must never confuse “no trade because login” with “no trade because thesis.”

### 4.8 Instrument master integrity (MDPH.5 — strengthened)

Not “HTTP 200 + file exists.”

```text
download → parse → validate columns/count
  → validate exchanges (NSE/BSE/…)
  → validate symbols used by active labs
  → validate token mapping
  → ACTIVE (VALID)
```

Per active symbol:

```text
CYIENT.NS → exchange=NSE → instrument_token=… 
  → dump_date=2026-09-03 → mapping_status=VALID
```

Status: **`VALID` / `INVALID` / `STALE`** (replace weak PASS/FAIL/STALE dump-only language).

### 4.9 Notifications

| Time (IST) | Action |
|------------|--------|
| ~08:00 | Premarket probe; LOGIN_REQUIRED → UI CTA |
| ~09:00 | Still LOGIN_REQUIRED → escalate (ops + optional email) |
| Callback / recovery → READY | Clear alerts; resume live lanes |
| Midnight | Day roll → EXPIRED |

**No** Playwright/TOTP automation.

### 4.10 MDPH implementation slices

| ID | Slice |
|----|-------|
| MDPH.1 | `MarketDataProviderHealth` model + persist + status API |
| MDPH.2 | Premarket probe + UI banner CTA |
| MDPH.3 | Lab `live_required` gate; pause; no silent Yahoo |
| MDPH.4 | Login callback / day-scoped token reuse + LTP smoke |
| MDPH.5 | Instrument master refresh + VALID/INVALID/STALE validation |
| MDPH.6 | Packet + observation provenance (provider, as_of, received_at, freshness, instrument version) |
| MDPH.7 | Mid-session DEGRADED reprobe / recovery + resume |
| MDPH.8 | Optional 09:00 email escalate |
| MDPH.9 | Post-crash operating-state reconciliation checklist |

---

## 5. Lab stuckness (unchanged diagnosis; tightened acceptances)

### 5.1 Swing

Safe HOLD under `thesis_gated` + `fcf_missing` is mechanical success and intelligence gap. Prefer **uncertainty → acquisition**, not gate relaxation.

### 5.2 Intraday CYIENT — competition gate (acceptance)

🔒 No primary cooldown.

**Every intraday re-entry must show:**

```text
candidate_set
  → scores (incl. CYIENT, others, CASH)
  → winner
  → decision
```

Example:

```text
CYIENT 0.31% · INFY 0.24% · RELIANCE 0.11% · CASH 0.00% → CYIENT wins (earned)
next day INFY 0.38% … → INFY wins
```

Objective: **anti-unearned-incumbency**, not anti-CYIENT.

### 5.3 F&O — acceptance (ADD)

Every F&O learning / allocation path must identify:

```text
instrument → expiry → contract → direction → entry → mark → exit → outcome → attribution
```

**Prohibit:** cash-equity candidate feeding F&O allocator.  
Historical NIFTY proxy contamination by cash-equity concentration logic must not recur.

---

## 6. Learning quality (strengthened milestone)

### 6.1 Two learning categories (ADD — LOCK)

| Category | Examples | Counts toward “5 investment learning records”? |
|----------|----------|-----------------------------------------------|
| **SYSTEM LEARNING** | provider reliability, 429, scheduler, inference, data quality, resources | **NO** |
| **INVESTMENT LEARNING** | prediction, outcome, attribution, thesis, opportunity cost, allocation | **YES** |

Operational lessons are valuable and should be audited — separately.

### 6.2 Levels L0–L5 (ADD — LOCK)

| Level | Meaning |
|-------|---------|
| L0 | Event logged |
| L1 | Prediction + outcome |
| L2 | + attribution |
| L3 | + candidate lesson |
| L4 | + belief/rule candidate |
| L5 | + subsequent test / validation |

**Headline milestone:** **5 independent L5 investment learning records** — not five rows, not five evaluations of one CYIENT day.

Independence: distinct qualifying decision/experiment (not same `state_hash` / evidence / thesis five times; not buy/trim/flatten/rebuy/trim of one sequence as five).

Aligned with ICR: identical state/evidence/challenger conditions ≠ separate learning events.

Do **not** manufacture trades to hit five. `2/5 — three more required` is a successful honest audit.

### 6.3 Report front page

1. What predicted?  
2. What happened?  
3. Why right/wrong?  
4. What changed?  
5. Did change improve next prediction?  

Else: `Learning: NONE — no qualifying closed prediction today.`

### 6.4 Five scoreboards

System maturity · Evidence quality · Decision quality · Learning quality · Economic quality.  
Rename “IQ” over time to system-maturity language.

### 6.5 Ollama

Beside deterministic core, not above it. Economic question: *did advice cause a better decision than deterministic-alone?* — later LLM ON vs OFF. Not “good prose.”

---

## 7. Implementation phases (revised order)

### Phase 0 — Lock contracts (before coding) ✅ this rev

1. Live-required lab definition  
2. Provider state machine  
3. Freshness contract  
4. Fallback/degradation (PAUSE live / CONTINUE non-live)  
5. Failure reason codes + `NOT_EVALUABLE`  
6. Decision-packet / observation provenance  

### Phase 1 — MDPH core

MDPH.1–MDPH.7 (+ MDPH.8 optional, MDPH.9 crash reconcile).

Acceptance sketch:

- No token → LOGIN_REQUIRED → CTA  
- Login → LTP + instrument VALID → READY  
- Mid-session failure → DEGRADED → live pause → reprobe  
- Recovery → READY → resume  
- **Silent live-data substitution count = 0**

### Phase 2 — MDPH observation period (~5 trading sessions)

**Status:** 🟡 **VALIDATION TRACK** (session 1/5 as of 2026-09-03) — **not a development freeze**.

**Operator surface:** `GET /zerodha/observation` · Ops Zerodha panel ·  
`{data}/investment/market_data_provider/phase2_verify.json`

**Principle (locked 2026-09-03):** *Don't wait to implement. Wait to trust.*  
Phase 2 accumulates MDPH observation in the background. Phases 3–7 **implement in parallel**; each component has its own ladder:

`IMPLEMENTED → TESTED → OBSERVED → VALIDATED → ACTIVE`

**Hard gates (never bypass while observing):** no strategy mutation · no capital increase · no silent Yahoo · no premature L5 claims · no Zerodha 2FA bots · `NOT_EVALUABLE` ≠ investment failure.

**Measure (passive):**

- login detection / CTA / LTP / hist / instrument success  
- false READY / false DEGRADED rates  
- live pause correctness / recovery correctness  
- **Silent live-data substitution = 0**

### Parallel intelligence tracks (implement now; activate on own acceptance)

| Track | Build now | Active when |
|-------|-----------|-------------|
| MDPH P2 | Observe | 5 READY sessions + silent Yahoo = 0 |
| Learning L3→L5 | Belief candidate + subsequent-test validator | Independent L5 records exist (honest 0 OK) |
| Uncertainty queue | Unknown → importance → acquisition task | Tasks created for material unknowns (FCF…) |
| Opportunity competition | candidate_set → scores → winner | Every intraday re-entry shows set/winner |
| Evidence lineage | observation/evidence IDs on packets | Material claims cite provenance |
| LLM attribution | advice → accepted? → changed? → outcome | Measurement only; never decides trades |

### Flow + capacity audit (locked 2026-09-03) — *not* an intelligence-feature session

**Principle:** Sight and thinking machinery exist. The immediate problem is **flow** (today's observations → decision packets) and **capacity discipline** (starved/zombie work + archive invariant). Do **not** respond with more models, GPU, workers, strategies, capital, or universe expansion.

| Priority | Item | Root cause / fix |
|----------|------|------------------|
| 🔴 P0 | Intraday Next-₹1 / competition refresh | Flat book early-return skipped economic center — **fixed**: empty holds still build challenger table → Next-₹1 → competition |
| 🔴 P0 | Scheduler starvation honesty | Flat 6h “starved” false-positives on weekly mentors/meta — **fixed**: cadence-aware `waiting_schedule`; ops cleanup for true duplicates (do not raise concurrency) |
| 🔴 P0 | Archive RTH `running ≤ max` | Clamp was admit/display-only; overnight 2 survived into RTH — **fixed**: `HostGuard._enforce_archive_cap` demotes excess |
| 🟠 P1 | Scientist drain | AttributeError/non-JSON forever-retriable — **fixed**: `failed_permanent` after max attempts; retire historical leftovers; exclude from retriable |
| 🟠 P1 | Uncertainty queue feed | Upstream packet skip — **fixed**: enqueue from ER gaps + awareness on Next-₹1 path (incl. flat book) |
| 🟠 P1 | Competition snapshot | Same as Next-₹1 gate — rides P0 fix |
| 🟡 P2 | F&O contract lineage | Remaining acceptance — no cash-equity contamination |
| 🟡 P2 | Lineage metrics / LLM attribution accumulate | Stubs live; measure obs_cite % / advice→outcome |
| 🔵 BG | Phase 2 MDPH | Passive only — 1/5, silent Yahoo = 0 |

**Scientist policy:** `RETRIABLE → max attempts → FAILED_PERMANENT → reason recorded → continue`. Goal is not 100% scientist success; failed cognitive work must not consume Atlas's ability to do useful work.

**Starvation taxonomy (ops):** `RUNNABLE` · `BLOCKED` · `STARVED` · `STALE`/`WAITING_SCHEDULE` · `DUPLICATE` · `OBSOLETE` · `WAITING_EXTERNAL`. Prefer classify + pause/dedupe over more tick slots (~15 GB RAM → ~2 preferred slots).

### Phase 3 — Learning Auditor: L3 → L5 machinery

**Status:** 🟢 **IMPLEMENTED** (L4 candidates + OPEN subsequent tests; L5 still gated)  
- Intraday CYIENT → 2× L4 belief candidates with OPEN subsequent tests  
- Headline remains **L5 = 0** until validation passes  

### Phase 4 — Uncertainty → active work queue

**Status:** 🟢 **WIRED** — feed from Next-₹1 / ACP / awareness; activate when pending tasks appear for material unknowns.

```text
unknown → importance → HIGH → acquisition task → packet update → re-evaluate
```

**Acceptance:** every material unknown has a research task, an explicit “not worthwhile” reason, or a deadline/expiry.

### Phase 5 — Opportunity competition

**Status:** 🟢 **WIRED** on Next-₹1 (+ ACP for swing) — flat-book refresh unblocked 2026-09-03.

Universe → candidates → evidence/E[R] → incumbent vs challenger(s) vs cash → switch cost → winner.  
Intraday must show CYIENT in the competitive set when eligible.

### Phase 6 — Evidence lineage

**Status:** 🟢 **STUB LIVE** — stamp on packets/ACPs; measure coverage next (do not overbuild KG).

Material capital-decision claims → prediction → ACP → evidence IDs → observations → source/as_of/provider.

### Phase 7 — LLM economic measurement

**Status:** 🟢 **INSTRUMENTED** — attribution rows on ICR5; `failed_permanent` bounded; never allocation authority.

```text
deterministic baseline ‖ Ollama advice → accepted? → changed anything? → outcome
```

### Explicitly deferred / forbidden

Strategy V2 · RL · capital increase · Zerodha credential bots · GPU until measured ROI · silent live Yahoo · claiming L5 without subsequent validation · **raising concurrency to clear starvation scarlet**.

---

## 8. Locked architecture sketch

```text
                    ┌────────────────────────────┐
                    │ MarketDataProviderHealth   │
                    │ READY / LOGIN_REQUIRED /   │
                    │ DEGRADED / ERROR / EXPIRED │
                    │ + freshness + instruments  │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ↓                           ↓
             LIVE-REQUIRED                NON-LIVE
             intraday / F&O               swing / research
                    │                           │
                 READY?                       continue
              ┌─────┴─────┐
              ↓           ↓
             YES          NO → PAUSE (NOT_EVALUABLE)
              │
         DATA OBSERVATION
         (provider, as_of, received_at,
          freshness, instrument version)
              ↓
           EVIDENCE
              ↓
   ┌──────────┴──────────┐
   ↓                     ↓
deterministic         Ollama scientist
   analysis              (advice only)
   └──────────┬──────────┘
              ↓
         HYPOTHESIS → PREDICTION
              ↓
     INCUMBENT vs CHALLENGER vs CASH
              ↓
           Next ₹1 → DECISION
              ↓
           OUTCOME → ATTRIBUTION
              ↓
     LEARNING RECORD (investment L5 vs system)
              ↓
         BELIEF UPDATE → NEXT DECISION
```

---

## 9. Acceptance criteria checklist

### MDPH

- [x] Premarket LOGIN_REQUIRED → CTA without hunting docs  
- [x] One human login → day-scoped token → LTP smoke → instrument VALID → READY  
- [x] Live-required labs pause with reason codes when not READY / STALE  
- [x] Silent Yahoo live substitution = **0** (blocked + observation counter; live labs default `zerodha`)  
- [x] Freshness + provenance on live observations and packets  
- [x] State machine + mid-session reprobe (DEGRADED → READY/ERROR)  
- [x] Instrument master VALID/INVALID/STALE with per-lab symbol mapping checks  
- [x] Post-crash full operating-state reconciliation (`mdph_reconcile` recovery step)

### Learning / labs

- [ ] 5 **independent L5 investment** records (system lessons separate)  
- [x] Intraday/ACP re-entry persists candidate_set / scores / winner (`competition_snapshot`)  
- [ ] F&O paths contract-identified; no cash-equity candidate contamination  
- [x] Material unknowns → acquisition task queue (`uncertainty_queue`; activate when tasks fire)  
- [x] Decision Evidence Completeness Engine (`evidence_completeness`; contract → gate → UQ)  
- [x] L3 → L4 belief candidate + OPEN subsequent_test (`l5_validation`; L5 still gated)  
- [x] Evidence lineage stub on decision packets / ACPs  
- [x] LLM attribution measurement (advice → accepted? → changed? → outcome; no allocation authority)  

### Host

- [ ] Unclean reboot → reconstructed READY/DEGRADED/LOGIN_REQUIRED, not “process up” only  

---

## 10. Open (non-blocking) ops choices

| Item | Default |
|------|---------|
| 09:00 LOGIN_REQUIRED email | Optional (MDPH.8) — escalate from **06:00 IST** (operator 2FA window); ops panel always shows Login / Force update token |
| Exact DEGRADED reprobe N and 2/3 threshold | Tune in Phase 2 observation; document in config |
| Freshness threshold for LIVE_LTP | Set conservatively in Phase 0 config; refine after Phase 2 |
| UPS / PSU host work | Ops parallel track |

---

## 11. Summary

| Theme | Locked stance |
|-------|----------------|
| Live-required vs non-live | Lab contract: pause live; continue non-live |
| Yahoo | Never silent substitute for live-required |
| MDPH | Health + freshness + provenance + state machine + recovery |
| CYIENT | Compete, don’t cooldown |
| Learning | 5 independent L5 investment records; system lessons separate |
| Sequencing | Contracts → MDPH → 5-session verify → Learning → uncertainty → competition → lineage → LLM ROI |
| Goal | Trustworthy sight → competitive capital → proven learning |

---

## 12. Decision Evidence Completeness Engine (next layer)

MDPH answers: *Can Atlas obtain Zerodha data?*

This layer answers: *For this decision, does Atlas have every required piece of evidence, with provenance?*

### Principle

**Do not download everything.** Per candidate:

```text
DECISION → REQUIRED EVIDENCE → AVAILABLE / STALE / MISSING / CONFLICTING
         → COMPLETE → evaluate
         → INCOMPLETE + material → acquisition task → rebuild → re-evaluate
         → INCOMPLETE + not material → NOT_WORTHWHILE
```

Completeness is **deterministic**. Ollama never decides “enough data?” — it only advises on bounded evidence.

### Module

`atlas/investment/evidence_completeness.py` (`learn.evidence_contract.v1`)

| Lab | Required evidence (from `strategy_contract`, not a mega-checklist) |
|-----|-------------------------------------------------------------------|
| Intraday | live_ltp, bars_intraday, technical_state, session, instrument |
| F&O | live_ltp, bars, underlying, expiry/proxy, cash_equity_excluded |
| Swing | price_history, pe, fcf, mos, sector, thesis, identity (+ material roe/debt) |

Item states: `AVAILABLE` · `STALE` · `MISSING` · `CONFLICTING` · `INVALID` · `NOT_APPLICABLE` · `PENDING_ACQUISITION`

Outputs: `decision_evaluable`, `usable_evidence_pct` (required vs usable — **not** an IQ score), `format_why_not_evaluable`, acquisition codes → existing `uncertainty_queue`.

### Wiring

- Next-₹1 tick: material symbols → completeness gate → UQ enqueue + persist under `investment/evidence_completeness/`
- ACP persist: attach `evidence_completeness` summary + lineage-adjacent packet
- Observation API `parallel_tracks.evidence_completeness`: per-lab rollup

Zerodha remains authoritative for the **market** plane only; Screener/news/research stay labelled non-Zerodha sources.

### Acceptance (this slice)

- [x] Deterministic contract per lab kind  
- [x] WELCORP-style `NOT_EVALUABLE` when MOS missing → `mos_unknown` acquisition  
- [x] Mechanical `why_not_evaluable` operator answer  
- [x] Completeness metric = required vs usable (with reasons)  
- [ ] Runtime: packet rebuild after acquisition closes UQ task (observe on next sessions)

**Next coding step:** Runtime proof of Evidence Completeness on live Next-₹1 / ACP paths (WELCORP / CYIENT). Keep observing Phase 2 MDPH (1/5). Do not add strategies/models/capital.
