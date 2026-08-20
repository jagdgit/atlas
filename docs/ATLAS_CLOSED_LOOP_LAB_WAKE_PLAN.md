# Closed Loop + Lab Wake — Feeds, Experiments, Beliefs in Decisions

> **Status:** 🔒 **LOCKED for implementation** (operator review 2026-08-17 19:44 IST — four tightenings accepted)  
> **Codename:** `OI-LOOP0`  
> **Parents:** [`ATLAS_STABILIZATION_SPRINT_ONE_MARKET_DAY.md`](ATLAS_STABILIZATION_SPRINT_ONE_MARKET_DAY.md) ·
> [`PROFESSIONAL_LABORATORY_CYCLE_PLAN.md`](PROFESSIONAL_LABORATORY_CYCLE_PLAN.md) ·
> [`UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md`](UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md) ·
> [`ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md`](ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md)  
> **Does not reopen:** AGENT-1 freeze · SELF0 **Phase 5 soft influence** freeze · SMA/RSI control lane · inventing prices/fundamentals  
> **Unit of truth:** durable journal + packets + WSO + beliefs — not evening prose

---

## 0. Operator thesis (LOCKED)

The evening report is right.

Atlas is becoming a **persistent cognitive system**. It is **not yet** becoming a better trader.

The missing edge is not “use more LLMs.” It is:

> **Worldview is decorative.** Beliefs, WSO, experiences, and curiosity exist — the trading engine does not consult them when it decides.

Target loop:

```text
Market → Beliefs + WSO + Experiences → Reasoning → Decision → Outcome → Belief revision ↺
```

Today’s loop:

```text
Market → Rules → Decision → Packet → Journal → Reflection (after the fact)
```

**Belief Consultations Today: 0** is the diagnostic. After L2 it must be > 0 for **unique decision states** on a session where Atlas evaluated a name — not once per HOLD tick.

**Judgment of success for this cycle (not P&L):**

| Metric | Today (2026-08-17) | Target after LOOP0 |
|--------|--------------------|--------------------|
| Belief consultations / session | **0** | **≥1 per unique decision state** (even “none found”) — not per HOLD tick |
| Material belief revisions / week | 0 | **≥1 candidate** from outcomes (not auto-applied to size) |
| Switch reviews | blocked `missing_er` | **computable E[R] prototype** with honesty tag |
| Closed trades (all-time) | **3** | experiments allowed; still too few for edge claims |
| Intraday / FNO fills | **0** (labs tick, never fill) | **honest first fills** or honest “cannot fill” with a *fixed* cause |

SELF0 Phase 5 (beliefs **change size/side**) stays frozen until ≥5 consecutive clean STAB0 sessions. LOOP0 **consults** and **records**. It does **not** let beliefs silently trade.

---

## 1. Why today still looks idle (2026-08-17 evidence)

Weekend **15–16 Aug** (Independence Day Saturday + Sunday). **Monday 17 Aug was a live NSE cash session.** Atlas saw it.

| Lab | Ticked? | Fills | What it actually did |
|-----|---------|------:|----------------------|
| `india_equity_learner` | Yes | **0** | Marked CIPLA **₹1,431.50** / book still CIPLA×13 + EICHERMOT×2. Day P&L **−₹273**. Switch: `switch_blocked_missing_er`. PLC.A / research holds on challengers. |
| `equity_intraday_learner` | Yes | **0** | Empty ₹50k. Same **Yahoo 1d** cash bars. After first bar: `mark_only`. Alts: `concentration_name:8.7%>0%`. |
| `india_fno_learner` | Yes | **0** | NIFTY daily **24,287.65**. Cash alts still injected. `max_exposure_pct=0`. HBLPOWER Yahoo **404**. |

Equity **is tracking live daily closes** (CIPLA 14 Aug 1,450 → 17 Aug 1,431.50). That is not a dead telescope.

“Not much activity” = **no fills + thousands of `session_closed` / `mark_only`**. Those are idle *decisions*, not a stopped worker.

---

## 2. What “start” means — three different labs

Do **not** treat “make them start” as one switch.

| Lab | Can start on **daily Yahoo**? | What “started” honestly means |
|-----|------------------------------|-------------------------------|
| **India equity (swing)** | **Yes. Already can.** | Rotate or add when E[R]+gates allow. Blocker is **policy**, not feed. |
| **Equity intraday** | **No.** 1d bar + `mark_only` = one decision per name per day. | Needs **intraday bars** (1m or 5m) **or** we relabel it “same-day cash swing” and stop calling it intraday. |
| **India F&O** | **No as futures.** `^NSEI` daily is an index proxy, not a contract. | Needs **explicit contracts + lot/margin** and an **underlier mark**. True FO quotes are a later vendor. First wake = **index-proxy paper lot** on NIFTY, labeled honestly. |

### 2.1 Immediate unblocks (no vendor, no 1m)

These are why empty labs cannot fill **even if** we ignore feed quality:

| Bug | Effect | Fix |
|-----|--------|-----|
| Template `max_exposure_pct: 0` treated as **0% name cap** | `8.7%>0%` — any proposed buy fails | **Narrow unset:** `None` / missing / template-`0` on `max_exposure_pct` → persona default. **`max_name_pct: 0` stays a hard 0%.** Positive → explicit cap. Do **not** treat every 0 in the process as unset. |
| UTS `expected_return_from_row` returns **None** in `phase=learning` / `confidence=very_low` | Every switch `missing_er` | Prototype E[R] **always emits a number** + `er_basis=prototype` + `er_completeness` |
| FNO `auto_max=0` but ranker still injects **cash alts** | FNO evaluates IDEA/DEVYANI cash | FNO tick: **NIFTY/BANKNIFTY only** — no cash universe alts |
| Intraday uses **1d** Yahoo + `nse_equity` | `mark_only` after first daily bar | Either 1m/5m path (§3) or honest `session_swing` label |
| `HBLPOWER.NS` | Permanent Yahoo **404** | Alias / drop from plan (HBLENGINE or remove) |
| PLC.A on equity challengers | `debt_to_equity` incomplete | Keep fail-closed for **new swing buys**; do **not** copy PLC.A onto FNO/intraday (already skipped in code — keep it) |

Equity can **start rotating** after the E[R] prototype + consult wire. It does **not** wait on 1-minute data.

---

## 3. Does Atlas need live 1-minute stock data?

**Equity swing: no.** Daily session-fresh OHLCV is the correct mark for a multi-day hold. CIPLA/Eicher already have 17 Aug closes.

**Intraday lab: yes, or stop calling it intraday.** A 1d bar cannot produce session-risk / flat-EOD behaviour. Atlas will look idle because there is only **one new bar per name per day**.

**F&O lab: not 1m cash.** It needs **futures (or index-proxy) quotes** with lot size. 1-minute RELIANCE.NS does not make a NIFTY lot trade.

### 3.1 What Yahoo can give us (already in-tree)

`YahooFinanceAdapter.fetch_bars(..., interval=, range=)` already hits:

```text
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=…&range=…
```

| Interval | Range | Use | Risk |
|----------|-------|-----|------|
| `1d` | `2mo` / `10y` | Swing marks + hist | Current path; 429 if uncapped |
| `5m` | `1d` | Intraday **first** (fewer points) | Still IP-shared |
| `1m` | `1d` (~375 bars) | True minute tape | **429 suicide** if 3 labs × 15 names × every tick |

Yahoo 1m is **not** NSE tick-by-tick, not bid/ask, not official, delayed, and **the same IP** as fundamentals + hist bootstrap. We already hit **321 consecutive 429s**.

### 3.2 How to get 1m without killing the telescope

**Lock (intraday wake):**

1. **At most 3 symbols** (open book first; else top-3 liquid NIFTY50).  
2. Interval **`5m` first** (one session ≈ 75 bars). Promote to `1m` only if 5m stays 429-clean for **two sessions**.  
3. Persist under `market/bars_intraday/{SYMBOL}/{IST_DATE}.json` — never mix into daily `market/bars`.  
4. Cache TTL **≥ 60s**. Paper tick may run every 5 min; it must **reuse** the last 5m fetch.  
5. Hist bootstrap + fundamentals **already yield in RTH**. Keep that. Intraday fetch is the **only** Yahoo chart in RTH besides open-book daily tip refresh (≤3/60s).  
6. If cooldown armed → mark last 5m bar **stale** + `yahoo_cooldown`; **do not invent**.  
7. **`1m` is a separate future OI (`OI-FEED-1M`)** — not L6-in-the-same-sprint. Two clean 5m sessions are a gate to *open* that OI, not to silently upgrade.

**Paid NSE / broker feed:** not this cycle. When we need official ticks / FO: Zerodha/Dhan/TrueData/GlobalDatafeeds — new adapter, **OI-FEED1**. LOOP0 must work **without** a paid key. One MarketDataService — do not add another Yahoo client.

### 3.3 F&O wake without a FO vendor (LOCKED)

First fill is an **honest index-proxy paper lot**:

- Instruments: `NIFTY` (required), `BANKNIFTY` (optional) — already seeded.  
- Mark: Yahoo `^NSEI` / `^NSEBANK` **daily** (session-fresh), same as now.  
- Size: 1 lot × lot_size (25 / 15) × point value as configured — **margin check**, not cash-equity concentration 0%.  
- Session: `nse_fno` 09:15–15:30.  
- Label: `valuation_basis: index_proxy daily underlier` — never “live futures”.  
- KPI / evening name: **NIFTY index-proxy laboratory performance** — never “F&O performance.”  
- **No cash-equity alt batch.**  
- Technical control: same SMA/RSI on the underlier (control lane). PLC.A fundamentals **off** (already).

True NSE FO chain / option greeks = later vendor (**OI-FEED1**, not this cycle). Do not block first lot on that.

**L4 operator unlock (2026-08-18 evening):** implement now so FNO can produce a closed-loop experiment. **L5 operator unlock (same evening):** complete true-intraday 5m wake. STAB0’s second consecutive clean session and AGENT-1 stay independent gates.

---

## 4. The three cognitive wires (LOCKED)

Operator assessment stands. Implement in this order **after** §2.1 unblocks so experiments can exist.

### 4.1 Mandatory belief consultation (`LOOP.1`)

Consult **unique decision states**, not every repeated HOLD tick.

```text
new decision state  →  ReasoningService.consult + RAG/WSO/experiences  →  persist
same state / evidence / thesis  →  reuse prior consultation
material change (price regime, thesis, fund, news, policy, ranking, belief, book)  →  re-consult
```

State key (durable, per lab+symbol+IST day): hash of
`{action_kind, thesis_id, evidence_fingerprint, ranking_bucket, book_fingerprint}`.
`mark_only` and identical HOLD on the same bar **must not** call the LLM.

A consultation still **always records**, including:

```text
beliefs_found: 0
note: "No relevant belief found."
```

Retrieval (deterministic first; LLM only if the façade needs it for this *new* state):

- Beliefs (`ReasoningService.consult`)
- WSO for the symbol
- Similar experiences
- Living RAG slice when cheap

**Influence: advice-only.** Packet field `belief_context`. SMA/RSI + PLC.A + UTS still decide. Phase 5 remains frozen. Goal is **not** more Qwen calls.

**Done when:** `Belief Consultations Today` ≥ unique decision states that produced packets (not ≥ paper ticks).

### 4.2 Expected-return prototype (`LOOP.2`)

UTS already has `expected_return_from_row` and then **refuses** when phase is learning. That is why CIPLA/Eicher never switch.

Crude, **always numeric**, never silent, **versioned**:

```text
E[R] = w_m·momentum + w_s·sector_RS + w_v·valuation + w_q·quality
       + w_b·belief_adj + w_e·experience_adj
```

Every packet / switch review must persist:

| Field | Example |
|-------|---------|
| `er_model` | `prototype_v1` (later `prototype_v2` / `learned_v1`) |
| `er_basis` | `prototype` |
| `er_completeness` | `0.43` |
| `er_inputs` | snapshot of each term + weights + missing flags |
| `expected_return` | `0.042` |

Six months later Atlas must answer “why was E[R] 4.2% on 17 Aug?” from the **packet**, not from today’s code.

| Term | Source | If missing |
|------|--------|------------|
| Momentum | Ranker / bar pct_move | 0, completeness− |
| Sector strength | NIFTY vs sector index RS (already in MTL) | 0, completeness− |
| Valuation | PE vs sector median if PE present | 0, completeness− |
| Quality | ROE / debt if present | 0, completeness− |
| Belief adj | consult score, **advice-only**, bounded ±2% | 0 if none found |
| Experience adj | closed-trade hit-rate on symbol/sector, bounded ±2% | 0 if n<3 |

Cap **confidence=low** while completeness < 0.6. Do **not** claim alpha.

**Done when:** CIPLA/Eicher switch reviews log a versioned number (hold or flip), not `switch_blocked_missing_er`.

### 4.3 Outcome-driven revision (`LOOP.3`)

Revisits already run. They must write an `outcome_check` **and**, when a belief candidate is created, the **causal chain**:

```text
belief_candidate:
  source_decision_id
  source_experience_id
  hypothesis
  expected_direction
  observed_direction
  evidence_ids
  contradiction_ids
  outcome_horizon
  confidence_before
  confidence_after_candidate
  reason
  falsifier_status
```

Not just `"CIPLA thesis weakened."`

**Do not auto-activate beliefs.** Candidate → evening reflection → operator / Phase 5 later.

**Done when:** a due CIPLA/Eicher revisit writes `outcome_check` + genealogical `belief_candidate` (or explicit “no candidate: evidence too thin”).

---

## 5. Implementation order (LOCKED — do not reorder, do not parallelize L4/L5 with L0–L3)

```text
L0  exposure semantics · FNO cash-alt · HBLPOWER · idle-reason honesty
 ↓
L1  E[R] prototype_v1 + versioned inputs/output on packets
 ↓
L2  unique-state ReasoningService + RAG/WSO/experiences + persist
 ↓
L3  outcome_check + genealogical belief candidate
 ↓
STAB0 second consecutive clean session   ← independent gate; LOOP0 does not finish STAB0
 ↓
AGENT-1  (still frozen until that gate)
 ↓
L4  FNO index-proxy lot  (NIFTY index-proxy lab performance)
 ↓
L5  Intraday 5m ≤3 names
 ↓
OI-FEED-1M  (optional 1m — separate OI, not this sprint)
 ↓
SELF0 Phase 5
```

**This landing is L0–L5.** 19 Aug RTH: FNO **did** take the index-proxy lot; intraday **did** consume 5m and fill. Integrity failures (FNO switched into Bosch cash; intraday overnight ASTRAL; thesis WATCH vs SMA BUY) are **OI-LINT0**, not more LOOP0 layers.

**Not in this cycle:** paid NSE feed, second Yahoo client, option chain, Phase 5 size influence, AtlasNet, new mentors, more LLM, judging Atlas by fill count.

STAB0 observe+explain stays the **equity session pass gate**. A trade is one possible experiment, not the success metric.

---

## 6. What Atlas needs from you (operator)

| Need | You | Atlas |
|------|-----|-------|
| Paid live tape | **Not required for L0–L4** | Daily Yahoo + paced 5m later |
| FO vendor / Kite token | **Not required for first NIFTY lot** | Index-proxy paper |
| Bounce after L0–L2 land | `sudo bash scripts/bounce_atlas_stab0.sh` | Workers pick up consult + E[R] |
| Screener FCF / promoter | Still unknown; IRA stays queued | Never invent |
| Phase 5 unlock | After **5 clean STAB0 sessions** | Beliefs may then nudge size |

If you later want **true** 1-second NSE / FO: pick a vendor, store API key in `.env` (`ATLAS_MARKET_FEED_*`), new adapter. That is **OI-FEED1** (not opened here).

---

## 7. Acceptance (session, not commit)

**L0–L3 (equity cognitive loop)** — next RTH after bounce. Success is **not** “Atlas traded.”

- [x] Consultations today **> 0** and tied to **unique decision states** (not every HOLD tick) — 18 Aug: 119 consults, 2 equity packets both `belief_context.reused`  
- [x] No `switch_blocked_missing_er` on CIPLA/Eicher (hold or switch with `er_model=prototype_v1` + `er_inputs`) — 18 Aug: `switch_blocked_plc_a`  
- [x] Intraday/FNO no longer fail `>0%` because template `max_exposure_pct=0` — 18 Aug: no `8.7%>0%`; FNO NIFTY-only  
- [x] FNO session notes have **zero cash-equity alts** (L0 — even before L4 lots) — `fno_no_cash_alts`×230  
- [x] Evening leads with **decision** idle reasons; `session_closed` / `mark_only` are clock noise — equity samples end in `switch_blocked_plc_a`  
- [x] Evening still honest: unknown ≠ learning; evaluations ≠ experiences  
- [x] L3 live: CIPLA 18 Aug `outcome_check` (open-book on paper ticks; Eicher buy-packet hole still optional)  

**L4 (FNO wake):**

- [x] Code: NIFTY 1 lot × 25, margin ~12% notional, `valuation_basis: index_proxy daily underlier`, KPI **NIFTY index-proxy laboratory performance** (not “F&O performance”)  
- [ ] Next RTH: either 1 NIFTY proxy lot **or** idle reason `margin` / `session_closed` — not `concentration 0%` / IDEA.NS / `research_hold` MVR  
- [x] Zero cash-equity alts in FNO session notes (L0)  

**L5 (intraday wake):**

- [x] Code: Yahoo **5m** / `range=1d`, persist `market/bars_intraday/{SYMBOL}/{IST_DATE}.json`, ≤3 names, cache ≥60s, no mix into daily `market/bars`  
- [x] Invalid 18 Aug daily-bar fills voided back to starting cash (operator reset — not a market sell)  
- [ ] Next RTH: `mark_only` is per **5m bar**, not per calendar day; Yahoo 429 stays 0  

---

## 8. Sentences to remember

> Daily Yahoo is enough for the swing book. It is not enough to call a lab “intraday.”  
> Consult unique decision states — not every HOLD tick.  
> Version the E[R] prototype; store inputs with the packet.  
> Belief candidates need genealogy, not slogans.  
> Template `max_exposure_pct=0` is unset, not a 0% cap — and not a global “every 0 means default.”  
> A trade is one experiment. STAB0 is still open. Phase 5 still does not spend money.

---

## 9. Discussion log

| Date | Note |
|------|------|
| 2026-08-18 20:21 IST | Operator: complete the plan so Atlas is true-intraday capable; void today’s daily-bar fills and restore cash. **L5 landed** (5m ≤3 names + `bars_intraday`). Invalid intraday session fills are not market sells. PLC.A on swing equity still fail-closed. 1m still OI-FEED-1M. |
| 2026-08-18 20:15 IST | Operator: three labs are different cars. Unlocked **L4** (NIFTY index-proxy 1 lot) now; **L5** (5m ≤3 names) next landing, not this one. PLC.A on swing equity stays fail-closed (policy, not a feed bug). |
| 2026-08-18 19:30 IST | Operator: complete L3 so we can judge without waiting ~10d for CIPLA day14. Open-book `outcome_check` now also runs from **paper ticks** (once/IST day), not only 86400s evolution. |
| 2026-08-17 evening | Operator: FNO/intraday still empty; need 1m?; implement closed loop. Assessment locked: worldview decorative; consult / E[R] prototype / outcome revision. **This plan locked.** Code starts at L0. |
| 2026-08-14 | Session observed: daily marks live; 0 fills; `missing_er`; `max_exposure 0%`; FNO cash alts. |
| 2026-08-13 | FNO unpaused; PLC.A skipped for FNO/intraday; session-fresh Yahoo tip refresh. |
