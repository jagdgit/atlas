# Market Laboratory — Evidence, Attribution & Learning Quality Plan

> **Status:** 🔒 **PLAN LOCKED** (2026-08-08) · **LQ.1–LQ.9 ✅** · **OI-MLQ0 shipped**  
> **Product redirect:** from *paper trading simulator* → *market laboratory*  
> **Governance:** respects [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) —
> **no new OS**; builds on Decision + Experience + Resource OS  
> **Parents (🔒 locked / shipped):**  
> [`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md) (DI.1→DI.7 ✅) ·  
> [`LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md`](LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md) (LI.1a→LI.6 ✅) ·  
> [`SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md`](SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md) (SI.1–6 🟢) ·  
> [`TRADING_STRATEGY_PLAYBOOK.md`](TRADING_STRATEGY_PLAYBOOK.md) · Resource OS / Host Guard  
> **Open item:** `OI-MLQ0` — **LQ.1–LQ.9 shipped** (evidence densify complete; AtlasNet still prep-only until §8.2 clears in production)  
> **Hard rule:** AtlasNet / live NN remain **off** until the quality gates in §8 are met  
> **After lock:** implement LQ phases in order; new ideas → OI items, not further redesign docs  
> **Execution rule:** every LQ PR must preserve **laboratory hermeticity** (LI §0.2) and research honesty (never invent)

---

## 0. One-sentence verdict

**Atlas already has the laboratory scaffolding (packets, timelines, labs, IQ, gated export). The gap is no longer architecture — it is structured evidence density: sector-specific research, mandatory time-series observation, causal attribution, and honest outcome labels so Atlas becomes measurably smarter from its own history.**

**Product test:**  
- Simulator asks: *What trades should I take today?*  
- Laboratory asks: *Why did I believe this would work, what happened afterward, which variables mattered, and what should change next time?*

If a closed book cannot answer those four questions from durable records, Atlas is still a simulator with research cosmetics.

---

## 1. Philosophical lock (do not reopen)

| Keep | Refuse |
|------|--------|
| Laboratory ≻ ledger | Busy fills as “learning” |
| Belief freeze at decide-time | Rewriting packets after the fact |
| Decision quality ≠ market P&L | Training NN on incomplete labels |
| Evidence tiers + never invent | Blended PE / fake industry averages |
| World knowledge may transfer; strategy priors may not | Cross-lab win-rate pooling |
| Resource OS host-first | Observation vanity that takes down the host |
| Stage KPIs (A→D) | Stage D metrics / AtlasNet before data quality |

**Milestone to optimize for:** Atlas in 2028 is measurably smarter than Atlas in 2026 **because of its own recorded investment history**, not because of better prompts.

---

## 2. What is already strong (do not redesign)

### 2.1 Resource OS
Host-first admission, scheduling, checkpoints, Host Guard cadence, slow-but-reliable on constrained hardware. **Keep.** LI observation cadence already asks Host Guard — deepen, don’t bypass.

### 2.2 Trading execution pipeline
Universe → daily plan → signal → research gate → portfolio gate → execution → journal → KPIs → mail. Real pipeline, not a toy script. **Keep.**

### 2.3 Research honesty
Coverage ≠ confidence ≠ quality ≠ evidence sufficiency. Prefer honest unknowns over invented values. **Keep.**

### 2.4 Decision / Learning Intelligence scaffolding (shipped)
| Capability | Status | Notes |
|------------|--------|-------|
| Decision Packets (immutable decide-time belief) | ✅ DI.1 | Freeze exists; **content depth** still thin |
| Timeline + revisits | ✅ DI.2 / LI.3a–3b | Structure exists; **density & mandatory cadence** weak |
| Observations | ✅ DI.Obs / LI.3 | Kinds exist; **per-position continuity** weak |
| Outcome attribution + failure_cause | ✅ DI.Attr / LI.5 | Schema exists; **fill rate** near zero in ops |
| Laboratories + hermeticity | ✅ LI.1 | Isolation shipped; more labs still to **operate** |
| Evidence tiers + Yahoo medium | ✅ LI.2 | Tier C path exists; not yet **default learning fuel** |
| Atlas IQ + hypotheses + readiness | ✅ LI.5 | Proxies exist; **causal skill reports** shallow |
| AtlasNet prep export | ✅ LI.6 | Partitioned export + contract; **no NN** |

**Implication:** This plan does **not** restart DI.1 / LI.1a. It **fills the laboratory with usable evidence** on top of those seams.

---

## 3. Where Atlas is still weak (honest gap)

### 3.1 Research is still too company-agnostic
Dossiers for Apollo vs MTAR can look structurally identical because questions are universal.

Sector Intelligence (SI) is frozen — **activation gap**: sector packs must drive the *first* research questions, not a post-hoc appendix.

| Hospital (Apollo) | Precision mfg / defense (MTAR) |
|-------------------|-------------------------------|
| Occupancy, ARPOB, pharmacy mix | Order-book quality |
| Insurance reimbursement | Customer concentration |
| Digital health, expansion economics | Cycle time, WC, export, certifications |

Without sector packs in the live research path, every dossier collapses to: *interesting business, valuation unknown, management unknown* — a **template**, not research.

### 3.2 Time does not fully exist yet
A trade is a **sequence**, not an entry/exit pair.

```
Day 0   Research · Decision · Buy
Day 7   Price −4% · news: order delay · volume spike
Day 21  Price +9% · clarification · sector rerating
Day 45  Sell · outcome · lesson
```

Revisits exist; they are not yet **mandatory sensory continuity** for every open book. Quiet marks (LI.3a) help density but do not replace news/sector/thesis checkpoints.

### 3.3 Learning is not causal
Atlas can record *Bought EICHERMOT*. It rarely can say:

> Succeeded because ROE was high, sector momentum positive, valuation reasonable, earnings surprise positive, promoter holding increased.

That needs **feature attribution** at outcome time — foundation for any future ML. Failure taxonomy and grades exist; **causal feature contribution on closes** is the missing layer.

### 3.4 Capture asymmetry (operator diagnosis)

| Capture | Today | Target |
|---------|-------|--------|
| Trades / fills | Strong | Keep |
| Beliefs (packets) | Partial | Complete decide-time freeze + sector lens |
| Outcomes | Weak | Always labeled on exit + thesis/hypothesis verdict |
| Attribution | Almost none | Root cause + feature drivers on material outcomes |

---

## 4. Permanent model — five laboratory layers

Not a new OS. A **data contract** every material decision must satisfy.

```
Layer 1  Observation     raw facts (price, fund, news, sector, macro, process…)
Layer 2  Decision Packet freeze belief + evidence + expectations at decide-time
Layer 3  Timeline        attach observations at T+1…T+90; thesis still valid?
Layer 4  Outcome         closed labels: return, thesis, hypothesis, root cause, regime
Layer 5  Learning        Atlas IQ / calibration / labs — what worked and why
```

### Layer 1 — Observation
Everything observable without interpretation theater: price, volume, PE/PB, ROE/ROIC, margins, growth, promoter, news, sector, macro, technicals, vol, drawdown, portfolio exposure, execution metrics, process proxies. Provenance + confidence on every field.

### Layer 2 — Decision Packet
Immutable snapshot: laboratory, symbol, action, prices, technical/fundamental/news/sector/macro/risk snapshots, thesis, falsifiers, expected hold/return/downside, confidence, `strategy_tag`, `experiment_id`, `hypothesis_id`, sector pack id. **Never rewrite.**

### Layer 3 — Timeline
Mandatory checkpoints for open material positions (resource-aware): T+1, T+3, T+7, T+14, T+30, T+90 (tune per lab personality). At each: mark, news delta, volume, earnings, sector/macro, thesis validity, confidence Δ, action Δ. Host Guard may **reduce** cadence — never invent coverage.

### Layer 4 — Outcome
On close (and gated revisits): return, risk-adjusted stubs when sample allows, drawdown, hold days, exit reason, thesis result, hypothesis verdict, **one primary root cause**, regime, strategy, laboratory. Creates labeled rows.

### Layer 5 — Learning
Across many outcomes: what worked/failed repeatedly; by sector, regime, confidence band, valuation range, pattern, hold period, size. Feeds Atlas IQ — **not** pooled vanity across laboratories.

---

## 5. KPI staging (keep the full list — stage activation)

| Stage | Closed sample (guideline) | Emphasize | Hide / stub |
|-------|---------------------------|-----------|-------------|
| **A** | 0–50 | Rule adherence, journal completion, risk/trade, drawdown, process control, decision quality, hypothesis outcomes | Sharpe/Sortino theater |
| **B** | 50–200 | Win rate, PF, expectancy, avg R, sector/strategy/regime lanes | Stage C risk ratios |
| **C** | 200–1000 | Sharpe, Sortino, Calmar, SQN, MAE/MFE, rolling expectancy/DD, confidence calibration | NN claims |
| **D** | 1000+ | Neural nets, meta-learning, regime classifiers, portfolio opt, probabilistic sizing | — until §8 gates |

**Mistake to avoid:** implementing Stage D now. LI.6 prep is enough until gates clear.

Existing DI sample gates (30/100/300 per lane) remain; Stage A–D is the **operator narrative** layered on top.

---

## 6. Fundamentals — stop waiting (evidence tiers)

Safe conservatism (never invent) stays. Waiting for operator CSV as the *only* fuel **starves the laboratory**.

| Tier | Sources | Confidence | Rule |
|------|---------|------------|------|
| **A** | Annual reports, quarterlies, exchange disclosures | very_high / verified | Preferred truth |
| **B** | Screener export, official decks | high | Prefer over C when present |
| **C** | Yahoo / public market APIs (no scrape ToS violations) | medium | **Auto-import allowed** with confidence penalty |
| **D** | AI-generated inference | low / estimated | Never sole gate for buys |

**Locked ops rule for this plan:** Tier C may run on a schedule / on packet freeze for watchlist gaps, always stamped as medium, never blended with A/B when conflict &gt;15% (already LI.2). Dossiers become useful **without** lying.

Yahoo is a **provider**, not Truth — already LI.2; this plan makes Tier C **default learning fuel**, not opt-in rarity.

---

## 7. Laboratories (operate, don’t redesign)

Agree with locked lab design. **Operate** these books as independent laboratories:

| Laboratory | Horizon | Emphasis |
|------------|---------|----------|
| India Equity Learner (swing) | 3–24 months | Fundamental-heavy |
| India Intraday Lab | minutes–days | Execution / technical |
| India F&O Lab | derivatives | Risk / volatility (demo first) |
| Event-Driven Lab | earnings / budget / RBI / policy | News & calendar |
| Experimental Lab | R&D | Alt signals / future NN heads only after gates |

**Transfer rule (locked):** world knowledge may inform other labs; strategy priors, sizing, and return labels must not contaminate.

---

## 8. News learning & AtlasNet gate

### 8.1 News timeline (per position)
Every open material position should accumulate a news event log:

- timestamp, source, topic tags (earnings, regulation, management, order, lawsuit, capex, sector, macro)
- sentiment (provisional)
- Did Atlas observe before the move? Act? Was the signal useful ex post?

Aggregate later: *“Defense order-win headlines → median +X% over N days”* as a **learned feature**, not a vibes summary.

### 8.2 AtlasNet hard gate (stricter than LI.6 prep)

LI.6 may **export** prep datasets. Training / paper NN / live NN only when **all** hold (lab-scoped where applicable):

1. ≥ **500** closed attributable decisions across laboratories (not fills alone)  
2. ≥ **10** market regimes represented in the closed set  
3. &lt; **5%** missing critical decide-time fields on export rows  
4. ≥ **70%** decisions with complete timelines (checkpoint coverage)  
5. ≥ **70%** decisions with thesis **or** hypothesis outcomes  
6. ≥ **12 months** continuous history  
7. Failure taxonomy present on a minimum fraction of material losses (LI.5 vocabulary)  
8. `learned_beats_rules` on **paper** walk-forward vs rules baseline (contract from LI.6)

Until then: `live_nn_trading=False`, `atlasnet_status=prep_only`.

---

## 9. Implementation phases (LQ.*)

Order is **evidence → time → causality → calibration → NN eligibility**.  
Do not reopen DI/LI architecture; **wire and densify**.

```
LQ.0  Lock this plan (OI-MLQ0) ✅
  → LQ.1  Sector packs in live research (SI activation)   ✅
  → LQ.7  Fundamentals Tier C default enrich (parallel OK with LQ.1) ✅
  → LQ.2  Mandatory position timeline density (resource-aware) ✅
  → LQ.3  News timeline per position   ✅
  → LQ.4  Causal feature attribution on outcomes   ✅
  → LQ.5  Confidence calibration curves   ✅
  → LQ.6  Regime labeling completeness   ✅
  → LQ.8  KPI Stage A/B honesty in mail/dashboards   ✅
  → LQ.9  AtlasNet hard-gate enforcer (block train beyond prep)   ✅
```

| Phase | Done when | Primary seams |
|-------|-----------|---------------|
| **LQ.1** ✅ | Dossier questions differ by sector pack before generic MVR; Apollo ≠ MTAR question set | SI packs · research service · compare |
| **LQ.2** ✅ | Every open material position has due checkpoints; Host Guard may thin, never invent; evening shows pending/done honestly | timeline · evolution worker · obs cadence |
| **LQ.3** ✅ | Per-symbol news jsonl/timeline events linked to open books; cite on revisits | news worker · observations · packets |
| **LQ.4** ✅ | Material exits carry primary root cause **and** top feature drivers (decide-time contrib Δ or ranked factors) | attribution · learning_intelligence |
| **LQ.5** ✅ | Stated confidence vs outcome curves per lab (hide below sample) | packets · outcomes · Atlas IQ calibration axis |
| **LQ.6** ✅ | Closed rows carry regime tags; unknown allowed; never invent | market_snapshot · export quality |
| **LQ.7** ✅ | Watchlist gaps auto Tier C enrich on schedule; conflicts flagged; coverage rises without operator CSV | yahoo_fundamentals · evidence_providers · fundamentals_enrich worker |
| **LQ.8** ✅ | Mail/API show Stage A metrics always; Stage B only past gates; no Stage C vanity early | di_dashboards · reports |
| **LQ.9** ✅ | Any train/paper-NN path checks §8 gate object; prep export remains available | atlasnet_prep · ml_export |

**Hermeticity:** every LQ PR keeps laboratory isolation (§0.2 of LI plan). World news/fundamentals may be shared; outcome stats and strategy priors must not mix.

**Parallelism:** LQ.7 may start alongside LQ.1 (independent seams). Do not start LQ.4+ until LQ.2–LQ.3 have a green path for open books.

---

## 10. Non-goals

- New top-level “Laboratory OS”  
- Reopening DI / LI locked architecture  
- Live or paper NN before §8  
- Screener HTML scrape / ToS-hostile sources  
- Inventing PE, regimes, or sector KPIs  
- Forcing fills to inflate sample size  
- Ignoring Host Guard for observation vanity  
- Collapsing all labs into one “best strategy”

---

## 11. Operator lock checklist

| # | Question | Locked decision | ✅ |
|---|----------|-----------------|---|
| 1 | Product identity | Market laboratory, not simulator | 🔒 |
| 2 | Do not restart DI/LI | Fill evidence on shipped seams | 🔒 |
| 3 | Sector packs first | LQ.1 before more generic research polish | 🔒 |
| 4 | Time mandatory | Open books get resource-aware timeline density | 🔒 |
| 5 | Tier C fundamentals | Auto medium evidence with penalties | 🔒 |
| 6 | Causal attribution | Root cause + feature drivers on material exits | 🔒 |
| 7 | KPI staging | A→D; hide vanity early | 🔒 |
| 8 | AtlasNet gate | §8 hard gate; prep-only until cleared | 🔒 |
| 9 | Labs to operate | Swing + Intraday next; F&O/Event/Experimental after | 🔒 |
| 10 | Promote to 🔒 | **Locked 2026-08-08** | 🔒 |

---

## 12. Status checklist

1. ✅ Operator review / finalize for implementation (2026-08-08).  
2. ✅ `OI-MLQ0` registered.  
3. ✅ Links from DI / LI / SI parent docs.  
4. ✅ 🔒 PLAN LOCKED.  
5. ✅ Code **LQ.1** Sector pack activation (`question_activation`, sector-first live head).  
6. ✅ Code **LQ.7** Tier C default enrich (`enrich_watchlist_gaps` + `fundamentals_enrich` worker).  
7. ✅ Code **LQ.2** Mandatory timeline density (day3/day14 + ensure + Host Guard + evening coverage).  
8. ✅ Code **LQ.3** News timelines (`news/{SYM}.jsonl`, §8.1 fields, `news_delta` on revisits).  
9. ✅ Code **LQ.4** Causal attribution (`failure_cause` infer + `feature_drivers` on exits).  
10. ✅ Code **LQ.5** Confidence calibration curves (hide below sample; ECE on Atlas IQ).  
11. ✅ Code **LQ.6** Regime labeling (`normalize`/`resolve`/`stamp`; closed export fill; unknown OK).  
12. ✅ Code **LQ.8** KPI Stage A/B honesty (`kpi_staging` on dashboards/mail; Stage C/D never invented).  
13. ✅ Code **LQ.9** AtlasNet hard-gate (`evaluate_atlasnet_hard_gate` / `request_atlasnet_train`; force cannot bypass).  

---

## 13. Coding kickoff

**LQ.1–LQ.9 ✅ — OI-MLQ0 implementation complete.**

Operate the laboratory: densify evidence in production, watch §8.2 hard_gate metrics, keep AtlasNet **prep_only** until gates clear on real sample.

Do **not** start AtlasNet training, Stage D KPIs, or cross-lab strategy prior sharing.

Hermeticity + never-invent fundamentals on every follow-on PR.

---

## Appendix A — Narrative map

| Operator statement | Home |
|--------------------|------|
| Laboratory ≠ simulator | §0–§1 |
| Keep Resource OS / pipeline / honesty | §2 |
| Company-agnostic research | §3.1 · LQ.1 · SI plan |
| Time must exist | §3.2 · LQ.2–LQ.3 |
| Causal learning | §3.3 · LQ.4–LQ.5 |
| Five layers | §4 |
| KPI stages | §5 |
| Fundamentals Tier C | §6 · LQ.7 |
| Laboratories | §7 |
| News + AtlasNet gate | §8 |
| Phase order | §9 |
| Hermeticity PR rule | Header · LI §0.2 |

## Appendix B — Relation to locked plans

| Plan | Relation |
|------|----------|
| DI.1–DI.7 | Scaffolding; LQ densifies content & fill rates |
| LI.1a–LI.6 | Labs, IQ, prep export; LQ raises **quality** toward §8 |
| SI.1–6 | Question packs; LQ.1 is **activation in the live path** |
| Playbook | Execution unchanged; laboratory learning sits beside it |
| Resource OS | Cadence authority for LQ.2–LQ.3 |

---

*🔒 PLAN LOCKED 2026-08-08 — LQ.1–LQ.9 ✅ (OI-MLQ0 shipped); new ideas become OI items.*
