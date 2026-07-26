# Autonomous Investment Learner — Bridging Plan (Indian Markets)

> **Status:** 🔒 **LOCKED** (operator 2026-07-25) · **§14 Q9–Q13 locked** · **IL.3–IL.4 + IL.10 + OX.2–OX.4 ✅ shipped** · **Date:** 2026-07-25  
> **Scope:** India-first · simulation execution only (P10) · cash-equity **autonomous** learner first · multi-instrument **sim capability** retained  
> **Parents:** [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) ·
> [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) ·
> [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) ·
> [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md)  
> **Open items:** `OI-IL0` (Universe → Rank → Plan → Simulate) · `OI-IL-OX` (orchestration / operator experience ship-along)

---

## 0. One-sentence verdict

**You wanted an autonomous investment learner. Atlas today ships a decision-and-ledger slice that trades *configured* symbols. The Market Intelligence Program (M1–M7) is the right house; the missing front door is stock selection — an Investment Universe Manager — not a new “Intelligence.” A shared Simulation Engine plus multiple virtual portfolios make F&O/commodities/ETF demos possible without derailing the cash-equity learner. The next leap in *felt* autonomy also needs orchestration and operator experience (intent → plan → goals → progress), not only better extraction.**

---

## 1. Two problems (why it feels wrong)

### What you expect (mental model)

```
Atlas has ₹10,000 (virtual)
        ↓
Study the market (breadth, sectors, session)
        ↓
Study companies (fundamentals, filings)
        ↓
Study news + events
        ↓
Choose stocks from a large universe
        ↓
Buy / monitor / sell virtually
        ↓
Record every action + reason
        ↓
Learn from success / failure
        ↓
Become better → repeat forever
```

Paper trading here is only the **safe room**. The product is the **investor**.

### What the flagship path still does (implementation center of gravity)

```
Configured symbols  (YOU pick RELIANCE.NS, TCS.NS, …)
        ↓
Price feed (replay or live adapter)
        ↓
Technical indicators
        ↓
Decision Engine → Buy / Sell / Hold
        ↓
Virtual ledger
```

That answers: *“Given these stocks, should I buy or sell?”*  
It does **not** answer: *“Find the best opportunities yourself.”*

That is why config still looks like:

```json
"instruments": [
  {"symbol": "RELIANCE.NS"},
  {"symbol": "TCS.NS"}
]
```

**There is no Stock Selection capability yet.** Observation / company / news workers largely share the same constraint: they watch what you name.

---

## 2. Honest map of Market Intelligence today

The locked plan [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) already describes seven missions. Much of the **scaffolding** shipped (templates, Program UI, readers, ledger profiles, mentor, context API). Capability depth is uneven.

| # | Mission | Scaffolding | Operator reality today |
|---|---------|-------------|------------------------|
| **M1** | Market Observer | ✅ worker + MarketReader | Watches **configured** symbols; interesting-event scoring exists |
| **M2** | Company Intelligence | ✅ worker + adapters | Mostly **config_seed** / skeletons; official NSE/BSE/filings still gated |
| **M3** | News Intelligence | ✅ worker | Needs headlines/items or feeds you supply; not a full India news firehose |
| **M4** | Event Research | ✅ worker → Jobs | Triggered from interesting moves — still on watched symbols |
| **M5** | Decision Simulation | ✅ (`paper_trading` = compat alias) | Strongest slice: decide + sim fill + experience |
| **M6** | Portfolio Ledger | ✅ + Broker Profiles | Fees/tax schedules exist for sim; not multi-portfolio isolation yet |
| **M7** | Investment Mentor | ✅ | Lessons bias future advice when experiences exist |
| **—** | **Investment Universe / Rank / Pick** | ❌ | **Missing — the blocker for autonomous learning** |

**Asset replay** (“replay a registered `market_data` asset”) is a **developer / regression** tool: deterministic backtests. Keep it internally. It must **not** be the primary operator story once live observation works. Operator primary path = live (or delayed) market data → Program cadence → sim ledger.

Rough maturity of *your* vision: **~25–35%** (platform + M5/M6 spine strong; selection + deep India research + orchestration thin).

---

## 3. What “asset replay” is (plain language)

| | Asset replay | Live observation |
|-|--------------|------------------|
| **Input** | JSON/CSV OHLCV you registered once | Bars from a market-data adapter (Yahoo / Polygon / …) |
| **Who it’s for** | Developers, hermetic tests, strategy A/B | The investment learner you want |
| **Feels like** | “Play this tape again” | “Watch the market as it happens” |
| **Operator default?** | No (keep as `feed_mode: asset_replay`) | Yes (`feed_mode: live` + session hours) |

Replay does **not** mean Atlas is “connected to the market.” It means Atlas is **re-reading a file**.

---

## 4. Architecture: Simulation Engine ≠ one instrument class

Do **not** treat “paper trading” as a single product. Separate:

```
Simulation Engine  (platform / shared Market Program core)
        │
        ├── Cash Equities          ← first autonomous learner (IL ship)
        ├── Futures                ← operator-selected sim when asked
        ├── Options
        ├── Commodities
        ├── Currency
        ├── ETF
        └── Crypto (future)
```

| Layer | Changes per instrument class? |
|-------|-------------------------------|
| Simulation Engine (fills, ledger hooks, journal, P10) | **No** — shared |
| Market rules (lot size, expiry, margin, session) | **Yes** — domain pack |
| Fee / Broker Profile | **Yes** |
| Risk / Policy | **Yes** |
| Universe + ranking + autonomous portfolio construction | **Cash equities first**; other classes later |

This matches Platform → Programs → Missions → Workers: each instrument family is a **domain pack** (or a thin Program variant), not a new Intelligence (P5).

---

## 5. Recommendation: M0 + domain pack (no new Intelligence)

| Option | Verdict |
|--------|---------|
| New top-level “Investment Intelligence” | ❌ Reject — duplicates Market Program / violates P5 |
| New kernel OS | ❌ Reject — Knowledge / Experience / Decision / Planning already exist |
| **M0 Investment Universe Manager + `atlas/investment/`** | ✅ **Locked** |
| Keep M5 as-is and only add live feeds | ❌ Insufficient — still “you pick symbols” |

### Shape

```
Indian Markets pack (World Model)     already started (WM.1)
        +
atlas/investment/  (domain package — NOT an Intelligence)
  universe.py      NIFTY50 / 100 / 500 membership, sectors
  ranking.py       score → ranked opportunities
  watchlists.py    active / candidate / blocked lists
  daily_plan.py    morning plan object for M5
  portfolios.py    multi-portfolio registry (IL-Q8)
        +
Mission M0: investment_universe
  cadence: pre-open + periodic refresh
  output: watchlist + ranked opportunities → Knowledge / Context API
        ↓
M1–M4 enrich those names (not a random operator list)
        ↓
M5 Decision Simulation (per portfolio):
  “Of ranked opportunities + this portfolio’s constraints, what do I do?”
        ↓
M6 Ledger (one book per virtual portfolio)
        ↓
M7 Mentor → Experience OS (scoped per portfolio / strategy tags)
```

**Service vs mission:** domain package + M0 is enough. Prefer **not** a new long-lived kernel “Investment Intelligence Service” unless volume later forces one.

---

## 6. Target daily workflow (Indian cash-equity learner)

Focus of **autonomous** learning: **NSE cash equities** (BSE as data allows). Times illustrative (IST).

### Pre-open (~08:45)

```
Download / refresh market snapshot (indices, breadth if available)
        ↓
M0: refresh universe membership (NIFTY50 → 100 → 500)
        ↓
M2: update company facts/ratios for watchlist + top movers (compliant sources)
        ↓
M3: overnight news → claims → (optional) verify
        ↓
M0: re-rank → produce Daily Investment Plan (candidates, sizes, avoids)
        ↓
Wait for open
```

### Open (~09:15) → continuous

```
M1: observe live bars / volume for plan + positions
        ↓
M5: execute *simulated* buys/sells/holds under Policy + Broker Profile
        ↓
M6: update that portfolio’s ledger (cash, lots, fees, equity)
        ↓
M4: if interesting event → research Job
        ↓
Every N minutes: refresh marks, news watch, adjust confidence — not thrash
```

### Close

```
Mark portfolio
        ↓
Evaluate vs plan
        ↓
Write Experience (outcome + lesson) tagged to portfolio
        ↓
M7 (weekly): mentor synthesis → bias future ranks / decisions
```

**Capital model:** e.g. virtual ₹10,000 on the India equity learner portfolio; **no** broker funds; commissions/TDS via Broker Profile. Other portfolios (swing, F&O demo, …) keep **separate** capital and ledgers (IL-Q8).

---

## 7. Locked decisions (operator 2026-07-25)

| # | Locked decision |
|---|-----------------|
| **IL-Q1** | ✅ **M0 + `atlas/investment/` domain pack** (no new Intelligence) |
| **IL-Q2** | ✅ **NIFTY50 → NIFTY100 → NIFTY500** |
| **IL-Q3** | ✅ **M0 chooses by default**; operator can always pin symbols |
| **IL-Q4** | ✅ **Live market feed** is the primary operator workflow; **replay** remains for testing and CI |
| **IL-Q5** | ✅ **₹10,000 India learner** preset (configurable) |
| **IL-Q6** | ✅ **Screener-style integration later** (IL.8) |
| **IL-Q7** | ✅ **Cash equities are the first autonomous learner.** Atlas must still support **operator-selected paper simulations** for Futures, Options, Commodities, ETFs, Currency, etc. Each instrument class uses its **own market rules, fee model, and risk model**; the **core Simulation Engine remains shared**. Expansion is incremental — it does not replace the equity learner. |
| **IL-Q8** | ✅ **Multiple independent virtual portfolios.** Examples: Long-term Investment, Swing, Intraday, F&O Demo, Dividend, AI Experiment #N. Each has starting capital, instrument universe, strategy, Broker Profile, ledger, experience history, and performance stats — so ₹10k equity + ₹50k futures + ₹1L momentum can run **without mixing books**. |

### IL-Q7 clarified (two questions)

| Question | Answer |
|----------|--------|
| What should Atlas become intelligent at **first**? | **Cash equities** |
| Can Atlas simulate Futures (etc.) tomorrow if I **ask**? | **Yes** — operator-selected sim; separate rules pack; not phase-1 autonomous ranking |

### IL-Q8 clarified

Portfolios are first-class simulation **books**, typically one Mission/Program instance (or config-scoped ledger id) each — not one shared cash pile. Experiences and mentor lessons should be **attributable** to a portfolio (tags / `portfolio_id`) so strategies do not contaminate each other.

---

## 8. Orchestration & operator experience (ship-along)

The investment pipeline can improve a lot while Atlas still *feels* like a command console. The next leap in **perceived** autonomy is orchestration and interaction — without replacing Knowledge / Decision / Experience.

| Gap | What Atlas should do | Why it matters |
|-----|----------------------|----------------|
| **Intent understanding** | Rewrite operator requests into actionable objectives (“start a ₹10k India learner” → Program + portfolio + M0–M7 wiring) | Stops forcing the operator to speak JSON / template names |
| **Planning** | Decompose goals into executable steps (extend Planning OS / Job planner; show the plan before/while running) | Feels collaborative, not one-shot commands |
| **Goal management** | Track **long-running objectives** (portfolios, “become better at NIFTY cash”) instead of only isolated Jobs | Matches the forever learner loop |
| **Operator experience** | Communicate plans, progress, and outcomes (Program cockpit, journals, “what I’m doing / why / next”) | Collaboration with an intelligent system |

These are **platform-facing** but proven on the Market Program first.

| ID | Slice | Delivers |
|----|-------|----------|
| **OX.1** | **Intent → objective** | Chat/Job rewrite layer: NL → structured objective (`program`, `portfolio`, `capital`, `universe`, `mode=auto\|pin`) |
| **OX.2** | **Plan visibility** | Planning OS returns steps the UI/Chat can show; “Start India learner” shows plan before activate |
| **OX.3** | **Goal objects** | Durable goals linked to Program/portfolio (`status`, `progress`, `last_outcome`); survive reboot |
| **OX.4** | **Progress narrative** | Periodic operator-facing summary (journal roll-up / Program cockpit): plan → actions → P&L → lessons |

**Rule:** OX slices must not invent a new Intelligence; they orchestrate existing Missions, Planning OS (PA.1), Jobs, and Programs.

---

## 9. Capability gap → ship slices

Ordered so each slice makes M5 less blind — and OX ship-along so the product *feels* autonomous.

| ID | Slice | Delivers | Depends on |
|----|-------|----------|------------|
| **IL.0** | Plan locked + `OI-IL0` / `OI-IL-OX` | Shared mental model | — ✅ |
| **IL.1** | **Universe pack** | NIFTY50 (then 100/500) + sectors in World Model / `atlas/investment` | WM.1 |
| **IL.2** | **M0 `investment_universe` mission** | Watchlists + ranked candidates → context; **M5 auto-loads when `instruments` empty** | IL.1, MCA.1 |
| **IL.3** | **Ranking v0** | Liquidity + momentum + simple quality + policy prefer/avoid | IL.2, M1 |
| **IL.4** | **Wire M1–M4 to watchlist** | Default to M0 lists; pin override remains | IL.2 |
| **IL.5** | **India data depth** | Live/delayed `.NS` path; hermetic quality seed + Yahoo for M0/M1; filings still ToS-gated | OI-D1, MI4/MI5 ✅ v0 |
| **IL.6** | **Daily Investment Plan** | Planning OS object from M0 watchlist + morning cron; OX.4 surfaces it | PA.1, SCHED.1 ✅ v0 |
| **IL.7** | **Ledger realism** | Broker Profile TDS + fee JSON + withdraw/deposit; India learner defaults to zerodha | MI.6 ✅ v0 |
| **IL.8** | **Screener-class signals** | Operator JSON snapshot + bars-derived signals → M0 quality; no scrape | MI5 ✅ v0 |
| **IL.9** | **Operator happy path** | ₹10k India learner preset + `/v1/learner/happy-path` checklist — no JSON instruments | Program UI ✅ v0 |
| **IL.10** | **Multi-portfolio (IL-Q8)** | Portfolio registry; isolated ledger + experience scope; concurrent learners | IL.7, M6 |
| **IL.11** | **Simulation Engine instrument packs** | Shared engine + cash-equity pack first; Futures/Options/… packs as operator-selected sim (rules/fees/risk only) | IL.10 |
| **OX.1–OX.4** | **Orchestration / UX** | Intent rewrite, plan visibility, goals, progress narrative | PA.1, Programs, Chat/Jobs |

**Explicit non-goals**

- Real broker login / real orders (P10)  
- Autonomous F&O / commodity **ranking & portfolio construction** in phase 1 (sim-on-request is in scope per IL-Q7)  
- Global (US/EU) universes as the first learner  
- Guaranteed alpha — Atlas learns; it does not promise profit  

---

## 10. How M5 should change (contract)

### Today

```
instruments[] required (or idle)
```

### Target

```
if instruments explicitly set → honor operator pin (manual mode)
else → load M0 ranked opportunities (auto mode) for this portfolio’s universe
         ∩ Policy
         ∩ cash / exposure / Broker Profile
         → decide via shared Simulation Engine + instrument-class rules
```

Decision rationale must cite:

- Universe rank reason (auto mode)  
- Mission Context (company / news / world facts)  
- Mentor advice / experience bias (portfolio-scoped)  
- Policy blocks  

Replay remains available as `feed_mode: asset_replay` for tests — not the Program default.

---

## 11. Success criteria

1. Operator starts **Market Intelligence** with an **India ₹10k learner** preset — **no** hand-built `instruments` list.  
2. Atlas maintains a **NIFTY-based universe**, ranks a short watchlist, and M5 only decides among those + open positions (auto mode).  
3. Pre-open plan and intraday sim fills appear in journal with **cited** context (not indicator-only).  
4. Ledger shows cash, positions, fees; net equity updates after each sim fill.  
5. Losses/wins write Experiences; Mentor changes later behavior.  
6. **Zero** broker trading credentials anywhere.  
7. Asset replay still passes hermetic tests but is not the console happy path.  
8. Operator can create a **second virtual portfolio** (e.g. F&O Demo) with separate capital/ledger without mixing the equity learner.  
9. Operator can ask Atlas in NL to start/monitor the learner and see a **plan + progress**, not only raw job steps (OX).

---

## 12. Relationship to existing docs

| Doc | Role after this plan |
|-----|----------------------|
| `MARKET_INTELLIGENCE_MISSIONS_PLAN.md` | Program bible (M1–M7); this doc adds **M0 + IL/OX ship order** |
| `MISSIONS_OPERATOR_GUIDE.md` | Happy path = India learner; live primary; replay for CI |
| `OPEN_ITEMS.md` | **`OI-IL0`**, **`OI-IL-OX`** |
| `ATLAS_MISSION_PHILOSOPHY.md` | MP7: simulate execution; observe for real — this plan adds selection + multi-book sim |
| `ATLAS_PLATFORM_ARCHITECTURE.md` | Planning OS / Programs — OX extends operator-facing use of PA.1 |

---

## 13. Checklist

- [x] Operator locks IL-Q1…Q8 (2026-07-25)  
- [x] Promote status → **LOCKED**  
- [x] Register `OI-IL0` / `OI-IL-OX` in `OPEN_ITEMS.md`  
- [x] Implement IL.1 (NIFTY50 pack) — `atlas/investment/universe.py`  
- [x] Implement IL.2 (M0 mission + M5 auto instruments)  
- [x] Implement OX.1 (intent → India learner Program start)  
- [x] Implement IL.3 (ranking + WHY ± + cold-start learning) — `atlas/investment/ranking.py`  
- [x] Implement IL.4 (watchlist wiring M1/M2/M3) — `atlas/investment/watchlists.resolve_*`  
- [x] Implement OX.2 (plan visibility — preview / start now / API immediate)  
- [x] Implement IL.10 (multi-portfolio + persona) — `atlas/investment/portfolios.py`  
- [x] Implement OX.3 (durable goals — objectives first) — `atlas/goals` + `system.goals`  
- [x] Implement OX.4 (progress narrative) — `GET /v1/goals/{id}/progress`, Chat learner status  
- [x] Update operator guide: “Atlas chooses; you constrain; multiple books OK”  
- [x] Keep replay for tests; demote in UI / template copy  
- [x] Document Simulation Engine + instrument packs (IL.11) without blocking equity learner  
- [x] Implement IL.11 packs (`atlas/investment/packs` + worker hooks + stub gaps)  
- [x] Implement IL.5 v0 — hermetic quality_seed + Yahoo for India learner M0/M1
- [x] Implement IL.6 v0 — Daily Investment Plan + morning cron + progress bullet
- [x] Implement IL.7 v0 — TDS/fee breakdown + withdrawal sim + zerodha India default
- [x] Implement IL.8 v0 — screener snapshot API + M0 merge (no scrape)
- [x] Implement IL.9 v0 — happy-path guide + learner status checklist  

---

## 14. Remaining work — discussion & implementation design (2026-07-25)

> **Status of this section:** §14 remaining work **shipped** (IL.3–IL.4, IL.10, OX.2–OX.4).  
> **Shipped already:** IL.1–IL.4, IL.10, OX.1–OX.4.  
> **Docs polish:** operator guide + IL.11 **implemented** (§15). **IL.5–IL.9 v0 shipped** (§16–20). India learner spine complete; F&O packs, Atlas holidays, and filing refs ready.

### 14.0 Recommended ship order

```
IL.3  Ranking v1          ← makes auto-picks meaningful (+ WHY THIS STOCK?)
   ↓
IL.4  Watchlist wiring    ← M1/M2/M3 stop needing hand-typed symbols
   ↓
OX.2  Plan visibility     ← operator sees steps before/while Program runs
   ↓
IL.10 Multi-portfolio     ← concurrent books + persona (equity + F&O demo, …)
   ↓
OX.3  Durable goals       ← objectives first → Program / Portfolio links
   ↓
OX.4  Progress narrative
```

**Locked (IL-Q9):** this order. Explicit dependency chain: ranking → everyone follows ranking → show operator the plan → multiple portfolios → goals → progress.

---

### 14.1 IL.3 — Real ranking (`atlas/investment/ranking.py`)

**Problem today:** M0 takes `members[:max_watchlist]` — stable but not “best opportunities.”

**Target contract**

```
membership(index)
    → score each symbol
    → sort desc
    → top max_watchlist
    → publish ranked[{symbol, score, rank, reason, components, explanations, confidence, phase}]
```

**Every ranked row MUST answer “WHY THIS STOCK?”** (locked with IL.3 — not a later polish).

Example operator-facing shape:

```
Rank #1  RELIANCE.NS   score 0.84   confidence=learning|low|medium|high
Reason (structured):
  + Strong momentum
  + High liquidity
  + Positive earnings proxy (if available)
  − Oil sector uncertainty (if policy/context)
  − Slight mentor caution (if experience bias)
```

Not merely `score: 0.84`. Without explanations the operator cannot judge whether Atlas is thinking sensibly — this is the leap from simulator to learner.

**v1 score (deterministic, no LLM)** — weighted sum in `[0, 1]` after normalizing each component:

| Component | Source | Notes |
|-----------|--------|--------|
| **Momentum** | MarketReader last N bars (live or last published) | e.g. 5d / 20d return; missing bars → neutral |
| **Liquidity** | average volume vs universe median | Prefer tradable names |
| **Quality proxy** | optional ratios from Company Intelligence / config_seed | ROE, low debt if present; else omit from ± list |
| **Policy** | PolicyEngine prefer/avoid | Soft nudge (±) — never hard override alone |
| **Experience bias** | Mentor / Experience OS advice tags | Light caution after repeated losses on symbol/sector |

Each component contributes a **signed explanation line** (`+` / `−` / `·` neutral) into `explanations: list[{sign, text, component}]`. `reason` is a short human join of the top ± lines.

**Cold start (IL-Q10 locked):**

```
No / insufficient bars for most names
    → Neutral component scores + membership tie-break
    → phase = "learning"
    → confidence = "very_low"
    → explanations include: "· Learning — insufficient market history yet"
```

Atlas must **not** invent confidence. Operator should immediately see the learner is still building knowledge.

**Non-goals for IL.3:** ML models, screener scraping, options IV. Keep hermetic: fake bars → stable ranking + explanation strings in tests.

**Touch points**

| File | Change |
|------|--------|
| `atlas/investment/ranking.py` | `rank_universe(...) → list[Ranked]` with explanations + confidence + phase |
| `atlas/workers/investment_universe.py` | Call ranker when `mode=auto`; inject optional `market_reader` |
| Config | `rank_weights`, `lookback_bars`, `require_bars: false` |
| Tests | Hermetic: rising series ranks above flat; cold start labeled `learning`/`very_low` |

**Acceptance:** Journal / watchlist API shows WHY ± lines; M5 auto symbols change when momentum flips; cold start never claims high confidence.

---

### 14.2 IL.4 — Wire Observer / Company / News to watchlist

**Problem today:** M1/M2/M3 idle or only use **config** `symbols` / `tickers` / headlines you typed.

**Contract (same for all three)**

```
if config.symbols / tickers / instruments non-empty → pin (operator wins)
else → atlas.investment.watchlists.instruments_for(program_id)
         or symbols from ranked snapshot
```

| Mission | Field to fill | Behavior |
|---------|---------------|----------|
| **M1 Market Observer** | `symbols` / `instruments` | Observe ranked watchlist; interesting events still score |
| **M2 Company Intelligence** | `tickers` | Refresh profiles/facts for watchlist (+ open positions later) |
| **M3 News Intelligence** | seed queries / symbol tags | Prefer symbol-scoped headline search when search tool available; else keep config `headlines` |

**Event Research (M4):** already reacts to interesting moves — once M1 watches the ranked list, M4 naturally follows. Optional: also accept `InvestmentUniverseUpdated` to refresh internal caches.

**Touch points:** `market_observer.py`, `company_intelligence.py`, `news_intelligence.py` — small preamble like M5’s auto-load; shared helper `atlas/investment/watchlists.resolve_symbols(cfg)`.

**Acceptance:** India learner preset with empty M1/M2 configs still journals observations / company ticks for top ranked names.

---

### 14.3 IL.10 — Multiple independent virtual portfolios (+ persona)

**Problem today:** `sim.portfolios` is effectively **one book per mission** (`name="default"`). Concurrent “₹10k equity” + “₹50k F&O demo” needs isolation of capital, ledger, experience, and stats.

**Locked (IL-Q11):** **One Decision Simulation mission per portfolio** — cleaner than one mission managing ten books.

```
Market Program
├── ₹10k Equity      (mission + ledger + experience + mentor scope)
├── ₹25k Swing
├── ₹50k F&O Demo
├── Dividend Portfolio
└── Experiment #7
```

Each portfolio owns: ledger, cash, positions, experience, mentor scope, performance.

**Persona (required on every portfolio — IL.10 addendum)**

| Field | Example (Long-term) | Example (F&O Demo) |
|-------|---------------------|--------------------|
| **objective** | Wealth | Learning |
| **risk** | low | very_high |
| **time_horizon** | 5y | intraday |
| **capital** | ₹10,000 | ₹50,000 |
| **allowed_assets** | cash_equity | futures |
| **strategy** | ref / params | ref / params |

Persona influences Decision Simulation, Policy evaluation, ranking filters (allowed assets), and Mentor advice scope. Without it, multi-book is only separate cash piles.

**v1 approach (minimal schema pain)**

1. `atlas/investment/portfolios.py` registry (+ optional `sim.virtual_portfolios` migration).  
2. One Decision Simulation mission per book; `ensure_portfolio(mission_id, name=portfolio_key)`.  
3. Experience / Mentor tagged `portfolio:<key>`; `advice_for` filters by tag.  
4. OX.1 / Program start: `preset` + `portfolio_key` + persona fields.

**API (sketch)**

```
GET  /v1/market/portfolios
POST /v1/market/portfolios  {label, capital, universe, broker_profile, asset_class, persona{…}}
GET  /v1/market/portfolios/{id}/snapshot
```

**Acceptance:** Two portfolios, two capitals, two ledgers, two personas; a loss on A does not change B’s cash; mentor advice for A does not soft-bias B unless tags overlap intentionally.

---

### 14.4 OX.2 — Plan visibility (three interaction modes)

**Problem:** OX.1 starts the Program immediately; operator doesn’t always want that.

**Locked (IL-Q12) — three modes:**

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Beginner** | `start India learner` | **Preview plan → Confirm → activate** |
| **Power user** | `start India learner now` / `… and start` | **No preview** — activate immediately |
| **Scheduler / API** | `POST /v1/programs/.../start`, cron | **Always immediate** |

**Design**

1. `PlanningService.plan_program_start(preset, capital, …)` → executable steps (M0→M7).  
2. Chat: default preview; power-user phrases / `confirm=true` skip preview.  
3. UI: optional “Proposed plan” when using presets; classic Start remains one-click (power/API class).

**Acceptance:** Beginner path shows WHY/steps before missions appear; `… now` and API start without preview.

---

### 14.5 OX.3 — Durable goals (objectives first)

**Problem:** Jobs are finite; the learner is forever.

**Locked (IL-Q13 modified):** A Goal is an **Objective** first. Program and Portfolio are **how** the objective is pursued — not the center of the Goal.

```
Goal: "Become a profitable investor"
        ↓ links
    Program: Market Intelligence
        ↓
    Portfolio: ₹10k Learner

Goal: "Beat NIFTY over 12 months"
        ↓
    Portfolio: Long Term

Goal: "Learn Options"
        ↓
    Portfolio: F&O Demo
```

```
Goal {
  id,
  title / objective (human + structured intent),
  status: active|paused|completed|archived,
  success_criteria?,           # e.g. beat nifty 12m
  program_id?,                 # optional link
  portfolio_id?,               # optional link — one way to achieve the goal
  progress: {…},               # filled by OX.4
  created_at, updated_at
}
```

- Store: platform `goals` table (small migration) — **not** Market-only.  
- Created when operator states an objective (Chat/OX.2) or when starting a learner with an explicit goal phrase.  
- A portfolio can serve a goal; a goal can outlive a portfolio or rebind.

**Acceptance:** Reboot preserves goals; Chat “how is my beat-NIFTY goal?” resolves by objective, not only by portfolio name.

---

### 14.6 OX.4 — Progress narrative

**Problem:** Journals are raw; operator wants a collaborator summary.

**Design**

- Daily/weekly **narrative** from: goal progress, portfolio snapshot (if linked), last decisions/outcomes, M0 rank changes + WHY highlights, mentor lesson.  
- Surface: Program cockpit + `GET /v1/goals/{id}/progress` + Chat `learner_status`.  
- Deterministic template first; LLM polish optional later.  
- When portfolio `phase=learning` / cold start, narrative must say so explicitly.

**Acceptance:** One paragraph + bullets without reading every journal line; cold-start honesty preserved.

---

### 14.7 Decisions locked (IL-Q9…Q13) — operator 2026-07-25

| # | Decision |
|---|----------|
| **IL-Q9** | ✅ **IL.3 → IL.4 → OX.2 → IL.10 → OX.3 → OX.4** |
| **IL-Q10** | ✅ Cold start = **neutral ranking + membership tie-break**, labeled **`phase=learning`**, **`confidence=very_low`** — never invent confidence |
| **IL-Q11** | ✅ **One Decision Simulation mission per portfolio** |
| **IL-Q12** | ✅ **Three modes:** Beginner preview→confirm · Power user “start now” · API/scheduler immediate |
| **IL-Q13** | ✅ **Goals = objectives first**; Program/Portfolio are optional links, not the Goal’s identity |
| **IL.3 addendum** | ✅ Ranking contract always includes **WHY THIS STOCK?** (± explanation lines) |
| **IL.10 addendum** | ✅ Each portfolio has a **persona** (objective, risk, horizon, capital, allowed assets, strategy) |

**§14–20 ship complete** — full IL.1–11 + OX spine. F&O packs, Atlas holidays, and **filing refs (IL.5+)** shipped. Optional: live ToS-compliant exchange filing clients.

---

## 15. IL.11 — Simulation Engine instrument packs

**Status:** ✅ implemented (cash equity + ETF + futures + options ready; commodity/FX/crypto stubs).  
**Depends on:** IL.10 (multi-portfolio + persona).  
**Goal:** Keep one shared Simulation Engine; attach **rules packs** per asset class so F&O/commodities/ETF demos do not fork Decision Simulation.

### Shared vs pack-local

| Shared (engine) | Pack-local (per asset class) |
|-----------------|------------------------------|
| Tick loop, journal, P10 “no real orders” | Session / lot size / tick size / expiry |
| Decision Engine hooks + Mission Context cites | Margin / position limits / allowed order types |
| Experience write-back (portfolio-scoped tags) | Fee & tax via Broker Profile overlays |
| Portfolio registry + persona binding | Risk Policy overlays (`forbid` / `limit`) |
| Live / replay MarketReader adapters | Symbol universe & data adapters for that class |

### Pack roadmap (operator-selected sim, not autonomous ranking)

| Pack ID | Class | Phase-1 scope | Autonomous ranking? |
|---------|-------|---------------|---------------------|
| `cash_equity` | NSE/BSE cash | ✅ Ready (India learner) | ✅ M0 (IL.1–IL.4) |
| `etf` | Equity ETFs | ✅ Thin overlay on cash equity | Later |
| `futures` | Index/stock F&O futures | ✅ Lot / margin / expiry / F&O fees (sim) | ❌ IL-Q7 |
| `options` | Equity/index options | ✅ Lot / premium / write-margin / fees (sim) | ❌ |
| `commodity` | MCX-style | Stub → capability_gap | ❌ |
| `currency` / `fx` | FX pairs | Stub → capability_gap | ❌ |
| `crypto` | Crypto | Stub → capability_gap | ❌ |

### Operator contract

1. Create a **portfolio book** with `asset_class` + persona `allowed_assets` (IL.10).  
2. Attach **one Decision Simulation** mission to that book.  
3. Engine loads `instrument_pack` (config → book → asset_class → first allowed asset → `cash_equity`).  
4. Unready packs journal `capability_gap: instrument_pack:<id>` — **never** silent fake fills.  
5. Replay fixtures remain valid for CI; live is operator-primary where adapters exist.  
6. Catalogue: `GET /v1/market/instrument-packs`.  
7. F&O books: set `lot_size` / `expiry` on instruments (or accept NIFTY=25 heuristic); margin gates block opens when cash is thin.

### Code shape

```
atlas/investment/packs/
  __init__.py          # resolve_pack / list_packs
  base.py              # InstrumentPack protocol + OrderValidation
  cash_equity.py       # CashEquityPack + EtfPack (ready)
  derivatives.py       # FuturesPack + OptionsPack (ready, sim rules)
  stubs.py             # Commodity / FX / crypto not ready
```

`PaperTradingWorker`: resolve pack → session via pack → `validate_order` before fill → `fee_overlay`.  
`PaperTradingConfig` accepts `portfolio_key` / `persona` / `instrument_pack` / `asset_class` (IL.10/11).  
Session id `nse_fno` aliases NSE cash hours; Atlas holiday calendar applies (IL.5+).

### Acceptance

- [x] Cash-equity path behaviour unchanged for India learner  
- [x] Second book with `asset_class=futures` loads **ready** futures pack (lot/margin gates; no silent fills)  
- [x] Commodity/FX/crypto still explicit capability_gap  
- [x] No cross-book cash / experience bleed (IL.10 unchanged)  
- [x] Hermetic tests: `tests/test_investment_packs_il11.py`, `tests/test_investment_derivatives_packs.py`  
- [x] Operator guide lists F&O as “sim-on-request,” not default learner  

**Non-goals still:** autonomous F&O ranking / portfolio construction (IL-Q7); live NSE contract master.

---

## 16. IL.5 — India data depth (v0 + holidays + filings refs)

**Status:** ✅ v0 shipped (2026-07-25); ✅ holiday detection (2026-07-26); ✅ filings refs (2026-07-26).  
**Non-goals for v0:** live NSE/BSE filing clients, scrapes, inventing financial line items from PDFs.

### Delivered

| Piece | Detail |
|-------|--------|
| Hermetic quality pack | `atlas/investment/quality_seed.py` — NIFTY50 sector proxies (ROE / D/E), `source=hermetic_seed` |
| M0 ranking | Default `use_quality_seed=True`; operator overrides merge on top; `False` disables |
| M2 company auto-seed | Watchlist profiles include seed `ratios` + hermetic **filing refs** + honest fact lines |
| India learner preset | M0/M1 `provider: yahoo`; Decision Simulation already live Yahoo |
| Yahoo `.NS` contract | Chart URL passes `RELIANCE.NS` unchanged (hermetic opener test) |
| **Holiday detection** | `atlas/trading/holidays.py` — Atlas detects NSE/BSE/US closed days; wired into `session_status` |
| **Filings refs** | `atlas/investment/filings.py` — hermetic annual/quarterly refs + operator snapshot; `filings_seed` provider |

### Holiday detection (Atlas-owned)

- Built-in calendars (`india_equity` for `nse_equity` / `nse_fno` / `bse_equity`; `us_equity`) seeded from exchange circulars for 2024–2026.
- `session_status` returns `reason=holiday:<name>` and `holiday` field — no operator config required.
- API: `GET /v1/market/holidays`, `GET /v1/market/session-status`, `POST /v1/market/holidays` (operator overlay).
- Muhurat / special sessions treated as **full-day closed** for regular cash gates (conservative sim).
- Not a live scrape — refresh seeds when exchanges publish next year’s list.

### Filings refs (IL.5+)

- Hermetic NIFTY50 filing **metadata** (annual + quarterly titles / as_of) — study placeholders, not PDF pulls.
- Operator wins: `POST /v1/market/filings-snapshot` with ToS-compliant refs (title, kind, as_of, optional url).
- M2 auto-seed attaches refs + “Filing ref: …” fact; provider `filings_seed` builds profiles without hand-written `companies[]`.
- Official `nse` / `bse` / `sec` adapters still `capability_gap` until a real ToS client ships (honest; no silent fabrications).

### Still later (IL.5+)

- Official NSE/BSE / SEC live filing clients (ToS-compliant)  
- Live fundamentals from a ToS-compliant vendor (optional)  
- Auto-refresh holiday seeds from a ToS-compliant feed  
- PDF/XBRL extraction into verified Knowledge claims

### Operator notes

- Seed ratios are **sector proxies for simulation ranking**, not advice.  
- Override: M0 config `quality_seed: { "INFY.NS": { "roe": 0.25, "debt_to_equity": 0.1 } }`.  
- Disable: `use_quality_seed: false`.  
- Yahoo still requires `market.yahoo_enabled: true` in config.  
- Extra closed day: `POST /v1/market/holidays` `{ "calendar": "india_equity", "day": "2026-07-22", "name": "…" }`.  
- Filing refs: `GET /v1/market/filings?symbol=RELIANCE.NS` · `POST /v1/market/filings-snapshot`.

---

## 17. IL.6 — Daily Investment Plan (v0)

**Status:** ✅ v0 shipped (2026-07-25).  
**Non-goals for v0:** LLM narrative, real order routing, replacing PA.1 `plan()`.

### Delivered

| Piece | Detail |
|-------|--------|
| Builder | `atlas/investment/daily_plan.py` — candidates + suggested notionals + avoids + cold-start notes |
| Planning OS | `PlanningService.plan_daily_investment` |
| API | `GET /v1/planning/daily-investment-plan` · alias `GET /v1/market/daily-plan` |
| M0 publish | Watchlist `extra.daily_plan` on every universe tick |
| Morning cron | M0 second worker: `15 3 * * 1-5` (08:45 IST Mon–Fri, UTC) |
| OX.4 | Progress / learner status includes “Today's plan …” bullet |

### Operator notes

- Sizes are **simulation heuristics** (default deploy 40% of capital across top 5) — not advice.  
- Query: `GET /v1/market/daily-plan?portfolio_key=india_equity_learner&capital=10000`.  
- Cold start keeps honesty: provisional sizes when `phase=learning`.

---

## 18. IL.7 — Ledger realism (v0)

**Status:** ✅ v0 shipped (2026-07-26).  
**Non-goals for v0:** full tax year / ITR, SEBI line-item fidelity, T+ settlement calendar.

### Delivered

| Piece | Detail |
|-------|--------|
| Fee breakdown | `FeeBreakdown.tds` + persist `sim.trades.fees` JSONB (migration `0044`) |
| Withdraw / deposit | `PortfolioLedgerService.withdraw` / `deposit` + `sim.cash_movements` |
| Statement | `fee_components`, `withdrawn`, `withdrawal_tds` |
| API | `GET …/ledger`, `POST …/withdraw` |
| India default | Learner preset `broker_profile: zerodha` (CI keeps `paper_demo`) |
| Paper fills | `PaperTradingFill` includes `fee` / `fees` / `broker_profile` |

### Operator notes

- Profiles: `GET /v1/market/broker-profiles` — set `tds_pct_sell` / `withdrawal_tds_pct` via custom profile when teaching tax.
- Withdraw: `POST /v1/market/portfolios/{key}/withdraw` with `{"amount": 1000, "tds_pct": 0.1}`.
- Apply migration `0044_sim_ledger_realism.sql` for durable fee JSON + cash movements.

---

## 19. IL.8 — Screener-class signals (v0)

**Status:** ✅ v0 shipped (2026-07-26).  
**Non-goals for v0:** Screener.in / Chartink scrapes, continuous in-tick Jobs, live vendor fundamentals APIs.

### Delivered

| Piece | Detail |
|-------|--------|
| Module | `atlas/investment/screener_signals.py` — operator snapshot store + bars-derived rel_volume / mom |
| Ranking | PE / promoter / screener_score enrich `_quality_score` + WHY text |
| M0 | `use_screener_signals` (default true); `extra.screener` meta |
| M2 | Auto company seeds include screener facts when snapshot present |
| API | `POST /v1/market/screener-snapshot`, `GET /v1/market/screener-signals`, `POST …/compute` |

### Operator notes

```http
POST /v1/market/screener-snapshot
{ "symbols": { "INFY.NS": { "pe": 22, "roe": 0.28, "promoter_holding": 0.74, "score": 0.9 } } }
GET  /v1/market/screener-signals
```

Disable: M0 config `use_screener_signals: false`.

---

## 20. IL.9 — Operator happy path (v0)

**Status:** ✅ v0 shipped (2026-07-26).

### Delivered

| Piece | Detail |
|-------|--------|
| Preset | `india_equity_learner` — empty instruments, live Yahoo, Zerodha fees, M0→M7 |
| Guide | `GET /v1/learner/happy-path` — start / monitor surfaces + checklist |
| Status | `GET /v1/learner/status` includes `happy_path` runtime checks + next actions |
| Chat | `start India learner` → preview/confirm/now (OX.2); `learner status` (OX.4) |

### Operator one-liner

Atlas chooses; you constrain. No hand-built `instruments` JSON required.

---

*End of locked plan + remaining-work design (Q9–Q13 locked 2026-07-25; IL.1–11 + OX 2026-07-26).*
