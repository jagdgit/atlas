# Universe Triage & Opportunity-Cost Switching

> **Status:** ✅ **FINALIZED FOR IMPLEMENTATION** (operator review aligned 2026-08-09)  
> **OI:** `OI-UTS0`  
> **Priority:** **Next code cycle after `OI-PLC0` operational verification** (Mon open + evening data sanity)  
> **Date:** 2026-08-09  
> **Does not reopen:** DI / LI / LQ / PLC architectures (reuse seams; closed-loop layer on top)  
> **Control strategy:** Keep SMA/RSI (`sma_cross_rsi`) as India Equity Laboratory control — switching is an **additive** portfolio policy, not a new technical strategy  
> **Identity shift:** Atlas is a **capital allocator with memory**, not a watchlist engine

---

## 0. Verdict (why this exists)

PLC0 gives Atlas disciplined **buying, observation, hypotheses, and exits**.  
UTS0 gives Atlas **competitive capital allocation across the entire market** plus a closed learning loop.

Together they form the first complete laboratory cycle that can improve **without** jumping into neural-network trading:

```
Observe everything → Research selectively → Allocate capital
→ Observe outcomes → Learn → Adjust future allocation
```

**Core principle (lock):**

> Atlas scans the entire universe every day, allocates attention selectively, allocates capital competitively, and learns from every decision it makes — including decisions **not** to trade and opportunities it **missed**.

M0 already **scores** ~190 members then **truncates** to a deep watchlist (~15). Open books get continuous packs (PLC.C). Two gaps remain:

1. **Triage amnesia** — ranks #16–#190 are not persisted → no rank acceleration, weak near-miss learning.  
2. **Naive / absent rotation** — holding a weaker name while a stronger challenger clears costs is an unpriced opportunity cost; blind “higher confidence ⇒ flip” over-trades without learning.

**North star:** Every material allocation choice is an **experiment with counterfactuals**, not just a logged trade opinion.

---

## 0.1 Non-negotiables

1. Never invent PE / FCF / MoS / expected returns / confidence / missed-opportunity PnL. Missing inputs → **no switch** (fail-closed) with an honest reason code.
2. Laboratory hermeticity — triage memory, switch records, missed-opportunity ledger, and thresholds are per `portfolio_key` / lab.
3. SMA/RSI remains the **control** technical lane; opportunity switching is a **separate** policy layer with its own reason codes.
4. No live NN / AtlasNet trading in this cycle. Threshold / confidence calibration = deterministic feedback from logged outcomes (proposals only until policy applies).
5. Early high turnover is **allowed when labeled exploratory**, not celebrated as edge. Goal: **fewer unnecessary trades**, not fewer trades.
6. Open positions always stay under continuous observation (PLC.C) even if demoted from the deep watchlist.
7. **Coverage KPIs are hard** — Atlas must not be uncertain whether it looked at the market today.
8. Switch Learning Records feed **existing Learning Intelligence** — no parallel learning database.

---

## 0.2 Relationship: PLC0 + UTS0

| | PLC0 | UTS0 |
|--|------|------|
| Role | Laboratory discipline (gates, packs, hypotheses, exits) | Capital allocation + memory + closed-loop learning |
| Unit | Hypothesis on a name / book | Hold-vs-challenger experiment + missed opportunities |
| When | Ops verify first (Mon open, evening density) | **Immediate next implementation priority after PLC0 verify** |

---

## 1. Locked architecture (learning allocator)

```
190-stock universe
        │
        ▼
Daily deterministic scan (all names)
        │
        ▼
Persist full rank ladder + acceleration
        │
        ├──────────────► Opportunity queue
        │                (accelerators, near-misses, discovery hits)
        ▼
Top 15 deep watchlist
        │
        ▼
Research + observation packs + PLC.A buy gates
        │
        ▼
Portfolio review (all current holdings)
        │
        ▼
Hold vs Challenger comparison
        │
        ▼
Switch decision (only if net advantage > threshold)
        │                 · label exploratory | calibrated
        ▼
Outcome tracking (1 / 5 / 20 / 60 days) + counterfactuals
        │
        ▼
Switch Learning Record → Learning Intelligence
        │
        ▼
Threshold + confidence calibration (proposals)
        │
        └──────────────► Better future attention & allocation

Parallel daily:
  Missed Opportunity Ledger (top 5 not owned that beat book over next 20d)
```

| Layer | Scope | Frequency | Cost | Purpose |
|-------|-------|-----------|------|---------|
| **Universe triage** | ~190 | Daily / M0 | Low | Vital signs + full memory |
| **Opportunity queue** | Accelerators / near-misses | Daily | Low | Attention candidates beyond top 15 |
| **Active watchlist** | Top ~15 | Intraday / deep | Medium | Conviction + trade prep |
| **Open books** | Holdings | Continuous | High | Risk, thesis, exits |
| **Portfolio review** | All holds vs challengers | Plan / sim ticks | Medium | Competitive capital |
| **Learning loop** | Switch + missed-opp records | Horizons | Low | Self-improving allocator |

**Open books** never lose observation coverage when demoted from the watchlist; they **do** face the switching rule when a challenger clears the advantage threshold.

---

## 2. What already exists (do not rebuild)

| Piece | Where | Keep |
|-------|-------|------|
| Full-membership score on M0 | `ranking.py` · `workers/investment_universe.py` | Extend — persist **before** truncate |
| Top-N watchlist publish | `watchlists.py` · `max_watchlist=15` | Yes |
| Open-book daily packs | `open_book_packs.py` · `market_observer` | Yes |
| Decision packets / timeline / revisits | DI + PLC | Switch experiments cite these |
| Exit reason codes | PLC.B | Add switch codes; don’t overwrite SMA exits |
| Learning Intelligence | LI plan / workers | **Sink** for Switch Learning Records |
| Experience / mentor soft-bias in rank | ranking weights | Soft only |

**Ops reality (2026-08-09):** `universe_size≈190`, durable watchlist=15, full ladder not stored; watchlist PE filled via Screener; Yahoo crumb often 429.

---

## 3. Layer definitions

### 3.1 Universe triage (light — all names)

Deterministic only (no LLM). Per symbol per triage day (IST):

| Signal | Source | Missing behavior |
|--------|--------|------------------|
| Rank + score + WHY components | M0 score **before truncate** | Mark day incomplete |
| Price change 1d / 5d / 20d | Chart bars | null |
| Relative strength vs Nifty | Bars + index | `unknown` if thin |
| Volume anomaly | Bars | null |
| Breakout / breakdown / vol expansion | Discovery screens (cheap) | Optional early |
| Earnings proximity | Research / calendar if present | null |
| News score | M3 when available | unknown — never invent |
| Liquidity / quality / policy / experience / research | Existing M0 components | As today |

**Persist for every member** (including #180): `as_of_ist`, `symbol`, `rank`, `score`, components, `rank_delta_*`, `acceleration`, `phase`, `confidence`.

### 3.2 Opportunity queue

Fed from triage (not a second ranker):

- Positive `acceleration_3d` outside top 15  
- Near-miss ranks (#16–#25)  
- Optional discovery hits (vol spike / breakout) when bars exist  

Queue drives **attention** (promote research / watchlist hysteresis), not automatic buys.

### 3.3 Rank acceleration

```
acceleration_3d = rank(t-3) - rank(t)   # positive = improved toward #1
accel_score = clip(acceleration_3d / universe_size, 0..1)
```

A path `150 → 40 → 18` is often a stronger attention signal than a static #5.

### 3.4 Deep watchlist (ICU)

Top `max_watchlist` by score + optional acceleration boost (off until validated) + **hysteresis** (beat #N by margin **or** hold 2 consecutive days) to limit thrash.

### 3.5 Separate expected return from confidence

| Field | Meaning |
|-------|---------|
| `expected_return` | Forward edge on tagged horizon (e.g. 20d) |
| `confidence` | Calibration of that estimate ∈ (0,1] |
| `risk_adjusted_score` | `expected_return × confidence` (v1) |

Committee example: prefer C (13%×0.80=10.4) over A (10%×0.90=9.0) and B (18%×0.45=8.1) for **new** risk capital. Switching still compares challenger vs **specific** hold after costs.

Null `expected_return` ⇒ **no switch**.

---

## 4. Opportunity-cost switching (capital competition)

### 4.1 Forbid

```
if confidence(new) > confidence(current): sell; buy
```

### 4.2 Require

```
ExpectedAdvantage =
    ExpectedReturn(challenger)
  - ExpectedReturn(hold)
  - TransactionCost - Slippage - TaxCost_proxy
  - ConfidencePenalty

Switch iff ExpectedAdvantage > SwitchingThreshold
```

**ConfidencePenalty (v1):**

```
k * max(0, conf(hold) - conf(challenger))
+ m * (1 - min(conf(challenger), conf(hold)))
```

Defaults: `k=0.02`, `m=0.01`; `SwitchingThreshold=0.02` (stricter under cold-start, e.g. `0.05`).

### 4.3 Portfolio review

On each eligible sim/plan tick: **every open hold** is reviewed against top challengers from watchlist + opportunity queue (not already held). Emit `hold_incumbent` or switch intent — silent “never looked” is a bug.

### 4.4 Reason codes

| Code | Meaning |
|------|---------|
| `switch_advantage_cleared` | Net advantage ≥ threshold |
| `switch_exploratory` | Cleared threshold while lab calibration immature / labeled exploration |
| `switch_blocked_costs` | Gross better, net ≤ threshold |
| `switch_blocked_missing_er` | E[R] or confidence missing |
| `switch_blocked_plc_a` | Challenger fails buy gates |
| `switch_blocked_cold_start` | Stricter threshold / policy hold |
| `hold_incumbent` | Evaluated; no switch |

SMA exits remain separate (`sma_crossunder`, stops, thesis breaks, …).

### 4.5 Exploratory vs calibrated

| Label | When | Evening honesty |
|-------|------|-----------------|
| `exploratory` | Cold-start / low sample / confidence poorly calibrated | “Exploring — expect higher turnover” |
| `calibrated` | Enough Switch Learning Records + stable threshold | “Selective — threshold T” |

Goal is not fewer trades — it is **fewer unnecessary trades**.

---

## 5. Every trade is an experiment (counterfactuals)

Logging a decision is not enough. Atlas logs **what would have happened otherwise**.

### 5.1 Switch Decision (execution record)

Durable row for every evaluated hold-vs-challenger (taken **or** blocked): symbols, E[R], confidence, costs, advantage, threshold, decision, reason_code, exploratory flag, packet/timeline ids.

### 5.2 Switch Learning Record (first-class LI object)

Feeds **Learning Intelligence** (not a separate DB). Shape:

```
Switch Learning Record
----------------------
Context:
  - market regime
  - sector regime
  - volatility regime
  - lab phase / exploratory?

Decision:
  - hold_symbol
  - challenger_symbol
  - expected_advantage
  - confidence
  - threshold
  - why (deterministic components)

Outcome (horizons 1 / 5 / 20 / 60d):
  - switched_return   # challenger path
  - held_return       # incumbent path (counterfactual if switched)
  - excess_return     # switched - held
  - was_switch_better?

Attribution:
  - primary_driver
  - incorrect_assumption   # null if unknown — never invent
  - missing_information
  - preventable?           # yes/no/unknown
```

Example narrative (operator-facing, built from fields — not free LLM invention):

| Question | Example |
|----------|---------|
| Sold / bought | TCS → BEL |
| Why | Higher E[R], sector strength, improving rank |
| Expected advantage | +4.2% vs threshold 2.0% |
| After 20d | BEL +8%, TCS +1% → switch better |
| Learn | Sector acceleration outweighed valuation this regime |

Patterns Atlas should eventually surface (examples, not hard-coded truths):

- Switching when rank acceleration > N positions helps  
- Single-news flips without rank/volume confirmation hurt  
- Holding through earnings when confidence > 0.8 helps  
- Costs erase sub-threshold advantages  

### 5.3 Outcome horizons

| Horizon | Role |
|---------|------|
| 1d | Immediate mark path |
| 5d | Short path |
| 20d | Primary swing horizon (default) |
| 60d | Slow path / regret |

All PnL fields labeled **sim counterfactual** — never broker truth.

### 5.4 Threshold calibration

After lab-local N (start ≥50 switches with 20d done): propose threshold that would have maximized excess return. **Proposal only** — config/policy applies; no silent live mutation.

---

## 6. Missed Opportunity Ledger (mandatory)

**Purpose:** Trades Atlas made teach something; names it **failed to notice** often teach more.

**Daily job (T+20 IST):** Among universe members **not held** on day T, take the top 5 by subsequent 20d return **relative to the portfolio’s 20d return** (or equal-weight book return if simpler v1). Record:

| Field | Notes |
|-------|-------|
| `as_of_ist` (decision day T) | |
| `symbol`, `rank_on_T`, `acceleration_on_T` | From triage memory |
| `in_watchlist_on_T?`, `in_opportunity_queue_on_T?` | Attention failure diagnosis |
| `return_20d_symbol`, `return_20d_book`, `excess_vs_book` | Marks only |
| `why_missed` codes | e.g. `never_top15`, `blocked_costs`, `missing_er`, `plc_a`, `not_evaluated` — from durable state, not invented story |

This ledger is a primary dataset for:

- ranking / acceleration weight proposals  
- threshold calibration  
- evening “what we failed to notice” honesty  

**Fail-closed:** if marks missing for symbol or book, skip row; do not invent excess.

---

## 7. Coverage KPIs (hard daily OS)

Atlas must not wonder whether it looked at the market.

| KPI | Target |
|-----|--------|
| Universe scanned | `scored / membership` → **190/190** when bars allow; else honest gap count |
| Price coverage | **>95%** of membership with usable last price (chart) |
| Rank ladder persisted | **Yes** for IST day |
| Acceleration computed | **Yes** where ≥3 triage days; else `pending_history` |
| Watchlist refreshed | **Yes** after triage |
| Open books observed | **100%** packs for `qty>0` |
| Switches evaluated | N (every hold reviewed) |
| Switches executed | N |
| Switches proven beneficial | rolling % at 20d |
| Missed-opportunity rows | up to 5 / day when marks exist |

**Observable improvement plots (6-month north star):**

- switch hit rate (20d)  
- opportunity capture rate (missed-opp excess declining)  
- average excess return from rotations  
- confidence calibration error  
- turnover_20d  
- missed-opportunity rate  

If these improve, Atlas is **genuinely getting better** — not just producing opinions.

---

## 8. Phased implementation (ready to code)

### Phase A — Full triage memory · `UTS.A`  ← start here

1. Split score-all vs truncate-to-watchlist in `ranking.py`.  
2. `atlas/investment/triage_memory.py` → `data/investment/triage/{lab_or_program}/{YYYY-MM-DD}.jsonl`.  
3. M0 writes full ladder; watchlist publish still ≤`max_watchlist`.  
4. Read helpers: latest day, symbol history K days.  
5. Emit raw **coverage KPI** stub (`scanned`, `persisted`).

**Done when:** Hermetic 5 members → 5 triage lines + watchlist max 2 → 2 published.

### Phase B — Acceleration + opportunity queue · `UTS.B`

1. `rank_delta_*`, `acceleration_3d`.  
2. Opportunity queue materialization.  
3. Evening: accelerating / near-miss (#16–#25).  
4. Optional rank boost config **default off**.

### Phase C — E[R] × confidence seam · `UTS.C`

1. `opportunity_switch.py`: `risk_adjusted_score`, `confidence_penalty`, `expected_advantage`.  
2. Null honesty → `switch_blocked_missing_er`.  
3. Attach to plan candidates + holdings when computable.

### Phase D — Portfolio review + switching (sim) · `UTS.D`

1. Every hold vs challengers (watchlist + queue).  
2. Advantage rule + PLC.A + concentration caps.  
3. Labels `exploratory` | `calibrated`.  
4. Learner default on; other books opt-in.

### Phase E — Switch Learning Records + calibration · `UTS.E`

1. Persist Switch Decision + schedule 1/5/20/60d counterfactuals.  
2. Build Switch Learning Record → LI sink.  
3. Threshold / confidence **proposals** only.

### Phase F — Missed Opportunity Ledger · `UTS.F`

1. T+20 job: top 5 not-held outperformers vs book.  
2. Wire `why_missed` from durable triage/switch state.  
3. Evening + LI consume ledger.

### Phase G — Coverage OS + status chat · `UTS.G`

1. Hard KPI block on evening / governance daily.  
2. Market status chat: “Did we scan the universe?” / “Why not switch into X?”  
3. Playbook one-pager.

---

## 9. Implementation sketch (files)

| Area | Touchpoints |
|------|-------------|
| Score-all / truncate | `atlas/investment/ranking.py` |
| Triage persist | new `atlas/investment/triage_memory.py` |
| M0 write | `atlas/workers/investment_universe.py` |
| Opportunity queue | `triage_memory.py` or small `opportunity_queue.py` |
| Advantage + review | new `atlas/investment/opportunity_switch.py` |
| Sim wiring | `paper_trading` / `decision_simulation` |
| Switch Learning Record | new module + LI publisher (reuse experience/LI seams) |
| Missed-opp ledger | new `atlas/investment/missed_opportunity.py` (+ worker/cron) |
| Packets / timeline | DI stores |
| Evening / KPIs | `reports.py` · `investor_reports` · governance daily |
| Tests | `tests/test_uts_*.py` hermetic |

---

## 10. Config defaults (learner)

```yaml
universe_triage_persist: true
max_watchlist: 15
opportunity_queue_enabled: true
opportunity_switch_enabled: true          # learner only
switching_threshold: 0.02
cold_start_switch_threshold: 0.05
switch_cost_bps: 100
confidence_penalty_k: 0.02
confidence_penalty_m: 0.01
acceleration_rank_boost: false
missed_opportunity_ledger: true
missed_opportunity_top_n: 5
missed_opportunity_horizon_d: 20
coverage_kpi_evening: true
exploratory_turnover_ok: true             # honesty label only
```

---

## 11. Explicit non-goals

- Autonomous F&O universe ranking  
- LLM essays for all 190 names daily  
- Live broker tax-lot precision (labeled proxies until adapter exists)  
- Silent self-tuning of live threshold  
- Replacing SMA/RSI control  
- Parallel learning database outside LI/Experience  

---

## 12. Acceptance checklist

- [x] UTS.A — full triage JSONL/day; watchlist truncated; coverage stub  
- [x] UTS.B — acceleration + opportunity queue + evening near-miss  
- [x] UTS.C — E[R]×confidence helpers + null honesty  
- [x] UTS.D — every hold reviewed; switch/hold reason codes; exploratory label  
- [x] UTS.E — Switch Learning Records → LI; 1/5/20/60d; threshold **proposal**  
- [x] UTS.F — Missed Opportunity Ledger top-5 / 20d  
- [x] UTS.G — hard coverage KPIs + status chat  
- [x] Hermetic tests for UTS.A/B/C/D/E/F/G  
- [x] Learner default on; other books opt-in  
- [ ] Improvement plots defined (even if first paint is sparse)

---

## 13. Relationship to other plans

| Plan | Relationship |
|------|----------------|
| `PROFESSIONAL_LABORATORY_CYCLE_PLAN.md` | PLC0 = discipline; UTS0 = allocator on top — **next after PLC0 ops verify** |
| `AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md` §14 | M0 score → top-N — **extend** with persist-all + queue |
| `DECISION_INTELLIGENCE_LEARNING_PLAN.md` | Packets/timeline host switch experiments |
| `LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md` | **Sink** for Switch Learning Records + missed-opp lessons |
| `MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md` | Counterfactuals labeled sim; no fake broker fills |

---

## 14. Operator one-liners

**Identity:** Capital allocator with memory — not a watchlist engine.

**Funnel:** Scan all → remember all → deep-watch few → review every hold → switch only on net advantage → learn from switches **and** misses.

**Success:** Coverage KPIs green daily; switch hit rate and missed-opportunity rate improve over months — observable self-improvement without NN trading.
