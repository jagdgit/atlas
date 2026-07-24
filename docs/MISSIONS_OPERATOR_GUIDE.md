# Missions — Operator Guide

> **Audience:** you (the operator) using the console / Jobs / API.  
> **Last updated:** 2026-07-24  
> **Related:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) (master),
> [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md),
> [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) (Market Program — locked),
> [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md),
> `docs/PHASE_A_PLAN.md`, `docs/PHASE_D_PLAN.md`,
> `docs/OPEN_ITEMS.md` (`OI-D1`, `OI-MP*`, `OI-MI0`, `OI-PA0`).

This guide is **how to run** missions. For **why missions exist** and the
Observe→Learn→Decide→Reflect→Improve loop, read the philosophy doc first.

---

## Programs (MI.1)

Console **Programs** groups cooperating missions (Market / Engineering / Personal).

1. Open **Programs** → **Market Intelligence**
2. Read the **Cognitive lifecycle** strip (Observe → … → Improve)
3. Click **Start Program** — instantiates startable members with template defaults (**no JSON**)
4. Stub members stay listed until MI.2 ships their templates
5. Optional: **Context** box gathers “everything relevant to X” (MCA.1 spike)

API: `GET /v1/programs`, `POST /v1/programs/{id}/start`, `GET /v1/programs/{id}/context?q=…`

**MI.4 — News / Events**

- **News Intelligence** config: `headlines: ["…"]` or `items: [{text, symbol}]` → extracts claims into Knowledge. Optional `verify: true`.
- **Event Research** polls `MarketInterestingMove` and enqueues research Jobs when `score ≥ score_threshold` (default 0.7).
- **Market Observer** scores price+volume; set `spawn_research: true` to spawn Jobs directly (default off — Event Research owns that path).

**MI.5 — Company Intelligence**

- Config hermetic path (no scrape):
  ```json
  {
    "tickers": ["RELIANCE.NS"],
    "companies": [{
      "symbol": "RELIANCE.NS",
      "name": "Reliance Industries",
      "sector": "Energy",
      "facts": ["Reliance Industries owns refining businesses."],
      "filings": [{"title": "Annual Report FY24", "kind": "annual", "as_of": "2024-03-31"}]
    }]
  }
  ```
- Official SEC/NSE/BSE adapters raise capability gaps until API keys + ToS paths exist (`GET /v1/market/company-providers`).

**Portfolio Ledger (MI.6)** — fee/tax-aware sim book + Broker Profiles (`paper_demo`, `zerodha`, `groww`, `angel`, or `custom_broker_profile`). List profiles: `GET /v1/market/broker-profiles`. Example config:

  ```json
  {
    "broker_profile": "zerodha",
    "starting_cash": 100000,
    "pending_fills": [
      {"symbol": "RELIANCE.NS", "side": "buy", "quantity": 10, "price": 2800}
    ],
    "marks": {"RELIANCE.NS": 2850}
  }
  ```

`paper_trading` / `decision_simulation` may set `broker_profile` to charge the same schedules on fills.

**Investment Mentor (MI.7)** — weekly synthesis of market Experiences into a Lesson written back to Experience OS. Decision Simulation pulls `advice_for` into each tick and lightly biases buy scores (caution vs reinforce). Example:

  ```json
  {
    "focus": "markets",
    "lookback": 40,
    "force": true,
    "seed_experiences": [
      {"title": "Paper trade closed on DEMO: loss -10", "tags": ["demo", "paper_trading", "loss", "markets"], "lessons": "Lesson: re-check"}
    ]
  }
  ```

`paper_trading` remains a **compat alias** for Chat/Jobs; prefer **`decision_simulation`**.
Start Program instantiates all seven Market members when templates are seeded.

**World Models (WM.1)** — domain *structure* (not Knowledge claims). List packs: `GET /v1/world-models`. Indian markets + solar stub (solar-plant test). Mission Context (`GET /v1/context?q=NSE`) returns `item_kind=world_fact` rows mixed with Knowledge.

**Knowledge Graph (KG.1)** — derived Claim↔Concept↔Entity↔SPO view over findings (no separate graph DB). `GET /v1/knowledge/graph?q=cash+flow`. Context also returns `item_kind=graph_node`.

**Mission Context (MCA.1)** — shared gather for all Programs: `GET /v1/context?q=…` returns `items`, `sources`, `citations`, `summary`. Decision Simulation pulls this each tick and cites refs in the decision rationale.

**Planning OS (PA.1)** — `GET /v1/planning/plan?goal=Should+I+buy+RELIANCE.NS` (or POST JSON). Returns gaps, alternatives, risks, recommended next steps, and a non-side-effecting decision (simulate / gather / hold). Never broker login (P10).

**Policy Engine (PA.2)** — soft prefer/avoid plus hard `forbid` / `limit` (provenance caps). Evaluate: `POST /v1/policy/evaluate` with `{action, context}`. Decision Simulation blocks hard violations before sim fills.

**Memory OS (MEM.1)** — explicit hierarchy: working → session → long_term (then Knowledge / Experience as separate OS). `GET /v1/memory/hierarchy`, `POST /v1/memory/os/remember` `{content, layer}`, `POST /v1/memory/promote` `{memory_id, to_layer}`.

**Capability Registry (CAP.1)** — missions declare needs instead of importing adapters. `POST /v1/capabilities/needs` `{needs:["MarketReader"]}` or `{mission:"market_observer"}`. `GET /v1/capabilities/inspect`. Missing needs → honest `capability_gap` (Market Observer).

**Scheduler hierarchy (SCHED.1)** — Program → Mission → Worker cadence. `GET /v1/scheduler/hierarchy?program_id=market` (alias for `market_intelligence`). Resolve interval: `POST /v1/scheduler/resolve` `{program_id, template}` (worker_specs > mission cadence > program default 300s).

---

## 0. Paper trading FAQ (read this if the mission “does nothing”)

### What is Atlas doing right now?

| You see | Meaning |
|---------|---------|
| Journal: `idle: no instruments…` | Mission is running but **config has empty `instruments`**. Defaults alone do not trade. |
| Journal: `tick: N decision(s) (+buys/sells/holds); equity… \| DEMO: hold @ …` | Fixture replay is live — decisions each tick. |
| Journal: `feed_exhausted` / `DONE: all feeds exhausted` | Sample/historical bars finished — simulation complete until you load more data. |
| Empty / silent ticks | Older builds idled quietly; restart Atlas to pick up clearer idle notes. |

**Default config is not enough.** You must:

1. **Register sample market data** (Missions UI button) **or** `POST /v1/assets` with `generate_sample: true`  
2. Set `instruments` to something like `[{"symbol":"DEMO","asset":"demo-feed"}]`  
3. Or Chat/Job: `start paper trading with 10000 on DEMO`

### Does it need logins for live markets?

| Credential | Needed today? | Notes |
|------------|---------------|-------|
| Atlas API / console login | For you to operate Atlas | Normal |
| **Broker trading login** | **Never** | Forbidden (P10) — no real orders |
| **Market-data provider API key** | Optional | Yahoo: `market.yahoo_enabled: true` (no key). Polygon/AV: set env from `market.*_api_key_env`. Still **no broker trading login** |

When live data arrives, expect a **data vendor API key** (quotes/candles), not a brokerage password.

### Does the mission learn from the web (screener, news sites)?

**Not as part of the paper-trading tick today.**

| Path | Today |
|------|-------|
| Replay OHLCV → indicators → virtual buy/sell → experience on sells | ✅ |
| Screener websites (e.g. Screener.in) inside the tick | ❌ not built |
| News / web research | ✅ as **separate Jobs/Chat** (`research`, `media.learn`) — **not auto-wired** into each trading decision |
| Verifying claims from videos/news into trusted knowledge | 📋 [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) |

So: start paper trading for **decision practice on sample/historical bars**. Use separate Jobs to learn from YouTube/news. Verification plan makes that knowledge trustworthy for later mission context.

### How do I verify claims after media.learn?

Learning Reports say **Verification: Not Executed** on purpose (learn ≠ verify).

After a COMPLETE learn (e.g. the Kiyosaki video), in Chat/Job:

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk
```

With optional web corroboration:

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk with web search
```

Or use `asset_id` from the report Observations. Continuous option: mission template `knowledge_verification`.  
Expect trust labels / contested flags; a single YouTube source alone will not become HIGH confidence.

Platform framing: [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) · Market Program: [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md).

---

---

## 1. Three different surfaces (don’t mix them up)

| Surface | What it is | Input style | When to use |
|---------|------------|-------------|-------------|
| **Chat** | Conversational turn with Atlas | Natural language | Questions, explanations, one-shot help |
| **Jobs** | Finite async objective (plan → steps → done) | Natural language objective | Research, ingest, *setup wizard* (“start paper trading with 10000…”) |
| **Missions** | Long-running process from a **template** | Structured **config** (+ optional JSON live inputs) | Continuous watchers: paper trading, research, jobs, security, etc. |

**Rule of thumb**

- Want Atlas to *talk* or *do a one-off task* → Chat / Job.  
- Want Atlas to *keep running in the background* → Mission.  
- The worker “Send input” box on a Mission is **not chat** — it only accepts **JSON** control messages.

---

## 2. What a Mission is

Instantiating a template creates:

1. A **Mission** (title, status, priority, journal)
2. A **versioned config** (schema-validated JSON; edits create a new version)
3. One or more **Workers** (tick on a schedule: read → decide → act-in-sim / notify → checkpoint)

Workers survive reboot via checkpoints. Archiving a mission does **not** delete knowledge it discovered (knowledge is global; mission ids are provenance).

---

## 3. Templates — what each one does & how to use it

### Quick status

| Template | Worker? | Typical use |
|----------|---------|-------------|
| `hello_watcher` | Yes | Demo / heartbeat |
| `paper_trading` | Yes | Simulation trading (no real money) |
| `research` | Yes | Continuous literature research on a topic |
| `job_hunting` | Yes | Match job feeds → recommend only (never apply) |
| `repository_learning` | Yes | Continuously ingest + understand a code repo |
| `owner_knowledge` | Yes | Continuously learn from your archive |
| `technology_watch` | Yes | Breaking-change / tech advisories → notify |
| `security_monitoring` | Yes | Security advisories → notify (recommend only) |
| `self_improvement` | Yes | Eval regressions → gated improvement proposals |
| `patent_watch` | **Stub** | Mission + config only; no worker yet |

---

### `hello_watcher`

**Purpose:** Reference heartbeat.  
**Config keys:** `greeting`, `tick_limit` (0 = forever), `tick_interval_seconds`.  
**How to start (UI):** Missions → select `hello_watcher` → Instantiate.  
**Live JSON input:** e.g. `{"note": "operator guidance"}` (generic).

---

### `paper_trading` (flagship simulation mission)

**Purpose:** Replay / tick market bars → indicators → Decision Engine → **virtual portfolio** fills → journal + learn from outcomes. **No broker, no real money (P10).**

**Config (important keys)**

| Key | Meaning | Default idea |
|-----|---------|--------------|
| `starting_cash` | Virtual cash | `100000` |
| `instruments` | `[{ "symbol", "asset" }]` — `asset` = Asset Store name of a `market_data` feed | `[]` (idle until set) |
| `strategy` | SMA/RSI params | `sma_fast/slow`, `rsi_period`, … |
| `bars_per_tick` | How many bars per tick | `1` |
| `tick_interval_seconds` | Schedule | `300` |
| `max_position_qty` / `max_exposure_pct` | Risk caps (`0` = unbounded) | `0` |
| `drawdown_alert_pct` | Notify on drawdown (`0` = off) | `0` |

**Market data today**

- Kind: `market_data` in the Asset Store (JSON or CSV OHLCV).
- **Fixture / sample / replay only** — not a live exchange feed (`OI-D1` still open).
- Easiest path: Missions UI → **Register sample market data** → merge into config → Instantiate.
- Or Job / Chat NL: `start paper trading with 10000 on DEMO` (setup wizard intents).
- Or API: `POST /v1/assets` with `generate_sample: true` or real `content`/`bars`.

**Live JSON inputs (while running)**

```json
{"block_symbol": "AAA"}
```

```json
{"unblock_symbol": "AAA"}
```

**Not valid:** free text like “assume you have 10000…” in the worker input box → UI error *Input must be valid JSON*. Put cash/instruments in **config**, not in that box.

**What it already maintains**

- Virtual portfolio (cash, positions, trades)
- Per-decision journal (why buy/sell/hold)
- Learning from realized sell outcomes (experience loop)
- Net equity from marks + cash (simulation accounting)

**What it does *not* do yet**

- Live prices from the exchange
- Screener sites, news gathering as part of the trading loop
- Broker-style commissions / TDS / withdrawal ledger (beyond simple sim fills)

---

### `research`

**Purpose:** Continuously research a `topic` → promote findings → notify on notable confidence.  
**Config:** `topic`, `max_iterations`, `max_documents`, `per_query`, `embed`, `alert_min_confidence`, `tick_interval_seconds`.  
**How to use:** Set `topic` in config (UI JSON or API overrides), instantiate, watch journal / knowledge.

---

### `knowledge_verification`

**Purpose:** Continuously drain **UNVERIFIED** knowledge findings through the shared VerificationEngine (KV.7). Same path as chat *“Verify claims learned from …”* — no parallel truth store.  
**Config:** `batch_limit`, `gather` (default **false**), `max_gather_iterations`, `claim_types`, optional `asset_id` / `source_url` / `job_id` filters, `alert_on_promoted`, `detect_contradictions` (default **true** — marks opposing KB claims contested), `tick_interval_seconds`.  
**How to use:** Instantiate the template after media learning has produced claims. Idle ticks are quiet when the queue is empty. Prefer operator verify for one-shot; use this mission for ongoing hygiene.

---

### `job_hunting`

**Purpose:** Read job-posting feed assets → match Personal profile + constraints → **recommend only** (never apply — P14).  
**Config:** `sources` (asset names), `locations`, `companies`, `skills`, `min_salary`, `min_skill_overlap`, …  
**How to use:** Register job feed assets, point `sources` at them, set constraints, instantiate.

---

### `repository_learning`

**Purpose:** Continuously ingest a repo (`repo_url` or `repo_path`) into Engineering / Knowledge.  
**Config:** `repo_url`, `repo_path`, `branch`, `languages`, `embed_code`, `policy`, `tick_interval_seconds`.  
**How to use:** Put a path or git URL in config and instantiate (or use Engineering ingest for one-shot).

---

### `owner_knowledge`

**Purpose:** Permanent mission — read User Archive roots into global knowledge + personal profile.  
**Config:** `archive_roots`, `build_profile`, `embed`, `policy`, `tick_interval_seconds`.  
**How to use:** Configure archive roots; leave running.

---

### `technology_watch` / `security_monitoring`

**Purpose:** Watch advisory feeds; Decision Engine prioritizes; notify. Security template uses a higher default severity floor. **Recommend only.**  
**Config:** `sources`, `mode`, `technologies` / `components` / `focus`, `severity_floor`, interval.  
**How to use:** Point `sources` at advisory feed assets; instantiate the template that matches your bias.

---

### `self_improvement`

**Purpose:** Run hermetic evals on a schedule; surface regressions; propose gated remediations (operator must approve).  
**Config:** `fixture_root`, `metric_floors`, `regression_drop`, `gate_fixes`, interval.

---

### `patent_watch` (stub)

Creates a mission + generic config; **no worker yet**. Don’t expect ticks until a real template lands.

---

## 4. Practical how-to (current console)

### Instantiate with config (UI)

1. Open **Missions**.
2. Choose a template — config JSON is seeded from `default_config`.
3. Edit overrides (e.g. `starting_cash`, `instruments`, `topic`, `repo_path`).
4. For paper trading: **Register sample market data** (or upload real OHLCV via API).
5. **Instantiate**.
6. Open the mission → edit **Config** and **Save** anytime (new version; worker picks up next tick).
7. Expand a worker → optional **JSON** live input only.

### Natural-language setup (Jobs / Chat)

Examples that hit the setup wizard intents:

- `start paper trading with 10000 on DEMO`
- `register sample market data for symbol MSFT`

These **create** the mission / feed; they do not replace the long-running Mission itself.

### API (reference)

```http
POST /v1/missions/instantiate
{ "template": "paper_trading", "title": "Learn", "config_overrides": { ... } }

GET  /v1/missions/{id}/config
PUT  /v1/missions/{id}/config
{ "document": { ... }, "activate": true }

GET  /v1/assets?kind=market_data
POST /v1/assets
{ "kind": "market_data", "name": "demo-feed", "symbol": "DEMO", "generate_sample": true }
```

OHLCV JSON shape (also CSV with headers):

```json
[
  {"date": "2024-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}
]
```

---

## 5. Setup work recorded from this chat (2026-07-22)

Operator confusion → product gaps closed:

| Gap | What we added |
|-----|----------------|
| Worker input looked like chat | Documented: JSON-only live inputs; config for cash/instruments |
| UI couldn’t set config without curl | Missions UI config textarea at instantiate + save on detail |
| No HTTP config edit | `GET/PUT /v1/missions/{id}/config` |
| No way to register OHLCV without code | `GET/POST /v1/assets` (+ sample generator) |
| Wanted NL to bootstrap a mission | Job/Chat intents `instantiate_mission` + `register_market_data` |

Code touchpoints (for maintainers): `atlas/web/static/{app.js,index.html,styles.css}`, `atlas/api/{routes.py,schemas.py}`, `atlas/planner/planner.py`, `atlas/jobs/planner.py`, `atlas/services/assistant_service.py`, `atlas/trading/sample_feed.py`, `atlas/kernel/bootstrap.py`.

---

## 6. Your question: live markets + screener + news + full sim ledger — is it possible?

**Short answer: yes, as an architecture — it matches where Atlas is pointed. It is not fully built yet.** No code changes in this note; this is the honest map.

### What you described

1. Atlas sees **live** market prices (not only fixtures).  
2. Reviews markets via sites like **screener**.  
3. Spawns **Jobs** to gather **related news** from the web into knowledge.  
4. Runs a **simulation** with virtual capital (e.g. ₹/₹10,000).  
5. Keeps **its own books**: buy ₹2000 of a stock, later sell at profit/loss, update net portfolio.  
6. Records **reasons** to invest or sell.  
7. Applies **commissions, TDS, withdrawal** math on the simulated ledger.  
8. **No real money** — only Atlas’s internal records driven by live data.

That combination is exactly: **live MarketDataReader + research/news Jobs + paper-trading Mission + richer portfolio accounting**. It does **not** require giving Atlas a brokerage login to place real orders.

### How Atlas “learns about markets” *today* (without live feed)

Today it learns from:

- **Replay / fixture OHLCV** you register (or sample bars),
- **Decisions + outcomes** written as experiences when simulated sells realize,
- Optional separate **Jobs/Chat** research (web/scholar) that enrich *knowledge* — but those are **not yet wired as a continuous input into the paper-trading tick**.

So: it can learn *trading behaviour* from simulated fills on historical/sample series, and it can learn *facts* from research Jobs — but it does **not** yet watch the live tape or screener continuously.

### What already exists vs what is still needed

| Piece of your vision | Today | Still needed |
|----------------------|-------|--------------|
| Virtual cash & positions | ✅ sim portfolio | — |
| Buy/sell on signals + journal “why” | ✅ Decision Engine + strategy rule | Richer reasons (news/screener context) |
| Learn from outcomes | ✅ experience loop on sells | Cross-mission feedback polish (`OI-F4`) |
| Live prices | ❌ fixture/replay only | **`OI-D1`**: live `MarketDataReader` (provider API — *market data* API key, not broker trading login) |
| Screener / site review | ❌ not a trading reader | New reader or scheduled Job that scrapes/fetches screener pages → assets/knowledge |
| News Jobs into the loop | ⚠️ Jobs can research news **separately** | Wire news/knowledge into paper-trading decision context each tick |
| Commissions / TDS / withdrawal | ❌ simple fill accounting | Extend sim portfolio ledger (fees, tax, cash withdrawals) |
| Real money / live orders | ❌ forbidden by design (P10) | Stay out of scope |

### Important distinction: “live market data” vs “broker login”

| Credential | Needed for your vision? | Notes |
|------------|-------------------------|--------|
| **Atlas API key** | Yes (to use Atlas) | Auth to Atlas only |
| **Market-data provider key** (e.g. quote API) | Yes, *if* you want live prices | Read-only quotes/candles — still simulation |
| **Brokerage login / trading password** | **No** | Real orders are out of scope; sim uses Atlas’s own records |

So: **yes — Atlas should eventually see live markets** for the simulation you want; **no — that does not mean logging into a broker to place real trades.**

### Is it possible?

**Yes.** The spine is already there:

```
Live (or fixture) bars → Reader → indicators / knowledge (news, screener)
        → Decision Engine (recommend buy/sell/hold + why)
        → Virtual portfolio (cash, lots, fees, TDS, equity)
        → Journal + experience learning
```

What remains is mostly **plugging live data + richer inputs + ledger rules** into that spine — tracked first by **`OI-D1` (live market-data feed)**, then screener/news integration and fee/tax accounting as follow-ons.

### Suggested mental model for you as operator (until live lands)

1. Use **sample or historical OHLCV** to practice the Mission loop now.  
2. Use **Jobs** for news/research to build knowledge in parallel.  
3. Treat live quotes + screener + fee/TDS ledger as the **next product slice**, not a missing philosophy — the design already says simulation-only + pluggable market reader.

---

## 7. One-page checklist

- [ ] Pick the right surface: Chat / Job / Mission  
- [ ] For paper trading: register a `market_data` asset (sample is fine)  
- [ ] Set `starting_cash` + `instruments` in config  
- [ ] Instantiate and watch **Journal** + portfolio behaviour  
- [ ] Steer with JSON live inputs (`block_symbol`), not prose  
- [ ] Use Jobs for news/research; don’t expect worker input to be a chat box  
- [ ] Remember: **no live tape yet** (`OI-D1`); **no real money ever** (P10)

---

*End of operator guide.*
