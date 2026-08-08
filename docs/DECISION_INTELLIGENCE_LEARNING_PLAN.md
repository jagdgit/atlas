# Decision Intelligence & Systematic Learning Plan

> **Status:** 🔒 **PLAN LOCKED · DI.1→DI.7 SHIPPED** (2026-08-05) · **DI stack complete (DI.7 gated)**  
> **Architecture score ~9.5/10 after review amendments** · **Implementation kickoff: §12**  
> **Date:** 2026-08-05  
> **Trigger:** Operator review — Atlas must become an investment researcher that happens to trade, not a technical execution engine that sometimes researches.  
> **Parents:** [`TRADING_STRATEGY_PLAYBOOK.md`](TRADING_STRATEGY_PLAYBOOK.md) ·
> [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) ·
> [`INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md`](INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md) ·
> [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md)  
> **Successor (🔒 locked):** [`LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md`](LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md) — Market Laboratories + Learning Intelligence; **does not reopen** DI; LI.1a→LI.6 ✅  
> **Next quality plan (🔒 locked):** [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) (`OI-MLQ0`) — **LQ.1–LQ.9 ✅ shipped**; AtlasNet prep-only until §8.2
> **Open item:** `OI-DI0` — **DI.1→DI.7 shipped**; DI.7 export gated until ≥300 trusted (or override); **no live NN**  
> **Book in scope first:** `india_equity_learner` · P10 simulation only  
> **Migrations used:** `0045`–`0048` · **Next free:** `0049` (reserved for LI / Learning Intelligence plan)

---

## 0. One-sentence verdict

**Atlas already has Knowledge OS, Experience OS, research dossiers, paper trading, and ledger honesty — what is missing is a durable Decision Intelligence layer that stores belief + evidence + expected outcome at decide-time, revisits those beliefs as time passes, separates decision quality from market luck, and measures whether Atlas itself is getting smarter.** Without that proprietary history, advanced ML later has nothing uniquely Atlas to train on.

**Philosophical redirect (locked):** from *“a system that can paper trade”* to *“a system that can explain, remember, critique, and improve every investment decision it has ever made.”*

---

## 1. Locked operator decisions (§8 resolved)

| Question | Locked answer |
|----------|---------------|
| Storage | **Hybrid** — Postgres authoritative for query/ML; JSON mirrors for replay, debugging, human reading, backups |
| DI.1 vs DI.4 | **DI.1 first**, **DI.4 in parallel** |
| Edge metrics gates | Hide &lt;30 closed · provisional 30–99 · usable 100–299 · trusted ≥300 |
| Watch/Hold packets | **Yes** — first-class decisions |
| Strategy tags | v1 set below; **expect growth** over time |
| Open item | **`OI-DI0` locked** |

---

## 2. Agreement + review amendments

### Strongly kept from draft

- Decision Packets (belief freeze) — highest leverage  
- Watch is a decision  
- Decision Replay  
- Five investment/trading dashboards (now **six** — see D6)  
- Playbook = strategy memory; this file = architecture memory  
- No redesign of Knowledge / Experience / Mission / Resource OS  

### Amendments from operator review (must design now — hard to bolt on later)

| # | Amendment | Why it matters later |
|---|-----------|----------------------|
| 1 | **Market Snapshot** on every packet | Regime learning (VIX, breadth, FX, sector day) |
| 2 | **Feature contributions** (signed weights), not only % confidence | Explain *why* BUY, train attribution models |
| 3 | **Decision evolution** (D1→W1→M1→Q→Exit) | Learning is gradual, not binary exit-only |
| 4 | **Decision quality ≠ market outcome** | Avoid “COVID taught don’t buy good businesses” |
| 5 | **Research field age / TTL / decay** | Stop believing stale ROE forever |
| 6 | **Observation Layer** before research | Continuous facts → research interprets → decision uses |
| 7 | **Lesson confidence + applicability + evidence count** | Genuine experience, not one-off notes |
| 8 | **Decision genealogy** | Trace how Atlas evolved |
| 9 | **Meta-learning job** (weekly automatic) | Which axes/KPIs/sections actually mattered |
| 10 | **D6 Intelligence Dashboard** | Evaluate Atlas-the-product, not only the book |

---

## 3. Desired end-state

```
Observation Layer  (continuous: CEO, order book, promoter, rates, margins, …)
        ↓
Research refresh   (interpret observations; aged fields; gaps)
        ↓
Decision Packet    (immutable belief + market snapshot + feature contributions)
        ↓
Market Timeline    (append decision / marks / observations / research / revisits)
        ↓
Evolution revisits (Day1 → Week1 → Month1 → Quarter → Exit)
        ↓
Outcome Attribution (decision quality × market quality × execution × portfolio)
        ↓
Lesson (confidence, applies_to, evidence_count) + genealogy links
        ↓
Meta-learning + Intelligence Dashboard
        ↓
Better future decisions (and, much later, ML on proprietary history)
```

Paper trading remains the **safe room**. Decision Intelligence is the **investor’s memory**. Observations are the **senses**.

---

## 4. Six dashboards

### D1 — Investment (business quality)

Stage 1: section completeness, MVR, MoS availability, known unknowns, **field age**  
Stage 2: ROE, ROIC, PE, P/B, FCF, debt, margins, growth, promoter, sector KPIs  
Stage 3: peer/industry averages (imported only), capital allocation, distinctiveness trend

### D2 — Trading (execution edge)

Stage 1: fills, fees, adherence, risk/trade, consecutive losses, loss limits  
Stage 2 (after sample gates): win rate, profit factor, expectancy, avg win/loss, avg R, setup split  
Stage 3 (≥300 trusted): Sharpe/Sortino/Calmar, SQN, MAE/MFE, rolling metrics, Monte Carlo

### D3 — Portfolio (book health)

Stage 1: cash, equity, holdings, sector/name exposure, net capital  
Stage 2: day/total P&L, drawdown, plan→fill fidelity  
Stage 3: beta, recovery factor, time in drawdown, curve smoothness

### D4 — Learning (becoming smarter about markets)

Stage 1: packets recorded, journals complete, open vs closed, lessons written  
Stage 2: correct vs wrong theses, repeating mistakes, advice followed/ignored, belief-change rate, **lesson reuse**  
Stage 3: which evidence axes predict outcomes; mentor usefulness; strategy improvement slope

### D5 — Research (what don’t we know?)

Stage 1: coverage, evidence vs reasoning, freshness, blocked inputs  
Stage 2: completeness radar (business/management/valuation/industry/competition/macro/news)  
Stage 3: peer-relative depth, filing latency, evidence level mix (A–G)

### D6 — Intelligence Dashboard (**Atlas-the-product**) — NEW / LOCKED

Does **not** score investments. Scores whether Atlas is becoming a better decision system.

| Metric family | Examples |
|---------------|----------|
| Completeness | research completeness, decision-packet completeness, average unknowns |
| Evidence | average evidence quality, fundamental/news/policy coverage |
| Freshness | knowledge freshness, % fields past TTL |
| Process | revisited decisions %, overdue revisits, replay coverage |
| Learning | lessons created, lessons reused, evidence_count distribution |
| Calibration | confidence vs outcome (over/under-confident) |
| Prediction | correct vs wrong predictions (decision-quality graded, not raw P&L) |
| Breadth | sector / industry / instrument coverage |
| Genealogy | % decisions with parent links; experience reuse rate |

Stage 1 ship a thin D6 (packet completeness, revisit %, lessons created, coverage holes).  
Stage 2–3 add calibration and replay accuracy.

---

## 5. Decision Intelligence subsystems

### 5.1 Observation Layer (NEW — insert before research)

Continuous, low-interpretation facts. Research later interprets; decisions cite observations.

| Observation kinds (v1) | Examples |
|------------------------|----------|
| `mgmt_event` | CEO resigns, promoter buy/sell |
| `operating_metric` | order book ↑, margins ↓, WC improved |
| `macro_event` | rate cut, oil spike |
| `policy_event` | PLI / budget / sector regulation |
| `market_event` | gap, circuit, expiry day |
| `filing_event` | AR/QR published (ref only) |
| `news_event` | allow-listed RSS item linked to symbol |

Each observation: `id`, `ts`, `symbol?`, `kind`, `payload`, `source`, `confidence`, `expires_at?`.

**Done-when (DI.Obs):** observations append to Market Timeline; research refresh can consume new observations since last run; packets may cite `observation_ids`.

### 5.2 Decision Packet v1 (immutable)

```text
decision_id
parent_decision_id?          # genealogy
derived_from_lesson_ids[]    # genealogy
ts_ist, symbol, action       # buy|sell|hold|watch|reduce
portfolio_key, mission_id, strategy_tag, setup_tag?

market_snapshot:             # LOCKED amendment
  nifty_level?, india_vix?, usdinr?
  sector_day_return?, breadth_advance?, breadth_decline?, breadth_pct?
  news_tone?, liquidity_band?, session, regime_tags[]
  # extend later: rates, oil, gold — null when unknown, never invent

prices: mark, suggested_qty, filled_qty?, fill_price?, fees?

feature_contributions:       # LOCKED amendment (signed, sum≠required)
  business, management, valuation, technical, macro, news, experience, …
  # e.g. business:+18, valuation:-6, technical:+8 → explains BUY

confidence_breakdown:        # keep % view for UI
  same axes as 0–1 or %

reasons_for[], reasons_against[]
evidence_refs[], observation_ids[], unknowns[]
expected: return_band?, holding_horizon, thesis_id, falsifiers[]
plan_link, gates (research + portfolio + trim binding)
```

**Watch/Hold are first-class.** Learning only from fills is forbidden by design.

### 5.3 Market Timeline + Decision Evolution

Append-only events per symbol (and optional index/macro stream).

| Event | Role |
|-------|------|
| `observation` | raw sense data |
| `fundamentals_update` / `research_refresh` / `thesis_change` | belief updates |
| `decision` | packet pointer |
| `revisit` | evolution checkpoint |
| `market_mark` | EOD sample |
| `outcome` / `lesson` | attribution |

**Evolution schedule (locked intent):** Day 1 → Week 1 → Month 1 → Quarter → Exit.  
Each revisit answers: thesis improved? confidence Δ? valuation Δ? management Δ? new evidence? new observations?

### 5.4 Outcome Attribution (decision quality ≠ market P&L)

On revisit/exit, grade separately:

| Dimension | Meaning |
|-----------|---------|
| `decision_quality` | A–F: given evidence then, was the decision sound? |
| `market_quality` | A–F: did beta/regime dominate (crash, melt-up)? |
| `execution_quality` | A–F: size, timing, fees, plan adherence |
| `portfolio_quality` | A–F: concentration / correlation fit |
| `thesis_correct` | yes / partial / no / unknown |
| `what_changed` | timeline event ids |
| `what_atlas_missed` | gap ids |
| `mae` / `mfe` | Stage 2+ |
| `pnl` | recorded but **not** the sole teacher |

**Hard rule:** do not update strategy priors from raw P&L alone when `market_quality` is F and `decision_quality` is A/B.

### 5.5 Research field age / decay

Every researched/fundamental field stores:

```text
value, as_of, confidence, ttl_days / expires_at, source
```

Past TTL → `stale` (already partially in IRA section TTL) — extend to **numeric fields** (ROE, PE, …), not only sections. Stale fields reduce feature contributions and raise unknowns.

### 5.6 Lessons with experience weight

```text
lesson_id, text
confidence: low|medium|high
evidence_count: N
applies_to: [manufacturing|banks|it|all|…]
derived_from_decision_ids[]
last_reinforced_at
```

One company → low confidence. Dozens of consistent cases → high. Meta-learning promotes/demotes.

### 5.7 Decision genealogy

Every packet may link:

`parent_decision_id` · `prior_thesis_id` · `derived_from_lesson_ids[]` · `supersedes_decision_id?`

Enables: “How did Atlas evolve from #241 → #482?”

### 5.8 Decision Replay

Frozen packet + timeline since + attribution + optional “would current priors still act?” (Stage 3).

### 5.9 Meta-learning (automatic weekly)

Job answers:

- Which feature contributions correlated with high `decision_quality`?  
- Which indicators never mattered?  
- Which research sections were unused or useless?  
- Which missing fields preceded poor decision_quality?  
- Which lessons repeat? Which should be retired?  
- Regime slices: VIX&lt;15 vs panic, etc. (needs market snapshots)

Writes into Intelligence Dashboard + lesson confidence updates — **not** silent strategy rewrites without playbook change-log row.

---

## 6. Storage architecture (LOCKED: Hybrid)

| Store | Role |
|-------|------|
| **Postgres** (`decision.*` or agreed schema) | Authoritative packets, timeline events, observations, lessons, genealogy edges — query/ML |
| **JSON mirrors** under `/data/atlas_data/investment/…` | Replay, debugging, human reading, backup, git-friendly exports |
| Existing IRA / thesis_tracker / KPI JSON | Keep; link by ids; migrate gradually — no big-bang rewrite |

Write path: Postgres commit → async/safe JSON mirror. Read path for analytics: SQL. Read path for Replay UI: either (prefer packet join).

---

## 7. What already exists (reuse)

| Existing | Reuse as |
|----------|----------|
| Decision Engine + `decision_id` | Packet spine |
| OI-F1 / Experience journals | Soft lesson channel |
| IRA dossiers, section TTL, outcomes | Research + partial decay |
| Thesis Tracker + priors | Closed attribution seed |
| Score axes / dual confidence | Breakdown + contributions source |
| Session notes + trading KPIs | Process scorecard |
| Sector packs, compare, policy catalog | Lenses / macro |
| Fundamentals import schema | D1 inputs once populated |
| Interesting events / RSS allow-list | Observation sources |

**Gap:** side effects of fills ≠ first-class Observation → Packet → Evolution → Attribution → Meta-learning product.

---

## 8. Phased delivery (implementation order — LOCKED priority)

Operator-preferred order after review:

### DI.0 — Plan lock (this doc) ✅

Playbook linked; `OI-DI0` registered; no code required for lock itself.

### DI.1 — Decision Packets v1 ⭐ first code

Immutable packets with: market snapshot, feature contributions, confidence breakdown, reasons, unknowns, genealogy hooks (nullable parents), strategy_tag, Watch/Hold included.  
Hybrid write. API `GET /v1/market/decisions/{id}`. Evening mail lists decisions.

**Out of scope for DI.1:** NN, Sharpe, peer medians, full meta-learning.

### DI.2 — Market Timeline + evolution revisits

Append timeline; Day1/Week1/… schedule; “what changed?” diffs; Learning dashboard open/closed counts.

### DI.Obs — Observation Layer

Ship **immediately after DI.2** (or thin v0 in parallel with DI.2 if cheap): observation events feeding timeline + research. Do not skip — hardest to retrofit if packets never cite observations.

### DI.4 — Fundamentals & peers (parallel from DI.1 day one)

Populate fundamentals; optional `industry_*_median` imports; MoS/PE honesty; stop empty-PE theater.

### DI.3 — Staged KPI dashboards (D1–D5) + sample gates

Core-20; never mix strategy tags; enforce 30/100/300 gates.

### DI.Attr — Outcome attribution + Replay

Multi-axis quality grades; MAE/MFE when ready; Replay UI; priors consume decision_quality not raw P&L alone.

### DI.5 — Process proxies (FOMO/revenge/hesitation/…)

✅ Shipped — countable process flags on packets + day scorecard (`GET /v1/market/process-proxies`). Atlas has no emotions; map:

| Human idea | Atlas proxy |
|------------|-------------|
| FOMO | Buy after ≥3% gap without plan rank |
| Revenge | Re-entry within 24h after a loss |
| Hesitation | Missed plan candidates / low plan→fill |
| Plan violation | Buy outside plan without alt reason |
| Overconfidence | Full size at low investment_confidence |
| Journal completion | Packet completeness + reasons coverage |

### DI.6 — Intelligence Dashboard (D6) + meta-learning weekly job

✅ Shipped — richer D6 (`intelligence_score` + Appendix B answers), weekly
`decision_meta_learning` worker, `GET/POST /v1/market/meta-learning`, evening + weekly
mail. **Proposals only** — never silent strategy rewrites.

### DI.7 — ML-ready export

✅ Shipped (gated) — `GET/POST /v1/market/ml-export`. Export JSONL of decide-time
features + graded outcomes only when a `strategy_tag` has ≥300 closed attributable
exits (or `force_override` + `override_note`). Offline rules-baseline walk-forward
stub included. **`live_nn_trading` always false** until learned beats rules on paper.

---

## 9. Locked principles

1. **P10 remains** — simulation only.  
2. **No new Intelligence** — Market Program capability on Decision + Experience + Research (+ Observation as data plane).  
3. **Freeze beliefs at decide-time** — never rewrite packets.  
4. **Watch is a decision.**  
5. **Never invent fundamentals or industry averages.**  
6. **Never mix strategy statistics.**  
7. **Sample-size gates** — 30 / 100 / 300.  
8. **Playbook = strategy; this plan = architecture.**  
9. **ML trains on decisions + context + evidence + outcomes + corrections** — not OHLCV alone.  
10. **Honesty over coverage theater.**  
11. **Decision quality ≠ market P&L** — attribution must separate them.  
12. **Hybrid storage** — Postgres authoritative + JSON mirrors.  
13. **Stale data decays** — aged fields lose influence.  
14. **Lessons carry confidence + applicability + evidence_count.**  
15. **Meta-learning proposes; playbook change-log accepts** strategy changes.  
16. **D6 measures Atlas intelligence**, not portfolio vanity.

---

## 10. Strategy tags v1 (expand later)

`sma_cross_rsi` · `next_alternative` · `research_forced_hold` · `portfolio_trim` · `policy_block` · `session_closed` · `plan_watch` · `plan_hold` · `manual_operator`

Expect ORB / pullback / mean-reversion / etc. when those setups exist — each gets its own stats lane.

---

## 11. Status checklist

1. ✅ Plan locked with review amendments.  
2. ✅ `OI-DI0` in [`OPEN_ITEMS.md`](OPEN_ITEMS.md).  
3. ✅ Playbook linked and strategy/architecture split preserved.  
4. ✅ Operator decisions locked (Hybrid, Watch/Hold, 30/100/300, DI.1∥DI.4, tags).  
5. ✅ **Implementation finalization (§12)** — DI.1 sprint is the next coding task.  
6. ✅ Code DI.1 (migration `0045`, store, paper + plan_watch wire, API, evening mail, tests).  
7. ✅ Kick DI.4 thin fundamentals gaps honesty (coverage + learner_gaps on GET fundamentals / evening).  
8. ✅ DI.2 Market Timeline (migration `0046`, revisits Day1→Quarter, worker, API).  
9. ✅ DI.Obs Observation Layer (migration `0047`, market/news/policy → timeline, packet citation, research since-window).  
10. ✅ DI.Attr Outcome attribution + Replay (migration `0048`, DQ≠MQ grades, priors hard rule, sell/revisit wire).  
11. ✅ Deepen DI.4 — learner gap template + industry_*_median import honesty + PE/FCF coverage (no migration; see [`SCREENER_FUNDAMENTALS_IMPORT.md`](SCREENER_FUNDAMENTALS_IMPORT.md)).  
12. ✅ DI.3 Staged KPI dashboards + sample gates (D1–D6 Stage-1, per-`strategy_tag` lanes, API + evening + learner UI; no migration).  
13. ✅ DI.5 Process proxies (FOMO/revenge/hesitation/plan violation/overconfidence/journal; packet flags + day scorecard; no migration).  
14. ✅ DI.6 Intelligence Dashboard + meta-learning weekly job (proposals only; no migration).  
15. ✅ DI.7 ML-ready export gated (≥300 trusted / override) + offline rules baseline; no live NN (no migration).

---

## 12. Implementation finalization (READY TO CODE)

This section is the build contract. Later phases stay sketched in §8; **only DI.1 is fully specified for the first sprint.** Do not expand scope mid-sprint.

### 12.1 Sprint goal — DI.1 Decision Packets v1

**Ship:** every material paper-trading / plan decision writes an **immutable Decision Packet** (Postgres + JSON mirror), including Watch/Hold, with market snapshot + feature contributions + reasons + unknowns + strategy_tag. Operator can fetch by id; evening report lists today’s packets.

**Do not ship in DI.1:** timeline evolution engine, observation ingest, Replay UI, D6, meta-learning, Sharpe, peer medians, NN.

**Parallel (thin, non-blocking):** DI.4 — document + start fundamentals import path for learner symbols (can be operator CSV drop); packets tolerate null fundamentals.

### 12.2 Postgres schema (migration `0045`)

Schema name: `decision`.

```sql
-- packets: append-only; UPDATEs forbidden in application code
CREATE TABLE decision.packets (
  decision_id        UUID PRIMARY KEY,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  ts_ist             DATE NOT NULL,
  symbol             TEXT NOT NULL,
  action             TEXT NOT NULL,  -- buy|sell|hold|watch|reduce
  portfolio_key      TEXT NOT NULL,
  mission_id         TEXT,
  strategy_tag       TEXT NOT NULL,
  setup_tag          TEXT,
  parent_decision_id UUID REFERENCES decision.packets(decision_id),
  prior_thesis_id    TEXT,
  engine_decision_id TEXT,           -- existing Decision Engine id when present
  fill_trade_id      TEXT,           -- sim trade id when filled
  payload            JSONB NOT NULL, -- full frozen packet (see 12.3)
  payload_version    TEXT NOT NULL DEFAULT 'di.packet.1'
);

CREATE INDEX decision_packets_symbol_ts ON decision.packets (symbol, created_at DESC);
CREATE INDEX decision_packets_portfolio_ts ON decision.packets (portfolio_key, ts_ist DESC);
CREATE INDEX decision_packets_action_ts ON decision.packets (action, created_at DESC);
CREATE INDEX decision_packets_strategy ON decision.packets (strategy_tag, created_at DESC);

-- stub tables created empty in 0045 so DI.2/Obs don’t renumber migrations
CREATE TABLE decision.timeline_events (
  id            UUID PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol        TEXT NOT NULL,
  kind          TEXT NOT NULL,
  decision_id   UUID REFERENCES decision.packets(decision_id),
  payload       JSONB NOT NULL DEFAULT '{}',
  payload_version TEXT NOT NULL DEFAULT 'di.timeline.1'
);
-- populated starting DI.2

CREATE TABLE decision.observations (
  id            UUID PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol        TEXT,
  kind          TEXT NOT NULL,
  payload       JSONB NOT NULL,
  source        TEXT,
  confidence    TEXT,
  expires_at    TIMESTAMPTZ,
  payload_version TEXT NOT NULL DEFAULT 'di.obs.1'
);
-- populated starting DI.Obs
```

Application rule: **no UPDATE/DELETE on `decision.packets`**. Corrections = new packet + `supersedes` link inside payload / genealogy fields in a later column if needed.

### 12.3 Frozen payload shape (`di.packet.1`)

```json
{
  "version": "di.packet.1",
  "decision_id": "...",
  "ts_ist": "2026-08-05",
  "symbol": "EICHERMOT.NS",
  "action": "buy",
  "portfolio_key": "india_equity_learner",
  "mission_id": "...",
  "strategy_tag": "sma_cross_rsi",
  "setup_tag": null,
  "parent_decision_id": null,
  "derived_from_lesson_ids": [],
  "prior_thesis_id": null,
  "engine_decision_id": "...",
  "market_snapshot": {
    "session": "nse_equity",
    "regime_tags": [],
    "nifty_level": null,
    "india_vix": null,
    "usdinr": null,
    "sector": "Automobile",
    "sector_day_return": null,
    "breadth_advance": null,
    "breadth_decline": null,
    "breadth_pct": null,
    "news_tone": null,
    "liquidity_band": null,
    "note": "nulls allowed; never invent"
  },
  "prices": {
    "mark": 7921.0,
    "suggested_qty": 2,
    "filled_qty": 2,
    "fill_price": 7921.0,
    "fees": 0.0
  },
  "feature_contributions": {
    "business": 0,
    "management": 0,
    "valuation": 0,
    "technical": 8,
    "macro": 0,
    "news": 0,
    "experience": 0,
    "research": 0,
    "portfolio_fit": 0
  },
  "confidence_breakdown": {
    "business": null,
    "management": null,
    "valuation": null,
    "technical": 0.7,
    "macro": null,
    "news": null,
    "experience": null,
    "research_confidence": "low",
    "investment_confidence": "medium",
    "overall": 0.55
  },
  "reasons_for": ["SMA fast above slow", "..."],
  "reasons_against": [],
  "evidence_refs": [],
  "observation_ids": [],
  "unknowns": ["pe_missing", "fcf_missing"],
  "expected": {
    "holding_horizon": "position",
    "return_band": null,
    "thesis_id": null,
    "falsifiers": []
  },
  "plan_link": {
    "rank": null,
    "suggested_notional": null,
    "in_daily_plan": false
  },
  "gates": {
    "research": {},
    "portfolio": {},
    "trimmed_from": null,
    "binding": null
  }
}
```

**Completeness score (D6 precursor):** fraction of non-null critical fields; store on write as `payload.meta.completeness` (0–1) for Intelligence Dashboard Stage 1 later.

### 12.4 JSON mirror layout

```text
/data/atlas_data/investment/decisions/
  by_id/<decision_id>.json
  by_day/<portfolio_key>/<YYYY-MM-DD>.jsonl   # one packet JSON per line
```

Write: Postgres insert success → best-effort mirror (log mirror failures; do not roll back packet).

### 12.5 Code touch list (DI.1)

| Area | Path / action |
|------|----------------|
| Migration | `database/migrations/0045_decision_intelligence.sql` (+ registry bump; OI-C7 → next `0046`) |
| Packet model + store | `atlas/investment/decision_packets.py` (build, validate, save, get, list_day) |
| Repo | `atlas/repositories/decision_repo.py` (or under investment if cleaner) |
| Builder | Pull snapshot from existing score/awareness/gates/strategy context; null-safe market_snapshot |
| Wire paper worker | `atlas/workers/paper_trading.py` — after decide / on hold\|buy\|sell\|watch paths, persist packet; attach `decision_id` on fills |
| Wire plan watches | Daily plan path: emit `plan_watch` / `plan_hold` packets for top candidates not filled (batch once per IST day, idempotent) |
| API | `GET /v1/market/decisions/{decision_id}`, `GET /v1/market/decisions?portfolio_key=&ist_date=&symbol=` |
| Bootstrap | Register packet store on container |
| Evening mail | `format_evening_report` — “Decisions today (N)” section from list_day |
| Playbook | Change-log row when DI.1 ships |
| Tests | Hermetic: build packet; immutability; watch action; list_day; API; worker writes packet on buy + hold |

### 12.6 Market snapshot v1 sources (best-effort)

| Field | Source in DI.1 |
|-------|----------------|
| `session` | existing market session helper |
| `sector` | universe membership / dossier |
| `nifty_level` / `india_vix` / breadth / FX | **null unless already available** via market_reader without new scrape; add fetchers in DI.2 if missing |
| `regime_tags` | derive lightly later; empty list OK |

Never invent VIX/Nifty. Completeness rises as feeds land.

### 12.7 Feature contributions v1 heuristic

Until meta-learning exists, derive signed contributions from existing axes:

- Map investment score axes × weights × sign(path) into integer-ish contributions (−20…+20).  
- Technical: from SMA margin / RSI band.  
- Valuation: from MoS when present else 0 + unknown flag.  
- Missing research → 0 contribution + `unknowns` entry — **do not fake positive business score**.

Document formula in module docstring; playbook notes “heuristic v1”.

### 12.8 API contract

```http
GET /v1/market/decisions/{decision_id}
→ { "packet": { ... }, "mirror_path": "...", "version": "di.packet.1" }

GET /v1/market/decisions?portfolio_key=india_equity_learner&ist_date=2026-08-05
→ { "count": N, "items": [ {summary...} ], "ist_date": "..." }

GET /v1/market/decisions?symbol=EICHERMOT.NS&limit=20
→ recent packets for symbol
```

No PATCH/DELETE.

### 12.9 DI.1 acceptance tests (done-when)

1. Migration `0045` applies clean on empty and existing Atlas DB.  
2. Simulated buy in hermetic paper test creates ≥1 row in `decision.packets` with `action=buy`, non-empty `strategy_tag`, `payload_version=di.packet.1`.  
3. Hermetic hold/watch path creates packet with `action` in `{hold,watch}` even when no fill.  
4. Packet JSON on disk mirrors Postgres payload (or test doubles).  
5. `GET /v1/market/decisions/{id}` returns frozen payload; mutating dossier afterward does not change stored packet.  
6. Evening preview includes a “Decisions today” block when packets exist for IST date.  
7. Null fundamentals do not crash builder; `unknowns` lists missing PE/FCF when absent.  
8. No UPDATEs issued to `decision.packets` in code paths (grep/test guard).

### 12.10 Explicit non-goals for DI.1 sprint

- Timeline revisit scheduler  
- Observation ingest workers  
- Replay UI  
- Intelligence Dashboard UI  
- Profit factor / Sharpe displays  
- Industry average PE invention  
- Changing SMA strategy knobs (strategy changes stay in playbook process)

### 12.11 Build sequence inside DI.1

1. Migration `0045` + empty timeline/observations stubs  
2. `decision_packets` module (schema validate + completeness)  
3. Repo + container registration  
4. Builder from paper-trading context  
5. Wire worker (buy/sell/hold)  
6. Wire daily plan watch/hold batch  
7. API routes  
8. Evening mail section  
9. Tests + playbook change-log “DI.1 shipped”  
10. Start DI.4 fundamentals drop docs/operator path in parallel

### 12.12 After DI.1 — next tickets (do not start until DI.1 green)

| Ticket | Depends on |
|--------|------------|
| DI.2 Timeline + Day1/Week1 revisits | packets exist |
| DI.Obs Observation Layer | timeline table |
| DI.4 fundamentals coverage (parallel OK) | import UX |
| DI.Attr quality grades + Replay | timeline + exits |
| DI.3 KPI dashboards + gates | closed sells count |
| DI.6 Intelligence Dashboard | completeness + revisits |
| DI.7 ML export | ≥300 trusted |

### 12.13 Operator green light

**This finalize marks the plan implementation-ready.** Coding of DI.1 may begin on the next implementation turn without further architecture debate unless a locked principle must change (then amend this doc + playbook change-log first).

---

## Appendix A — Core-20 → dashboard map

| Core KPI | Dashboard | Stage |
|----------|-----------|-------|
| Net P&L | D2/D3 | 1 |
| Win Rate / Profit Factor / Expectancy | D2 | 2 (+gates) |
| Avg Win / Loss / R | D2 | 2 |
| Max Drawdown / Risk per Trade | D3 | 1–2 |
| Consecutive Losses | D2 | 1 |
| Rule Adherence / Journal completion | D4 | 1 |
| Setup / Strategy stats | D2 | 2 |
| Market condition performance | D2 | 2 (needs snapshots) |
| Holding time / MAE/MFE | D2 | 2–3 |
| Weekly improvement | D4 | 2 |
| Packet completeness / revisit % / lesson reuse / calibration | **D6** | 1–3 |

## Appendix B — Weekly Learning + Intelligence questions

**Markets (D4):** most common mistake; best/worst setup; regime fit; stop/repeat; plan followed %; weakness.  

**Atlas (D6):** incomplete packets %; overdue revisits; stale field %; lessons created vs reused; overconfidence rate; observation→decision citation rate; genealogy coverage.

## Appendix C — Non-goals (v1–v3)

- Live broker execution  
- ToS-violating scrapes  
- Neural nets before DI.7 gates  
- New top-level Intelligence OS  
- Invented industry averages  
- Teaching from raw P&L when market_quality is catastrophic and decision_quality was sound  
