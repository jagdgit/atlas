# Investment Intelligence Platform (IIP) — Stage 4 Plan

> **Status:** 🔒 **LOCKED for implementation** (operator finalize 2026-07-27)  
> **Product name:** Investment Intelligence Platform (not “Trading”)  
> **Parents:** [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) (🔒) ·
> [`INVESTING_RESEARCH_AGENT_PLAN.md`](INVESTING_RESEARCH_AGENT_PLAN.md) ·
> [`IRA_NEXT_LEAP_EVIDENCE_PLAN.md`](IRA_NEXT_LEAP_EVIDENCE_PLAN.md) ·
> [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) ·
> [`HOST_UNATTENDED_AND_MARKET_RESILIENCE.md`](HOST_UNATTENDED_AND_MARKET_RESILIENCE.md) ·
> [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) (Evidence Graph / KG)  
> **Open item:** `OI-IIP0`  
> **Non-negotiables:** P10 simulation-only fills · MI4/MI5 honesty · no ToS scraping · coverage ≠ confidence ≠ research quality ≠ **investment confidence** · MVR ≠ buy · evidence before eloquence · IR-RO11 host-first · CapabilityGap when data missing · **no new top-level Intelligence / OS**

---

## 0. Locked verdict

Atlas already has a **strong operating spine** (sim ledger, outage recovery, research gate, investor email, IRA dossiers).  
What is weak is **evidence quality, discovery breadth, and relational market understanding** — not architecture.

**Do not** invent a new top-level Intelligence or replace Market Program.  
**Do** grow Market Program into an **Investment Intelligence Platform** that reuses the same Atlas platform as Engineering / Research Workers.

```text
95% of the product = themes · discovery · research · evidence · thesis quality
 5%                = the sim fill
```

Paper trading stays **near the end** of the pipeline — not the center of gravity.

**Year-ahead success depends more on discovery, fundamentals, filings, and document ingestion than on more decision logic.**

---

## 1. Locked operator decisions (2026-07-27)

| Decision | Lock |
|----------|------|
| Product framing | **Investment Intelligence Platform** inside Market Program |
| Platform reuse | Research Worker / Engineering / IIP share one Atlas OS — no fork |
| Pipeline order | Theme → Universe → Discover → Research → Evidence/MKG → Score → Portfolio → Simulate → Learn |
| First three builds | **IIP.1 Universe → IIP.2 Discovery (+ themes v1) → IIP.3 Fundamentals import** |
| Before advanced scoring | **Market Knowledge Graph + document research** (IIP.4–IIP.5) |
| Discovery | Screening **plus** hypothesis / theme expansion (not ROCE filters alone) |
| Confidences | Separate **Research Confidence** vs **Investment Confidence** |
| Time horizon | Every idea tagged: trading · swing · position · long_term · structural · speculative |
| Thesis | First-class **Thesis Tracker** (hypothesis → evidence → decision → outcome) |
| Screener / TradingView | Export/snapshot + chart links; **no HTML scrape dependency** |
| Geography | India cash equity until portfolio gates land; global = new universes later |

---

## 2. What is already good (keep)

| Capability | Status |
|------------|--------|
| Persistent paper portfolio (Postgres) | ✅ |
| Outage / internet / restart resilience | ✅ |
| systemd + watchdog host recovery | ✅ |
| Research gating before buys (IRA) | ✅ |
| Morning / evening / trade emails + zero-fill honesty | ✅ |
| IRA dossier spine (thesis, MVR, MoS, evidence ladder, sector packs) | ✅ |
| M0 Investment Universe + ranking + daily plan | ✅ (still **NIFTY50-centered**) |
| Multi-portfolio registry (`india_equity_learner`) | ✅ |
| Knowledge / Verification / Experience OS | ✅ (platform — reuse for MKG) |

---

## 3. Honest gap

Today’s learning diet:

```text
Yahoo prices + hermetic policy catalog + operator snapshots + thin IRA dossiers
```

Enough for infrastructure tests. Not enough for a good investor.

Missing center of gravity:

```text
Macro themes → Discover (why a company exists in a story)
  → Research → Market Knowledge Graph
  → Score → Portfolio → Simulate → Thesis Tracker / Learn
```

---

## 4. Four capabilities (locked shape)

| Capability | Owns | Atlas home (extend, don’t fork) |
|------------|------|----------------------------------|
| **1. Market Intelligence** | Prices, technicals, universes, themes, macro/policy | MarketReader · M0 · Theme Engine · Discovery · gov worker |
| **2. Company Intelligence** | Fundamentals, filings, transcripts, management | M2 · IRA · fundamentals import · Research Worker PDFs |
| **3. Research Intelligence** | Books, papers, methods, failure studies | Research/Knowledge pipeline + IRA memory |
| **4. Portfolio Intelligence** | Sizing, sim fills, Thesis Tracker, attribution | M5/M6 · ThesisOutcome · Experience · Mentor |

**Naming rule:** UI/docs say *Investment Intelligence Platform*. Code stays under Market Program + `atlas/investment/` + IRA + Knowledge graph extensions. **No new kernel Intelligence.**

---

## 5. Canonical pipeline (locked)

```text
Macro Theme Engine
        │
        ▼
Universe Manager          (index · theme · sector · operator · dynamic)
        │
        ▼
Discovery Engine          (screen + hypothesis expansion)
        │
        ▼
Research Worker / IRA     (same PDF → claims pipeline)
        │
        ▼
Market Knowledge Graph    (entities + relationships; supersedes “evidence-only”)
        │
        ▼
Investment Scoring        (multi-axis; horizon-weighted)
        │
        ▼
Portfolio Optimizer       (policy · persona · cash · concentration)
        │
        ▼
Paper Trading (sim)       (already strong)
        │
        ▼
Thesis Tracker + Learning (hypothesis · outcome · priors)
```

Professional shape (not “market data → buy signal → trade”):

```text
Discover → Research → Evidence/MKG → Score → Portfolio → Simulation → Learning
```

---

## 6. Macro Theme Engine (before Discovery)

**Problem with screening-only discovery:** volume, breakouts, ROCE, debt are useful **filters**. They do not explain *why a company exists in an investment story*.

**Theme Engine** continuously maintains themes and asks:

> Which companies **gain** if this theme strengthens?

### Seed themes (India-first v1)

AI · EV · Defence · Renewable Energy · Green Hydrogen · Railways · Data Centers · Water · Healthcare · Nuclear · Space · Battery / Storage · Power Transmission

### Theme → supply-chain expansion (hypothesis generation)

Example:

```text
Hypothesis: India's data-center demand will grow
        │
        ▼
Who benefits?
  Power → Cooling → Transmission → Cables → Transformers
  → REITs → Semiconductors → EPC
        │
        ▼
Candidate set for Discovery / Research queue
```

### Theme object (durable)

| Field | Meaning |
|-------|---------|
| `theme_id` | e.g. `data_centers` |
| `hypothesis` | One-sentence structural claim |
| `status` | watch · active · fading · falsified |
| `policy_links` | Gov/MKG policy nodes |
| `beneficiary_roles` | power, cooling, cables, … |
| `symbols` | Mapped companies (weak→strong links) |
| `horizon_default` | Usually `structural` or `long_term` |
| `evidence_refs` | MKG / dossier links |

**v1:** hermetic theme packs + operator CRUD + policy-event hooks.  
**v2:** auto-create theme watchlists from policy/news (e.g. Green Hydrogen Mission → 30 names).

Mission/worker home: extend M0 **or** thin `theme_intelligence` member — still Market Program.

---

## 7. Universe Manager

Maintain **many** membership sets:

| Family | Examples |
|--------|----------|
| **Index** | NIFTY50 ✅ → NEXT50, MIDCAP150, SMALLCAP250, BSE500 |
| **Theme** | Green Energy, AI, Defence, Data Centers, … |
| **Sector** | Banks, IT, Pharma, Capital Goods, … |
| **Operator** | Manual books / experiments |
| **Dynamic** | Auto from Theme Engine / policy events |

```text
Universe Manager
  → Maintain · Expand · Shrink · Rebalance
```

Active research/trade sets stay **capped** (host + attention). Membership ≠ permission to buy.

Storage: extend `atlas/investment/universe.py` + `data/investment/universes/`.

---

## 8. Discovery Engine (screen + hypothesis)

**Mission:** `opportunity_discovery` (or M0 `discover` mode)  
**Cadence:** post-close IST + optional weekend batch  
**Output:** `InterestingCandidate[]` with **why** — never a buy.

### Two discovery modes (both required)

| Mode | What | Example |
|------|------|---------|
| **A. Screening** | Quantitative / event filters | Volume spike, 52w high, ROCE>X (if snapshot), debt drop, policy sector delta |
| **B. Hypothesis** | Theme / supply-chain expansion | “Data-center demand ↑ → list transmission + cooling beneficiaries” |

Funnel (host-safe):

```text
~1000 names in enabled universes
   → ≤40 interesting (screen ∪ theme)
   → ≤10 research queue
   → ≤2–5 size-eligible after gates
```

### Time horizon (locked on every candidate / thesis)

| Horizon | Evidence weight tilt |
|---------|----------------------|
| `trading` | Technicals · news · volume (weak fundamentals) |
| `swing` | Technicals + near-term events |
| `position` | Mix fundamentals + technicals |
| `long_term` | Fundamentals · management · MoS |
| `structural` | Themes · policy · supply chain · MKG |
| `speculative` | Explicit high-uncertainty; never default size |

Horizon changes **evidence weights**, not honesty rules.

IR-RO11: discovery is **background**, memory-gated.

---

## 9. Research confidence vs investment confidence (locked)

Keep existing IRA separations: coverage · evidence sufficiency · research quality · MVR · MoS.

**Add:**

| Concept | Question |
|---------|----------|
| **Research Confidence** | How well do we understand this company / theme? |
| **Investment Confidence** | How attractive is owning it *now* (valuation, timing, risk, portfolio fit)? |

Example (allowed and expected):

```text
Research Confidence   95%
Investment Confidence 42%
→ Excellent research; terrible entry / valuation → watch, do not buy
```

Buy gates must see **both**. High research confidence alone never implies buy.

---

## 10. Market Knowledge Graph (locked priority)

**Do not stop at a flat Evidence Graph of claims.**  
Build a **Market Knowledge Graph (MKG)** — domain content on the existing Knowledge / graph machinery (reuse KV / derived graph; do not invent a second graph OS).

### Why before advanced scoring

Scoring quality depends on whether Atlas understands **relationships**, not only filters:

```text
MNRE → Solar PLI → Waaree → Revenue / Margins → Portfolio position
```

Answer: *“Why do I own Waaree?”* → policy + theme + financials — not “RSI crossed.”

### Node types (v1 subset → expand)

Companies · People · Products · Industries · Themes · Policies · Events · Countries · Commodities · Technologies · Patents

### Relationship types (v1 subset)

`supplies` · `competes` · `owns` · `imports` · `exports` · `benefits_from` · `depends_on` · `affected_by` · `produces` · `uses` · `regulates` · `customer_of`

### Honesty

Missing edges → CapabilityGap / “unknown relation,” never invented supply chains.  
Hermetic seed edges allowed if labeled `source=hermetic_seed`.

---

## 11. Thesis Tracker (locked)

Every investment path:

```text
Hypothesis → Evidence → Decision → Outcome → Lessons
```

### Stored with each position / watch

| Field | Example |
|-------|---------|
| Hypothesis | “Battery demand + grid investment supports Tata Power” |
| Theme links | `battery`, `power_transmission` |
| Assumptions | Policy support · capex delivery · valuation band |
| Horizon | `structural` |
| Research vs investment confidence | at decision time |
| Decision | buy / watch / avoid + size |
| Outcome (later) | Which assumptions held / failed |

Six months later Atlas revisits: *which assumptions were right?* → Experience OS + discovery/scoring priors.

Extends ThesisOutcome / IRA research memory — **one tracker**, not a parallel system.

---

## 12. Eight evidence domains → adapters

Every adapter emits typed evidence with `source`, `as_of`, confidence, **horizon relevance**, and **which dossier / MKG nodes it strengthens**.

| # | Domain | Near-term | Mid-term | Do **not** |
|---|--------|-----------|----------|------------|
| 1 | Market data | Yahoo ✅; AV/Polygon when keyed; Stooq history | Twelve/Finnhub/Tiingo; corporate actions | TradingView as price source |
| 2 | Fundamentals | Snapshot schema v2 + CSV/JSON import | Licensed API or Screener **export** | HTML scrape Screener/Trendlyne |
| 3 | Gov / regulatory | Catalog + operator; theme hooks | PIB/MoF/RBI/SEBI RSS → MKG policy nodes | Pretend static = live desk |
| 4 | Company documents | PDF upload → Research Worker | IR fetch where allowed; transcripts | Invent line items |
| 5 | News | Operator/RSS allow-list | Claim extract → MKG events | Trade on sentiment alone |
| 6 | Community | Off | Weak `level=E` only | Override research/investment gates |
| 7 | Technicals | Local OHLCV indicators | Support/resistance/breakout features | Require TradingView to compute RSI |
| 8 | Research corpus | IRA + Knowledge | Buffett letters, books, papers | Separate investing LLM outside Knowledge |

### TradingView

Chart links · optional weak ideas · **never** primary feed.

### Screener.in

Highest-value **convenience** for India ratios via **export → import**, always cite origin when known (filing vs screener).

---

## 13. Scoring, portfolio, dossier

### Investment Score (after MKG has something to say)

Axes: Business · Growth · Financial health · Management · Valuation/MoS · Technical · Macro/theme · Risk · **Research confidence** · (report **Investment confidence** separately).

Horizon-specific weights. **Overall score ≠ buy.**

### Portfolio selection (before fill)

Owned? · sector concentration? · cash/risk/persona? · size from MoS + policy + investment confidence?

### Dossier (operator-visible; extend IRA)

```text
Thesis · Business quality · Moat · Risks · Management
Valuation · Technical structure · Policy / theme impact
Recent news · Quarterly changes · MKG neighborhood
Historical decisions · Why Atlas owns/watches
Research confidence · Investment confidence · Evidence · Watch items
```

Prefer this over naked buy/sell signals.

---

## 14. Implementation roadmap (locked ship order)

Operator-reordered priority (evidence & relationships before fancy scoring):

```text
IIP.1  Universe Manager
IIP.2  Discovery Engine (+ Theme Engine v1)
IIP.3  Fundamental import layer
IIP.4  Research Worker document integration
IIP.5  Market Knowledge Graph
IIP.6  Investment Scoring (+ dual confidence + horizons)
IIP.7  Portfolio Optimizer
IIP.8  Thesis Tracker / Outcome Learning
IIP.9  News/policy live feeds & extra market-data vendors (as needed)
```

### Principles

1. Breadth (universes/themes) before scrape farms.  
2. Evidence quality before eloquence.  
3. Relationships (MKG) before advanced scoring.  
4. Same Research Worker for ARs/transcripts.  
5. Host-first batching.  
6. Licensed / operator / official RSS only.

---

### IIP.1 — Universe Manager multi-set · ~1–2 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Index packs | NEXT50, MIDCAP150 (staged), SMALLCAP250 (staged) ✅ |
| Families | index · theme placeholders · operator |
| API / UI | `GET/POST /v1/market/universes*` · Invest intel page ✅ |
| Caps | `max_active_research`, `max_watchlist` / trade-set defaults in view ✅ |
| Default | NIFTY50 still safe default ✅ |
| Feed failures | Durable log + catalog page triage ✅ |

**Done when:** learner can enable NEXT50 ∪ Midcap without rewriting paper config — **met** via Invest intel → Save universes.

---

### IIP.2 — Theme Engine v1 + Discovery Engine v1 · ~2–3 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Theme packs | Seed themes + beneficiary roles ✅ |
| Hypothesis expand | Theme → role → symbol candidates ✅ |
| Screening | Volume, near-high/low, MA20 breakout, momentum, ROCE/debt, policy ✅ |
| Horizon tag | Required on every interesting candidate ✅ |
| Output | `market/discovery/{ist_date}.json` + Invest intel UI + Run now ✅ |
| Caps | `max_interesting`, `max_enqueue_research` ✅ |

**Done when:** one evening run yields ≤40 interesting names mixing screen hits and theme beneficiaries — **met** (worker + API run).

---

### IIP.3 — Fundamental import layer · ~2–3 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Schema v2 | ROE, ROCE, D/E, margins, FCF, promoter %, pledge, growth ✅ |
| Import | JSON API · CSV · `imports/fundamentals/` drop ✅ |
| Screener guide | `docs/SCREENER_FUNDAMENTALS_IMPORT.md` (ToS-safe) ✅ |
| Ladder | Fields → `strengthens_sections` + optional `push_to_ira` ✅ |
| Honesty | Missing → `evidence_sufficiency=missing/weak/sufficient` ✅ |
| UI | Invest intel → Fundamentals paste / drop ingest ✅ |

**Done when:** ≥20 active-set names have non-seed fundamentals; MoS/quality leave pure seeds — **operator action**: import Screener export for watchlist (store + ranking merge ready).

---

### IIP.4 — Research Worker ↔ company documents · ~2–4 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Ingest | AR / quarterly / deck / transcript PDF (+ text paste) ✅ |
| Extract | Guidance, risks, KPIs → claims ✅ |
| Link | Auto-attach to IRA dossier by symbol ✅ |
| Reuse | PDF text layer + Research OCR; same evidence ladder ✅ |
| Guide | `docs/COMPANY_DOCUMENTS_IMPORT.md` ✅ |
| UI | Invest intel → Company documents ✅ |

**Done when:** one uploaded AR PDF measurably lifts dossier coverage/quality — **met** in tests (claims → present evidence + coverage/quality path); operator uploads real ARs on Invest intel.

---

### IIP.5 — Market Knowledge Graph v1 · ~2–3 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Schema | company · theme · policy (+ sparse industry); `benefits_from` / `depends_on` / `affected_by` / `regulates` ✅ |
| Seed | Theme↔company↔policy hermetic + Waaree demo edges ✅ |
| Ingest | Fundamentals join on why-own (read-only); policy/theme refresh via reseed ✅ |
| Query | `why-own` · `who-benefits` · neighborhood ✅ |
| UI/API | Invest intel MKG panel + dossier awareness.mkg ✅ |

**Done when:** Waaree-style “why” cites ≥1 policy/theme edge + financials without inventing links — **met** (`WAAREE.NS` hermetic seed + fundamentals cites in tests).

---

### IIP.6 — Investment Scoring · ~2 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Multi-axis score | Business · growth · financial health · management · valuation · technical · macro/theme · risk ✅ |
| Dual confidence | `research_confidence` ≠ `investment_confidence` on awareness + daily plan ✅ |
| Horizon weights | swing / position / long_term / structural / speculative ✅ |
| Gate visibility | Score band + dual conf on `gate_buy` / `GET /v1/market/score/{symbol}` ✅ |

**Done when:** reports show both confidences; high research + low investment → watch path in tests — **met**.

---

### IIP.7 — Portfolio Optimizer · ~1–2 weeks · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Gates | Concentration, cash, persona, max names, investment confidence floor ✅ |
| Sizing | MoS + risk + horizon (`suggest_notional`) ✅ |
| Pre-trade check | Explicit pass/fail reasons + checks log ✅ |
| Wire | Paper trading buy path after research gate; `POST /v1/market/portfolio/pre-trade` ✅ |

**Done when:** buys require score + research gate + portfolio gate (all logged) — **met** in tests + paper worker.

---

### IIP.8 — Thesis Tracker + outcome learning · ~2 weeks + ongoing · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| Tracker object | Hypothesis · assumptions · horizons · dual confidence at entry ✅ |
| Revisit job | Periodic assumption check vs new evidence (`POST …/revisit`) ✅ |
| Attribution | P&L ↔ which assumptions held/failed ✅ |
| Priors | Feed discovery theme boost + scoring axis penalties (unlock N≥20) ✅ |
| Mentor | Surface failures (“ignored debt”, “overpay”) ✅ |
| Wire | `record_outcome` opens on sim buy / closes on held·weakened·falsified; awareness + Invest intel UI ✅ |
| APIs | `GET/POST /v1/market/thesis-tracker*` ✅ |

**Done when:** N≥20 closed paper outcomes shift at least one prior with test coverage — **met**.

---

### IIP.9 — Live news/policy + vendors · as needed · ✅ shipped 2026-07-27

| Work | Detail |
|------|--------|
| RSS allow-list | Official/operator URLs only; HTML refused; disabled by default ✅ |
| PIB/policy refresh | Policy-kind RSS → gov catalog (`into_policy` / gov worker) ✅ |
| Vendors | Stooq history adapter registered; AV/Polygon unchanged behind keys ✅ |
| Chart links | TradingView / Yahoo / Screener URLs (non-primary) ✅ |
| APIs | `GET/POST /v1/market/news-feeds*`, `GET /v1/market/chart-links/{symbol}` ✅ |
| UI | Invest intel News feeds panel (`dash40`) ✅ |

**Done when:** allow-listed RSS can deepen policy/news without scrape; Stooq + chart links available — **met**.

---

## 15. Calendar (operator-facing)

| Horizon | Focus | Outcome |
|---------|-------|---------|
| **Weeks 1–2** | IIP.1 | Multi-universe |
| **Weeks 3–5** | IIP.2 + IIP.3 | Theme/discovery + fundamentals bottleneck relief |
| **Weeks 6–9** | IIP.4 + IIP.5 | Documents + MKG relationships |
| **Weeks 10–12** | IIP.6 + IIP.7 | Scoring + portfolio gates |
| **Then** | IIP.8 (+ IIP.9) | Thesis Tracker compounding |

Adjust for host load; discovery/MKG builds never block the desktop.

---

## 16. Explicit non-goals

- Real-money brokerage execution  
- New top-level “Investment OS” or parallel Intelligence  
- HTML scraping Screener / TradingView / Moneycontrol as a dependency  
- Replacing IRA with a prompt-only stock picker  
- Trading on community sentiment alone  
- Advanced scoring **before** fundamentals import + MKG v1  
- Instant global multi-country parity  
- Making paper trading the product center again  

---

## 17. Success metrics

| Metric | Target |
|--------|--------|
| Universe breadth | ≥500 symbols membership; ≤50 in active research/trade set |
| Themes | ≥8 seed themes with beneficiary maps |
| Discovery | ≥1 interesting list per NSE week; mix of screen + theme reasons |
| Fundamentals | ≥20% of active set non-seed snapshots |
| MKG | “Why own X?” cites theme/policy relation when edges exist |
| Dual confidence | Both fields on dossier + trade email |
| Thesis Tracker | Every sim buy has hypothesis + assumptions recorded |
| Honesty | Zero invented fundamentals / supply-chain edges |
| Host | Discovery/MKG batches respect Host Guard |

---

## 18. Relationship to locked plans

| Plan | Relationship |
|------|----------------|
| IL | Parent — M0 Universe Manager expands here |
| IRA / Evidence leap | Dossier + confidence spine; IIP feeds evidence + MKG |
| Sector Intelligence (`OI-SI0`) | **Next research lens** — identity → sector pack → strategy **before** MVR (do not mix into Evidence sprint) |
| ARMF (`OI-OPS1`) | Execution capacity so Market research ticks are not starved |
| Market Intelligence Missions | House for all new workers |
| Knowledge Verification | Graph/verification substrate for MKG |
| Host resilience | Assumes Atlas stays up |

IL: *“M0 Investment Universe Manager — not a new Intelligence.”*  
IIP: **Theme + Universe + Discovery + MKG + Thesis Tracker** inside that house.

---

## 19. Operator lock (accepted 2026-07-27)

- [x] Investment Intelligence Platform naming (Market Program framing)  
- [x] No new top-level OS / Intelligence  
- [x] Pipeline: Theme → Universe → Discover → Research → MKG → Score → Portfolio → Sim → Learn  
- [x] Ship order **IIP.1 → IIP.2 → IIP.3 → IIP.4 → IIP.5 → IIP.6 → IIP.7 → IIP.8** (IIP.9 as needed)  
- [x] Hypothesis/theme discovery, not screening alone  
- [x] Research Confidence ≠ Investment Confidence  
- [x] Time horizons on ideas  
- [x] Market Knowledge Graph before advanced scoring  
- [x] Thesis Tracker as first-class learning object  
- [x] No ToS scraping; Screener via export; TradingView non-primary  
- [x] India cash equity first  

**Next action:** finish **Evidence Plan** (Sprint 1); then ARMF A→C; then SI.1+. Master: [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md).