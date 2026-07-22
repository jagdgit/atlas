# Atlas Missions — Operator Guide

> **Audience:** you (the operator) using the console / Jobs / API.  
> **Last updated:** 2026-07-22  
> **Related:** `docs/PHASE_A_PLAN.md` (Missions/Workers), `docs/PHASE_D_PLAN.md` (Paper Trading + Decision Engine), `docs/OPEN_ITEMS.md` (`OI-D1` live market feed).

This document captures how Missions work, how to use each template, the setup work done for paper-trading onboarding, and a clear answer to: *“Can Atlas learn from live markets and simulate real trading on its own books?”*

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
