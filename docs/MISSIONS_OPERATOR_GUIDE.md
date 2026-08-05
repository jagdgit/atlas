# Missions — Operator Guide

> **Audience:** you (the operator) using the console / Jobs / API.  
> **Last updated:** 2026-07-25  
> **Related:** [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) (master),
> [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md),
> [`RESOURCE_OS.md`](RESOURCE_OS.md) (host-first principle + Resource OS — **locked / frozen**),
> [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) (**execute** — IR-* gaps),
> [`HOST_RESPECT_AND_ARCHIVE.md`](HOST_RESPECT_AND_ARCHIVE.md) (Host Guard + Archive ingest — **shipped**),
> [`HOST_UNATTENDED_AND_MARKET_RESILIENCE.md`](HOST_UNATTENDED_AND_MARKET_RESILIENCE.md) (systemd boot + outage/email catch-up),
> [`INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md`](INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md) (Stage 4 🔒 — Theme → Discover → MKG),
> [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) (**locked** — India learner),
> [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md) (Market Program),
> [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md),
> `docs/OPEN_ITEMS.md` (`OI-IL0`, `OI-IL-OX`, `OI-MI0`, …).

This guide is **how to run** missions. For **why missions exist**, read the philosophy doc.
For the autonomous investment learner (Universe → Rank → Simulate → Learn), read the IL plan.

---

### Program dashboards

| Sidebar | What you see |
|---------|----------------|
| **Market** | Watchlist, today's sim plan, checklist, books + mission links |
| **Personal** | Coverage, **Needs confirmation** (Confirm/Reject), tabbed skills/timeline/… |
| **Engineering** | Repo summary chips + ingest + graph/findings |

Hard-refresh the browser after updates. Market watchlist is persisted to disk and recovered from M0 worker checkpoints.

```http
GET /v1/learner/status
GET /v1/market/daily-plan
GET /v1/market/watchlist
```

---

## India equity learner (preferred path)

**Atlas chooses; you constrain.** You do not have to hand-type NIFTY symbols or paste JSON to begin learning.

Guide: `GET /v1/learner/happy-path` · Status: `GET /v1/learner/status` (includes checklist).

### Start (three modes — OX.2)

| Mode | What you say / call | What happens |
|------|---------------------|--------------|
| **Beginner** | Chat: `start India learner with 10000` | Preview M0→M7 plan → say `confirm India learner` or `start India learner now` |
| **Power user** | `start India learner now` | Activates immediately |
| **API** | `POST /v1/programs/market_intelligence/start` with `{"preset":"india_equity_learner"}` | Always immediate |
| **Preview API** | `POST /v1/programs/market_intelligence/plan` | Dry-run (no missions created) |

Preset: **₹10k · NIFTY50 · live Yahoo · empty instruments** → M0 ranks the universe (WHY ± lines + hermetic quality seed) → M1/M2/M3/M5 follow the watchlist. Simulation only (P10).

Cold start: ranking may show **phase=learning / confidence=very_low** until enough bars exist — that is honesty, not a finished edge. Quality lines use **sector proxies** (`hermetic_seed`), not live filings — override via M0 `quality_seed` or disable with `use_quality_seed: false`. M2 auto-seed also attaches hermetic **filing refs** (titles/dates only); POST real refs when you have a ToS-compliant source.

### Multiple books (IL.10)

Each virtual portfolio is its **own** Decision Simulation mission + persona (objective, risk, horizon, capital, allowed assets).

```http
GET  /v1/market/portfolios
POST /v1/market/portfolios
{ "label": "F&O Demo", "capital": 50000, "asset_class": "futures",
  "persona": {"objective": "Learning", "risk": "very_high", "time_horizon": "intraday",
              "allowed_assets": ["futures"]} }
```

Books do not share cash or mentor soft-bias (`portfolio:<key>` tags).

### Instrument packs (IL.11) — sim-on-request

Shared Simulation Engine + per-class rules. **India learner uses `cash_equity` (ready).** F&O is operator-selected demo with lot/margin/expiry gates — **not** the default learner and **not** autonomous ranking.

| Pack | Ready? |
|------|--------|
| `cash_equity` / `etf` | ✅ |
| `futures` / `options` | ✅ sim rules (lot / margin / F&O fees) |
| `commodity` / `currency` / `crypto` | ❌ stub → `capability_gap` |

```http
GET /v1/market/instrument-packs
```

F&O tip: set `lot_size` / `expiry` on instruments (NIFTY defaults to lot 25). Thin cash → `pack_block` on open, not silent fills.

### Market holidays (IL.5+)

Atlas **detects** NSE/BSE/US closed days automatically when `market_session` is set (no hand-maintained holiday list required for 2024–2026 seeds).

```http
GET /v1/market/holidays?calendar=india_equity&year=2026
GET /v1/market/session-status?session=nse_equity
POST /v1/market/holidays
{ "calendar": "india_equity", "day": "2026-07-22", "name": "Special closure" }
```

On a holiday midday, Decision Simulation journals `session_closed (holiday:…)` instead of trading.

### Filings refs (IL.5+)

Hermetic annual/quarterly **metadata** for NIFTY names (not PDF scrapes). Operator snapshots win when posted.

```http
GET  /v1/market/filings?symbol=RELIANCE.NS
POST /v1/market/filings-snapshot
{ "symbols": { "INFY.NS": [{ "title": "AR FY25", "kind": "annual", "as_of": "2025-03-31", "url": "…" }] } }
```

Official NSE/BSE adapters stay `capability_gap` until a ToS client exists — use hermetic refs or the snapshot path.

### Goals & progress (OX.3 / OX.4)

Goals are **objectives first** — Program/Portfolio are optional links.

- Chat: `my goal is Beat NIFTY over 12 months` · `list goals` · `how is my beat-NIFTY goal?` · `learner status`
- API: `GET/POST /v1/goals`, `GET /v1/goals/{id}/progress`, `GET /v1/learner/status`

### Daily Investment Plan (IL.6)

Built from the latest M0 ranked watchlist (simulation sizing only — P10).

```http
GET /v1/planning/daily-investment-plan?portfolio_key=india_equity_learner&capital=10000
GET /v1/market/daily-plan
```

M0 also stashes the plan on the watchlist and refreshes on a **morning cron** (08:45 IST Mon–Fri). Progress / `learner status` shows a “Today's plan …” bullet.

### Screener signals (IL.8)

No website scrapes. Post an operator snapshot (or later a ToS API) — M0 merges into quality ranking.

```http
POST /v1/market/screener-snapshot
{ "symbols": { "INFY.NS": { "pe": 22, "roe": 0.28, "score": 0.9 } } }
GET  /v1/market/screener-signals
```

Disable with M0 `use_screener_signals: false`. Bars can also contribute computed rel-volume / short momentum when present.

### Feeds: live primary, replay for tests

| Path | Role |
|------|------|
| **`feed_mode: live`** | **Operator default** for the India learner (Yahoo / keyed providers) |
| **`feed_mode: asset_replay`** | **CI / hermetic demos** — DEMO fixtures, sample OHLCV. Not the primary learner story. |

Register sample market data only when you deliberately want a **fixture replay** mission — not required for the India learner preset.

---

## Programs (MI.1)

Console **Programs** groups cooperating missions (Market / Engineering / Personal).

1. Open **Programs** → **Market Intelligence**
2. Read the **Cognitive lifecycle** strip (Observe → … → Improve)
3. Prefer Chat/API **India learner** preset above, **or** click **Start Program** (template defaults)
4. Optional: **Context** box gathers “everything relevant to X” (MCA.1)

API: `GET /v1/programs`, `POST /v1/programs/{id}/start`, `POST /v1/programs/{id}/plan`, `GET /v1/programs/{id}/context?q=…`

**M0 — Investment Universe** — NIFTY membership → ranked watchlist with WHY ± explanations. Empty M1/M2/M3/M5 configs auto-load from this list (operator pins still win).

**MI.4 — News / Events**

- **News Intelligence**: operator `headlines`/`items`, or empty → watchlist monitoring seeds (`seed_from_watchlist`).
- **Event Research** polls `MarketInterestingMove` and enqueues research Jobs when `score ≥ score_threshold` (default 0.7).
- **Market Observer** scores price+volume; empty symbols → ranked watchlist (IL.4).

**MI.5 — Company Intelligence**

- Empty tickers → ranked watchlist + minimal membership `config_seed` profiles.
- Richer hermetic profiles still accepted via `companies: […]`.
- Official SEC/NSE/BSE adapters raise capability gaps until API keys + ToS paths exist (`GET /v1/market/company-providers`).

**Portfolio Ledger (MI.6 / IL.7)** — fee/tax-aware sim book + Broker Profiles (`paper_demo`, `zerodha`, `groww`, `angel`, or custom). India learner defaults to **`zerodha`**. Fee components (brokerage, STT, stamp, GST, TDS) persist on trades; withdrawals supported.

```http
GET  /v1/market/broker-profiles
GET  /v1/market/portfolios/{key}/ledger
POST /v1/market/portfolios/{key}/withdraw
{ "amount": 1000, "tds_pct": 0.1 }
```

**Investment Mentor (MI.7)** — weekly synthesis into Experience OS; scoped by `portfolio_key` when set so books do not cross-contaminate.

`paper_trading` remains a **compat alias**; prefer **`decision_simulation`**.

**World Models (WM.1)** — domain *structure* (not Knowledge claims). List packs: `GET /v1/world-models`. Indian markets + solar stub. Mission Context returns `item_kind=world_fact` rows.

**Knowledge Graph (KG.1)** — derived Claim↔Concept↔Entity↔SPO view. `GET /v1/knowledge/graph?q=…`.

**Mission Context (MCA.1)** — `GET /v1/context?q=…`. Decision Simulation cites refs each tick.

**Planning OS (PA.1)** — `GET /v1/planning/plan?goal=…` (also `plan_program_start` for India learner). Never broker login (P10).

**Policy Engine (PA.2)** — soft prefer/avoid + hard `forbid` / `limit`. `POST /v1/policy/evaluate`.

**Memory OS (MEM.1)** — working → session → long_term. `GET /v1/memory/hierarchy`.

**Experience OS (EX.1)** — journal / recall / advice. Mentor + Decision Simulation write through it.

**Unified ingest (OI-C5)** — `atlas ingest <path>` / `POST /v1/ingest`. Candidate drain: `POST /v1/candidates/drain`.

**Capability Registry (CAP.1)** — `POST /v1/capabilities/needs`, `GET /v1/capabilities/gaps`.

**Scheduler hierarchy (SCHED.1)** — `GET /v1/scheduler/hierarchy?program_id=market`. Cron via `worker_specs.cron`.

**Daily Learning Governance (OI-MP3)** — `GET /v1/governance/daily`.

---

## 0. Decision Simulation FAQ (if a mission “does nothing”)

### Preferred fix

Chat: `start India learner now` — or confirm after preview. Empty `instruments` is **OK**: M0 watchlist auto-loads (IL.2/IL.4).

### What is Atlas doing right now?

| You see | Meaning |
|---------|---------|
| Journal: `auto universe (N)…` / `book=india_equity_learner` | Learner path — symbols from M0 |
| Journal: `phase=learning, confidence=very_low` | Cold start — Atlas is not inventing confidence |
| Journal: `idle: no instruments…` **and** no M0 watchlist | Start Investment Universe / India learner, **or** pin `instruments` |
| Journal: `tick: N decision(s)… \| DEMO: hold @ …` | **Fixture replay** path (CI/demo) — not the primary learner |
| Journal: `feed_exhausted` | Replay bars finished — load more fixtures or switch to `live` |

### Fixture replay (CI / demos only)

1. **Register sample market data** (Missions UI) **or** `POST /v1/assets` with `generate_sample: true`  
2. Set `feed_mode: asset_replay` and `instruments: [{"symbol":"DEMO","asset":"demo-feed"}]`  
3. Or Chat/Job: `start paper trading with 10000 on DEMO`

### Does it need logins for live markets?

| Credential | Needed today? | Notes |
|------------|---------------|-------|
| Atlas API / console login | For you to operate Atlas | Normal |
| **Broker trading login** | **Never** | Forbidden (P10) — no real orders |
| **Market-data provider API key** | Optional | Yahoo: `market.yahoo_enabled: true` (no key). Polygon/AV: set env from `market.*_api_key_env`. NSE/BSE still ToS skeletons. |

### Does the mission learn from the web (screener, news sites)?

**Live prices yes; screener sites not yet inside the tick.** News/Company follow the **ranked watchlist** (IL.4). Screener scraping is later (IL.8).

| Path | Role today |
|------|------------|
| Live MarketReader bars (`feed_mode: live`) | **Operator primary** — India learner preset |
| Replay OHLCV (`feed_mode: asset_replay`) | **Tests / CI / DEMO demos** |
| Screener websites inside the tick | ❌ not built |
| News / company along the watchlist | ✅ M2/M3 auto when configs empty |
| Extra research Jobs | ✅ Chat/Jobs (`research`, `media.learn`) |

### How do I verify claims after media.learn?

Learning Reports say **Verification: Not Executed** on purpose (learn ≠ verify).

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk
```

Or mission template `knowledge_verification`. Platform: [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) · Learner: [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md).

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

### `decision_simulation` (preferred) / `paper_trading` (compat)

**Purpose:** Live or replay bars → indicators → Decision Engine → **virtual portfolio** fills → journal + learn. **No broker, no real money (P10).**

**Operator primary path:** India learner preset (`feed_mode: live`, empty `instruments` → M0 watchlist).  
**Replay path:** keep for tests/CI with DEMO fixtures — not the default story.

**Config (important keys)**

| Key | Meaning | Operator tip |
|-----|---------|--------------|
| `starting_cash` | Virtual cash | India learner: `10000` |
| `instruments` | `[{symbol, asset?}]` | **Empty OK** — auto from M0; or pin symbols |
| `portfolio_key` / `persona` | IL.10 book identity | Required fields on persona when multi-book |
| `instrument_pack` / `asset_class` | IL.11 rules pack | Default `cash_equity`; F&O ready for sim books; commodity/FX/crypto → capability_gap |
| `feed_mode` | `live` (primary) or `asset_replay` (CI) | Prefer `live` |
| `live_provider` | `yahoo` / `polygon` / `alphavantage` | Yahoo opt-in in config |
| `market_session` | `nse_equity`, `nse_fno`, `us_equity`, … | India learner: `nse_equity` — **Atlas detects holidays** automatically |
| `strategy` | SMA/RSI params | defaults fine to start |

**Live JSON inputs:** `{"block_symbol":"AAA"}` / `{"unblock_symbol":"AAA"}` — not prose.

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

**Programs UI (preferred):** In **Programs → Personal** or **Engineering**, use **Program chat** / **Share path**. One share registers the root on Owner Knowledge and processes it now:

- Resume / docs → Personal only (same job); **CV text is parsed into inferred facts** (name, education, roles, skills) for Confirm/Reject
- Past-work repos (`code`) → `learn_repository` **once** → Engineering findings **and** Personal experiences

Do not also call Engineering ingest for the same path — that would duplicate the job.

**Career / LinkedIn (suggestions only — P10/P14 · [`CAREER_INTELLIGENCE_PLAN.md`](CAREER_INTELLIGENCE_PLAN.md) LOCKED):**
- Personal → **Career** tab: LinkedIn improvement tips + best open jobs for your profile
- Atlas **never** edits LinkedIn and **never** applies to jobs — you copy tips / apply yourself
- **LinkedIn export (CI.1+):** **One step** — Career → **Ingest export**, or `POST /v1/personal/linkedin/ingest-export` with `{"path":"…"}`. Coaches + snapshot + **auto-wires Career Observer** (creates mission if needed). No separate Observer config step
- **Career Observer / Research:** `career_observer` (discover) + `career_research` (deepen companies) — both BATCH; never recommend/apply
- **Career Advisor** remains `job_hunting` — Opportunity Score v1 + watchlist companies
- **Jobs feed (CI.0.2):** Career → **Import sample / path → Advisor**, or `POST /v1/personal/career/import-feed`
- **CKG / market / gaps / discover / gated-apply:** `GET /v1/personal/career/market|timeline|gaps|brief`, `POST /v1/personal/career/discover`, `POST /v1/personal/career/gated-apply` (LinkedIn always blocked)
- **Watchlist:** `GET|POST /v1/personal/career/watchlist`
- Share a LinkedIn profile export path for better tips; share a jobs JSON export (or configure `job_postings` assets) for ranking
- API: `POST /v1/personal/learn-cv`, `POST /v1/personal/linkedin/suggestions`, `POST /v1/personal/linkedin/ingest-export`, `POST /v1/personal/career/import-feed`, `GET|POST /v1/personal/jobs`, plus market/timeline/gaps/discover/brief/watchlist/gated-apply

API: `POST /v1/programs/{personal_intelligence|engineering_intelligence}/share` with `{"path":"/host/path"}`, or `POST .../chat` with a message like `share /host/path/resume.pdf`.

**Large external archives (USB / One Touch):**
- Do **not** Engineering-ingest a whole 20GB `personal` tree — use **Archive** in the console (or Owner Knowledge `archive_roots`).
- Console: **Archive** nav → path + optional note/period → **Start ingest** (parallel checked = separate mission/worker with its own progress bar). Start another job anytime while the first runs.
- Prefer **selective subfolders** (e.g. Certificates, Design, code projects) — skip photos/zips noise.
- Keep the disk **mounted until ticks finish**; unplug mid-import causes errors.
- Document roots resume **per file** after reboot/power loss (`files_done` checkpoint + `files_per_tick`, default 40). Watch Archive progress bars or mission journal `progress name:done/total`.
- **Host-respect:** only one archive ingest runs by default (`ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS=1`). Extra starts are **accepted and queued** until RAM/CPU/tick slots free — Atlas stays slow but does not drop the job or thrash the host. Ops shows Host guard / tick slots / capacity queue.
- API: `GET /v1/archive/status`, `POST /v1/archive/ingest` with `{"path":"…","parallel":true}`; `GET /v1/resources/guard`; workers also expose checkpoint progress via `GET /v1/workers`.
- Optional: copy priority folders to local disk first for speed/safety.

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

**Jobs live view (OI-UI0):** the Jobs panel refreshes from poll + SSE (`job.activity` / blocked / finalized). After a deploy, a normal reload is enough — `/ui` assets are served with `Cache-Control: no-cache`.

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

**Short answer: yes.** The India learner path (live + M0 → sim) is the spine; screener-in-tick and full fee/TDS realism are follow-ons (IL.8 / IL.7). No broker login (P10).

### What you described

1. Atlas sees **live** market prices (not only fixtures).  
2. Reviews markets via sites like **screener**.  
3. Spawns **Jobs** to gather **related news** from the web into knowledge.  
4. Runs a **simulation** with virtual capital (e.g. ₹/₹10,000).  
5. Keeps **its own books**: buy ₹2000 of a stock, later sell at profit/loss, update net portfolio.  
6. Records **reasons** to invest or sell.  
7. Applies **commissions, TDS, withdrawal** math on the simulated ledger.  
8. **No real money** — only Atlas’s internal records driven by live data.

That combination is **live MarketReader + M0/M2/M3 + Decision Simulation + Broker Profiles** — and still **never** a brokerage login for real orders.

### How Atlas “learns about markets” *today*

Prefer the **India learner** path (live + M0 watchlist). Atlas learns from:

- **Live MarketReader bars** (`feed_mode: live`, Yahoo opt-in / keyed providers) with buy/sell gated by `market_session` — **operator primary**,
- **M0 ranking WHY** + Company/News along the watchlist (IL.3/IL.4),
- **Decisions + outcomes** as experiences when simulated sells realize (portfolio-scoped mentor),
- **Replay / fixture OHLCV** (`feed_mode: asset_replay`) only for CI/demos,
- Optional **Jobs/Chat** research — not yet a continuous screener loop into every tick.

### What already exists vs what is still needed

| Piece of your vision | Today | Still needed |
|----------------------|-------|--------------|
| Virtual cash & positions | ✅ sim portfolio + multi-book (IL.10) | — |
| Buy/sell on signals + journal “why” | ✅ Decision Engine + M0 WHY | Richer news/screener in each tick |
| Learn from outcomes | ✅ experience loop on sells | Cross-mission feedback polish (`OI-F4`) |
| Live prices | ✅ Yahoo/Polygon/AV + session hours + Atlas holidays | NSE/BSE native adapters |
| Universe selection | ✅ M0 NIFTY + ranking | Broader India depth (IL.5) |
| Screener / site review | ❌ not in the tick | IL.8 (APIs preferred) |
| News into the loop | ⚠️ M3 watchlist + separate Jobs | Tighter Decision Context each tick |
| Commissions / TDS / withdrawal | ⚠️ Broker Profiles (MI.6) started | Full IL.7 ledger realism |
| F&O / other classes | ⚠️ separate books + persona | IL.11 futures/options packs ready (sim); commodity/FX/crypto stubs |
| Real money / live orders | ❌ forbidden (P10) | Stay out of scope |

### Important distinction: “live market data” vs “broker login”

| Credential | Needed? | Notes |
|------------|---------|--------|
| **Atlas API / console** | Yes | Auth to Atlas only |
| **Market-data provider key** | Optional (Yahoo needs none) | Read-only quotes — still simulation |
| **Brokerage login** | **Never** | P10 — no real orders |

### Mental model

1. **Start India learner** (preview → confirm, or `… now`).  
2. Constrain with pins / persona / policy when you care.  
3. Use **Goals** + `learner status` for progress.  
4. Use fixture replay only when you want a hermetic DEMO tape.

---

## 7. One-page checklist

- [ ] Prefer **India learner** (`start India learner` → confirm / `… now`) over hand-built JSON  
- [ ] Remember: **Atlas chooses; you constrain** (pin symbols / persona / policy when needed)  
- [ ] Multiple books OK — one Decision Simulation + persona each (`/v1/market/portfolios`)  
- [ ] Goals are objectives first — `my goal is …` / `learner status`  
- [ ] Live feed is the operator path; **replay is for CI/demos**  
- [ ] Steer running sims with JSON live inputs (`block_symbol`), not prose  
- [ ] **No real money ever** (P10)

---

*End of operator guide.*
