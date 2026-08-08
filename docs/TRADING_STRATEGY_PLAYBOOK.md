# Atlas Trading Strategy Playbook

> **Status:** living operator record · **Book:** `india_equity_learner` · **Mode:** P10 simulation only  
> **Last updated:** 2026-08-05  
> **Parents:** [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) ·
> [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) ·
> [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md)  
> **Architecture leap:** [`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md) — 🔒 **PLAN LOCKED · DI.1→DI.7 SHIPPED** (`OI-DI0` 🟢). ML export gated ≥300 trusted; **no live NN**.

This file is the operator memory of **how and why** Atlas paper-trades **today**, plus the
**strategy improvement ledger**. Change strategy knobs here first (intent), then change code /
mission config to match. Architecture that makes Atlas truly learn (Decision Intelligence) lives
in the DI plan — do not conflate the two.

Daily KPI snapshots live under
`/data/atlas_data/market/trading_kpis/india_equity_learner/<YYYY-MM-DD>.json`.

---

## 1. Where to see the portfolio

| Surface | What you get |
|---------|----------------|
| **UI → Market** | Top summary (cash / equity / today P&L), daily plan, watchlist, **Sim book & missions** panel with positions, deposit/withdraw, recent fills + why |
| **UI → Market → Investor email report** | Preview / force-send morning & evening digests (includes KPIs) |
| **API** | `GET /v1/market/portfolios/india_equity_learner/ledger` |
| **Postgres** | `sim.portfolios` / `sim.positions` / `sim.trades` / `sim.cash_movements` (authoritative cash) |
| **Disk registry** | `/data/atlas_data/market/virtual_portfolios.json` (persona label + key; cash must match ledger) |

There is no separate “default ₹1,00,000” live book — that was a stale archived template and is hidden.

---

## 2. How Atlas decides to trade (pipeline)

```
Investment Universe (rank NIFTY50 / watchlist)
        ↓
Daily plan (deploy ~40% of book across top ~5 candidates)
        ↓
Paper trading tick (live Yahoo .NS bars, NSE cash hours 09:15–15:30 IST)
        ↓
Strategy signal (SMA fast > slow, RSI not overbought) → proposed qty
        ↓
Research gate (MVR + thesis when required)
        ↓
Portfolio gate (cash buffer · max names · name/sector caps) — may TRIM size
        ↓
Instrument pack + fee profile → sim fill on ledger
        ↓
Journal + research outcome + session notes + KPI snapshot
        ↓
Morning / evening investor email
```

### Why a buy happens

1. **Universe rank** put the name on today’s plan or next-alternative list.
2. **Technical signal** — fast SMA above slow SMA, RSI below overbought.
3. **Research gate** — for the learner: MVR + thesis must pass (soft MoS).
4. **Portfolio gate** — cash buffer, name/sector concentration, max names.
5. **Sizing** — target ≈ persona per-name budget (**~18%** for medium risk), ceiling **`max_exposure_pct` 40%**. Whole shares only; min lot = 1 share when cash allows.

### Why a sell happens

1. **Technical exit (v1):** while holding, fast SMA falls **below** slow SMA and RSI is not
   oversold (default RSI &gt; 30). Default exits the **full** position (`sell_fraction=1`).
2. **Not yet automatic:** calendar time-stops, hard MoS stops, or “falsifier → market sell”.
   Thesis falsifiers are reviewed on **Decision Evolution revisits** and exit attribution.
3. **Learning implication:** until sells happen, Atlas can record decisions and fills but cannot
   prove strategy edge (win rate / expectancy stay gated).

### Why a buy does *not* happen

Session notes + evening mail list the top reasons, typically:

| Reason | Meaning |
|--------|---------|
| `session_closed` | Outside NSE cash hours |
| `research_hold` | MVR / thesis / MoS gate failed |
| `portfolio_hold` / concentration | Name or sector cap / cash buffer |
| `investment_confidence_floor` | Score below configured floor (empty score no longer invents `very_low`) |
| `size_block` / cannot size | Share price > spendable cash |
| `policy_block` | Operator / mentor avoid |

After a gate size breach, Atlas **trims** to the largest whole-share qty that fits instead of vetoing (unless the failure is a hard research/policy veto).

---

## 3. Current knobs (learner preset)

From `india_equity_learner_overrides()` / paper mission config:

| Knob | Value | Role |
|------|-------|------|
| `starting_cash` / deposits | ₹50k bootstrap; deposit anytime | Book capital |
| `trade_fraction` | `1.0` | Use available cash up to target |
| `name_target_pct` | persona `max_name_pct` (~0.18) | Per-trade *target* |
| `max_exposure_pct` | `40` | Hard single-name *ceiling* |
| `sector_cap_pct` | ≥ name cap (auto) | Sector concentration |
| `min_cash_pct` | persona (15% medium) | Cash buffer |
| `prefer_next_alternatives` | true | Try next ranked names when top are blocked |
| `require_mvr` / `require_thesis` | true | Research honesty |
| `broker_profile` | `zerodha` | Fee overlay on sim fills |

Improve strategy by changing these deliberately and watching the KPI history — do not silent-edit mid-session without a note below.

---

## 4. Decision-input data dictionary

This is the canonical list of the data points Atlas can currently observe, import, derive, or
use in an investment decision. **A field existing in code does not mean Atlas has a current value
for every company.** The status column is important:

- **Auto/live** — normally populated from the market feed or ledger.
- **Derived** — calculated only when its source fields exist.
- **Imported** — operator / Screener CSV or JSON; Atlas does not scrape it.
- **Research lens** — Atlas asks for and stores evidence, but may have an explicit gap instead of a number.

### 4.1 Market, price and technical data

| Human name | Exact field(s) | Status / decision use |
|------------|----------------|-----------------------|
| OHLC price | `open`, `high`, `low`, `close` / `price` | Auto/live Yahoo bars; marking and signals |
| Volume | `volume` | Auto/live; average-volume liquidity rank |
| Bar time / history depth | timestamp, `bars` | Auto/live; freshness and cold-start coverage |
| Short / long return | derived 5/20-bar period return | Derived; `momentum` rank component |
| Average volume | derived 20-bar mean | Derived; `liquidity` rank component |
| Fast / slow SMA | `sma_fast`, `sma_slow` (default 10/30) | Derived; current buy/sell crossover signal |
| RSI | `rsi` (default 14) | Derived; overbought/oversold timing gate |
| EMA | internal `ema` | Derived helper |
| MACD | `macd.macd`, `macd.signal`, `macd.histogram` | Derived and recorded; not the primary current buy trigger |
| Market/session state | NSE session, holiday, market open/closed | Auto; prevents fills outside cash hours |
| Feed health | feed mode/provider, last bar, gap days, empty/error counts | Auto; report honesty, not company quality |

### 4.2 Company fundamentals and valuation inputs

Canonical import schema (`atlas/investment/fundamentals.py`):

| Human name | Exact field | How Atlas uses it |
|------------|-------------|-------------------|
| Return on equity | `roe` | Quality / financial-health score; fair-PE heuristic |
| Return on capital employed | `roce` | Profitability and financial-health evidence |
| Return on invested capital | `roic` | Quality, capital allocation, valuation debate |
| Debt to equity | `debt_to_equity` | Financial-health and risk score |
| Price / earnings | `pe` | Quality proxy and PE-vs-fair margin of safety |
| Price / book | `pb` | Valuation evidence (especially banks) |
| Free cash flow | `fcf` | Cash-flow evidence and DCF stub |
| Operating margin | `operating_margin` | Profitability / quality |
| Net margin | `net_margin` | Profitability / quality |
| YoY revenue growth | `revenue_growth_yoy` | Growth and thesis |
| QoQ revenue growth | `revenue_growth_qoq` | Growth |
| Revenue CAGR | `revenue_cagr` | Growth / DCF assumption support |
| Earnings CAGR | `earnings_cagr` | Growth |
| Promoter holding | `promoter_holding` | Management / governance |
| Promoter pledge | `pledge_pct` | Governance and risk |
| Current price | `price` | Price-vs-intrinsic-value MoS |
| Shares outstanding | `shares` | Per-share intrinsic value |
| Market capitalization | `market_cap` | Company context |
| Sector | `sector` | Sector pack, peer lens and concentration |

Additional valuation inputs / assumptions:

`capex`, `fcf_growth`, `discount_rate`, `dividend_yield`, `fair_pe`,
`intrinsic_value`, `margin_of_safety_pct`, `terminal_growth`, DCF `years`,
DCF bear/base/bull enterprise-value scenarios, and `min_mos_buy_pct` (15%).

**Industry average / peer comparison honesty:** Atlas stores optional operator-imported
`industry_pe_median` / `industry_pb_median` / `industry_roe_median` on the fundamentals row.
It computes a conservative `fair_pe` from ROE + broad sector as a **quality heuristic only**.
Atlas must **not** claim “PE below industry average” unless `industry_pe_median` was imported
(`may_claim_below_industry_pe` / `pe_vs_industry_median_pct` on valuation). Gap-fill:
`GET /v1/market/fundamentals/learner-template` — see [`SCREENER_FUNDAMENTALS_IMPORT.md`](SCREENER_FUNDAMENTALS_IMPORT.md).

### 4.3 Research coverage and evidence

Every researched company has these ten dossier sections:

`business`, `profitability`, `financial_health`, `cash_flow`, `valuation`, `growth`,
`earnings_quality`, `management`, `moat`, `risks`.

Minimum Viable Research (MVR) requires business, management, financial health, cash flow,
valuation, and risks to be addressed. Atlas tracks:

| Data point | Exact field(s) |
|------------|----------------|
| Section state / freshness | `status`, `as_of`, TTL, `stale_sections` |
| Section certainty | per-section `confidence` |
| Evidence and provenance | `fields.evidence`, `sources`, `filings_refs` |
| Missing data | `gaps`, `missing_inputs`, `known_unknowns`, `blocked_on` |
| Coverage | `coverage`, `coverage_by_section`, `coverage_by_evidence`, `coverage_by_reasoning` |
| Research depth | `research_quality` (`basic` / `developing` / `substantive` / `deep`) |
| MVR gate | `mvr_satisfied`, required/present/missing sections |
| Thesis | summary, bull/base/bear, stance, drivers, assumptions, catalysts, falsifiers |
| Business identity | company name, sector, industry, products/services, customer/geography context |
| Critical flags | active thesis-invalidating / warning flags |
| Distinctiveness | reason to exist, position, value drivers, falsifiers, gaps |
| Timing | horizon, RSI timing bias, stale/data-quality status |

### 4.4 Sector / industry operating KPIs Atlas asks to verify

These are **research lenses**, not guaranteed live numeric feeds:

| Sector pack | KPI names |
|-------------|-----------|
| Defence / aerospace | order book / book-to-bill; customer concentration; receivables days; working capital / cash conversion; execution and certification milestones; defence/aerospace revenue mix |
| Hospitals | occupancy; ARPOB; doctor retention/utilization; bed expansion and new-capacity ROIC; payer/insurance mix; same-store growth vs new-bed ramp |
| Manufacturing / capital goods / EMS | customer concentration; gross-margin durability; working-capital cycle; capacity utilization; capex vs FCF |
| IT / software services | deal TCV/pipeline; utilization; attrition; vertical mix; margin bridge |
| Banks / NBFCs | NIM; credit cost/slippages; CASA/deposit mix; capital adequacy; loan-growth mix |

Valuation lenses include PE, P/B, EV/EBITDA, FCF yield, growth-adjusted multiples, ROIC vs WACC,
and normalized credit cost. Atlas records the missing evidence when these values are unavailable.

### 4.5 Ranking, policy, portfolio and execution inputs

| Group | Exact data points |
|-------|-------------------|
| Universe rank | `momentum`, `liquidity`, `quality`, `policy`, `experience`, `research`, total `score`, `rank`, `phase`, `confidence` |
| Investment score axes | `business`, `growth`, `financial_health`, `management`, `valuation`, `technical`, `macro_theme`, `risk` |
| Dual confidence | `research_confidence`, `investment_confidence`, `score_band`, `path`, `path_reason` |
| Government / macro | policy category, affected sectors, directional delta, provenance/freshness |
| News / events | symbol/company/sector relevance, recency, source; evidence only unless translated to a cited policy/research nudge |
| Portfolio | cash, equity, holdings value, position qty, average price, market mark, realized/unrealized P&L |
| Risk limits | `max_name_pct`, `sector_cap_pct`, `min_cash_pct`, `max_names`, allowed assets, persona risk/horizon |
| Sizing | MoS, horizon multiplier, investment-confidence multiplier, spendable cash, whole-share qty, binding cap |
| Execution | side, quantity, fill price, notional, broker profile, fees/taxes, decision ID, research/portfolio gate results |

### 4.6 What counts as learning (and what does not)

| Recorded object | Meaning |
|-----------------|---------|
| Research dossier / memory | Atlas studied or recorded evidence. This is **knowledge gained**, not proof the stock will perform. |
| `observed` outcome | Entry or timed thesis checkpoint. It is an observation, not a win. |
| `held` outcome | Realized profitable exit tentatively supported the thesis. |
| `weakened` outcome | Realized loss requires falsifier/assumption review. |
| `falsified` outcome | Evidence invalidated a thesis. |
| Experience / mentor journal | Outcome written back so future ranking/sizing can cite the prior lesson. |
| Thesis priors | Repeated outcomes can eventually adjust ranking/scoring weights; changes remain gated by sample sufficiency. |

Do not read “13 companies researched” as “13 successful learnings.” Proven strategy learning
requires completed outcomes—especially exits—and enough samples to compare decisions against a
baseline.

---

## 5. How to inspect how much Atlas learned

### UI (easiest)

Go to **Market → Investing research (IRA)**. The top block now shows:

- number of company dossiers;
- total research memories;
- total thesis/trade outcomes;
- recent lesson texts.

Each company’s **Open** button shows its coverage, evidence vs reasoning, confidence, MVR state,
thesis, valuation/MoS, investment-score axes, known unknowns, outcome count and thesis tracker.
Use **Preview weekly** in Investor email report for a cross-company belief-change summary.

### API

```http
GET /v1/market/research
GET /v1/market/research/EICHERMOT.NS?full=true
GET /v1/market/research/compare?a=EICHERMOT.NS&b=INFY.NS&portfolio_ref=india_equity_learner
GET /v1/market/fundamentals
GET /v1/market/portfolios/india_equity_learner/ledger
GET /v1/market/investor-report/preview?kind=weekly
```

The research-list response contains `count`, each item’s `memories_count` /
`outcomes_count`, and `digest.studied`, `digest.lessons`, `digest.open_gaps`.

### Durable data

| Data | Location |
|------|----------|
| Company dossiers, memories, outcomes | `/data/atlas_data/investment/research/market_intelligence/<SYMBOL>.json` |
| Thesis trackers and program priors | `/data/atlas_data/investment/` thesis-tracker files |
| Imported fundamentals | `/data/atlas_data/investment/fundamentals/market_intelligence.json` |
| Daily hold/no-fill reasons | `/data/atlas_data/market/session_notes/india_equity_learner/<DATE>.json` |
| Daily trading scorecard | `/data/atlas_data/market/trading_kpis/india_equity_learner/<DATE>.json` |
| Trades / positions / cash | Postgres `sim.*` ledger tables |
| Reusable outcome lessons | Experience OS journals tagged `markets`, `ira`, `thesis_outcome`, symbol and portfolio |

### Current snapshot (2026-08-05)

- 13 stored research dossiers, all at `thesis_ready`;
- 193 research memories;
- 28 outcomes across 11 dossiers;
- all current outcomes are predominantly `observed` checkpoints; EICHERMOT includes today’s sim-buy observation;
- 1 open position and **no completed sell outcome yet**, so win rate / strategy hit rate is not proven;
- the canonical fundamentals store does not yet exist, so there is **no broad-universe imported
  fundamentals coverage**;
- dossier field coverage currently has ROE and debt/equity for 11 dossiers, but **0 dossiers with
  PE, P/B, FCF, ROIC, margins, growth rates, promoter data, shares, or market cap**;
- therefore today’s ranking/trade must not be described as PE- or industry-average-driven—the
  current fill was driven by market signal + research/gate context, not a verified PE comparison;
- one duplicate/malformed Apollo dossier key (`APOLLOHOSP.NS · APOLLO HOSPITALS`) exists and should be cleaned before treating dossier count as unique-company coverage.

This is the honest answer to “how much learned”: Atlas has accumulated research and observations,
but it does not yet have enough completed trade outcomes to claim that the strategy has improved
returns.

---

## 6. Operator KPI scorecard (must track)

### 6.1 Ship today (Stage 1 minimum)

Every evening snapshot and ledger response should populate these:

| KPI | Why it matters |
|-----|----------------|
| **cash / holdings_value / equity** | Current portfolio total |
| **day_pnl / day_return_pct** | Today’s market delta after investment |
| **total_pnl / total_return_pct** | P&L after deposits & withdrawals |
| **net_contributed_capital** | Money you put in (truth for return %) |
| **open_positions** | Concentration / diversification |
| **fills_today / buys_today / sells_today** | Did the sim act? |
| **candidates_planned / candidates_filled / plan_fill_rate** | Plan honesty — “top 5” vs actual fills |
| **top_no_fill_reasons** | Why only one stock (or none) bought |
| **size_trims / portfolio_gate_blocks** | Sizing vs gate health |
| **fees_paid** | Realism of broker costs |
| **phase / confidence** | Learning honesty (cold start ≠ confident) |
| **research_studied / lessons_count** | What Atlas studied / recorded that day |

**Storage:** `atlas/investment/trading_kpis.py` →
`/data/atlas_data/market/trading_kpis/<portfolio_key>/<date>.json`  
**Surfaces:** evening email “Trading KPIs” block · Market UI Sim book · ledger `statement.kpis`

### 6.2 Target shape — five dashboards (staged)

Full trader KPI framework is valuable, but **must not** land as one mega-wall. Target surfaces
(see DI plan §3):

| Dashboard | Focus | Stage 1 now? |
|-----------|-------|--------------|
| **Investment** | Business quality / MoS / fundamentals / field age | Partial (mostly gaps) |
| **Trading** | Win rate, expectancy, R-multiples | Not yet (need closed sells) |
| **Portfolio** | Exposure, drawdown, cash | Mostly yes |
| **Learning** | Decision packets, lessons, adherence | Weak (observations only) |
| **Research** | Completeness / freshness / ignorance | Partial (IRA coverage) |
| **Intelligence (D6)** | Is *Atlas* getting smarter? (packet quality, revisits, lesson reuse, calibration) | Not built — DI plan |

**Sample-size gates (locked):** hide edge metrics &lt;30 closed sells; provisional 30–99; usable 100–299; trusted ≥300. Never mix stats across `strategy_tag`s.

**Storage for Decision Intelligence (locked):** Hybrid — Postgres authoritative + JSON mirrors.

**Human psych KPIs → Atlas process proxies** (FOMO, revenge, hesitation, plan violation,
overconfidence, journal completion) — ✅ DI.5. Atlas has no emotions; countable flags live on
Decision Packets (`meta.process_flags`) and day scorecard
`GET /v1/market/process-proxies`. See DI plan §DI.5.

**Attribution rule (locked):** never teach strategy from raw P&L alone when market regime quality was catastrophic and decision quality was sound.

### 6.3 Strategy improvement loop (how this playbook stays honest)

1. Change intent in **§8 Strategy change log** (why + expected KPI effect).  
2. Change mission/config/code to match.  
3. Let ≥1 full market week accumulate KPIs / decisions.  
4. Weekly Learning review (DI plan Appendix B): stop / repeat / weakness.  
5. If the change failed its expected KPI effect, revert or amend — and log that too.

---

## 7. How to regenerate today’s emails

On **Market → Investor email report**:

1. **Preview morning / evening** — builds body without sending (good for checking P&L / KPIs).
2. **Send morning / Send evening** — force-resends (`?force=true`), even if already sent today.

API:

```http
POST /v1/market/investor-report/morning?force=true
POST /v1/market/investor-report/evening?force=true
GET  /v1/market/investor-report/preview?kind=evening
```

Already-sent dates are tracked in `/data/atlas_data/market/investor_reports_sent.json`; `force=true` bypasses the once-per-day guard.

Preview/Send now attach the **live** `india_equity_learner` ledger (cash, marks, day P&L, KPIs) — not an empty plan-only stub.

---

## 8. Strategy change log

| Date | Change | Why | Expected KPI effect | Result (fill later) |
|------|--------|-----|---------------------|---------------------|
| 2026-08-05 | Persist virtual book + rehydrate live ledger after restart | Deposits vanished; emails showed Cash: None | equity/cash match ledger | observed fixed |
| 2026-08-05 | Evening day_pnl + total_pnl on marks | Needed today’s delta in mail | day_pnl populated | observed fixed |
| 2026-08-05 | Per-name target ~18%; trim on sector/name caps | 40% first fill starved other candidates | higher plan_fill_rate | pending next sessions |
| 2026-08-05 | Empty investment score ≠ `very_low` floor fail | Blocked fills when research score missing | fewer false floor blocks | pending |
| 2026-08-05 | Durable KPI snapshots + playbook | Operator strategy memory | KPIs in mail + disk | shipped |
| 2026-08-05 | DI Learning Plan drafted (no code) | Execution engine ≠ investment learner | architecture path to real learning | plan draft |
| 2026-08-05 | DI plan LOCKED after review (OI-DI0) | Packets+Obs+Timeline+attribution+D6+Hybrid | proprietary decision history | plan locked — await DI.1 code |
| 2026-08-05 | DI plan finalized for implementation (§12) | DI.1 schema/API/acceptance locked; migration `0045` | build contract | **green light DI.1** — no further arch debate |
| 2026-08-05 | **DI.1 shipped** | Decision Packets hybrid store + API + evening + plan_watch | freeze decide-time belief | feature contributions heuristic v1 |
| 2026-08-05 | **DI.2 shipped** | Timeline + Day1→Quarter revisits + evolution worker | belief evolution without rewrite | what_changed diffs |
| 2026-08-05 | **DI.4 thin** | Fundamentals coverage + learner_gaps honesty | stop empty-PE theater | operator import still required |
| 2026-08-05 | **DI.Obs shipped** | Observation store + timeline fan-out + packet citation | evidence before research | market/news/policy sources |
| 2026-08-05 | **DI.Attr shipped** | DQ/MQ/EQ/PQ grades + Replay API + priors hard rule | decision≠market P&L | market F + decision A/B blocks weight update |
| 2026-08-05 | **DI.3 shipped** | Staged D1–D6 dashboards + 30/100/300 gates per strategy_tag | honest edge hide until sample | no migration; API + evening + learner UI |
| 2026-08-05 | **DI.4 deepen** | Learner gap template + industry_*_median import + MoS honesty | stop empty-PE / fake industry claims | operator Screener CSV still required |
| 2026-08-05 | **DI.5 shipped** | Process proxies FOMO/revenge/hesitation/plan/overconfidence/journal | no emotions — countable process | packet flags + day scorecard API |
| 2026-08-05 | **DI.6 shipped** | Meta-learning weekly + D6 intelligence_score + proposals | Atlas-the-product not vanity P&L | never silent strategy rewrite |
| 2026-08-05 | **DI.7 shipped (gated)** | ML JSONL export + offline rules baseline | train on decisions not OHLCV alone | no live NN; ≥300 trusted or override |

Add a row here whenever you change sizing, gates, research requirements, universe rules, or
decision/learning policy. Architecture phases belong in
[`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md).

---

## 9. Honest maturity & open improvements

**Today:** strong-ish data collection + paper ledger; basic research; very early outcome learning.
Atlas is **not** yet up to the systematic-trader / investment-intelligence bar — and the playbook
must keep saying so until Decision Packets, Timeline, closed-outcome stats, and fundamentals
coverage exist.

Tracked in DI plan (`OI-DI0` 🟢, **DI.1→DI.7 shipped**):

- **DI.1** Decision Packet ✅ (migration `0045`)
- **DI.2** Market Timeline + revisits ✅ (migration `0046`)
- **DI.Obs** Observation Layer ✅ (migration `0047`)
- **DI.Attr** Outcome attribution + Replay ✅ (migration `0048`; priors hard rule)
- **DI.3** Staged KPI dashboards + sample gates ✅
- **DI.4** Fundamentals / peers ✅ deepen
- **DI.5** Process proxies ✅
- **DI.6** Intelligence Dashboard + meta-learning weekly ✅
- **DI.7** ML-ready export ✅ gated (≥300 trusted / override; offline eval; **no live NN**)

Accumulate closed attributable exits; check `GET /v1/market/ml-export` until a strategy_tag is trusted.

Near-term playbook-level leftovers (until DI ships):

- Soften or stage research gates during `phase=learning` so cold-start books still practice fills.
- Track **max drawdown** and **hit rate on exited trades** once sells accumulate.
- Compare plan suggested_notional vs actual fill notional per symbol.
- Mentor advice → explicit KPI “advice followed / ignored”.
- Clean duplicate Apollo dossier key before trusting dossier counts.
