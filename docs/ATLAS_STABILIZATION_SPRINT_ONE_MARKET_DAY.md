# Atlas Stabilization Sprint — One Reliable Market Day

> **Status:** 🔒 **LOCKED** — operator lock 2026-08-12 evening · **execute STAB0 before any other work**  
> **Codename:** `OI-STAB0`  
> **Horizon:** **10 days** with buffer · **market sessions as the unit of truth**  
> **Scope (first reliable day):** **Equity-only** (`india_equity_learner`)  
> **Parents:** [`OPS_STARVATION_CLEANUP_AND_MARKET_FOCUS_PLAN.md`](OPS_STARVATION_CLEANUP_AND_MARKET_FOCUS_PLAN.md) ·
> [`ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md`](ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md) ·
> [`RESOURCE_OS.md`](RESOURCE_OS.md) · today audit canvas `atlas-today-activity-2026-08-12`  
> **Audience:** operator (CTO-mode) + implementers  
> **Code:** not started — lock first, then implement in §9 order

---

## 0. Operator thesis (LOCKED)

Belief Core direction is correct. **Belief Core cannot learn from broken perception.**

```text
Ownership (Activity Journal)
        ↓
Perception → Execution → Attribution → Belief Revision → Intelligence
     ↑              ↑            ↑              (SELF0 started)   (SELF0 started)
   DIRTY          NOISY        WEAK
```

**This sprint is a stabilization sprint, not an intelligence sprint.**

Stop almost all new feature / intelligence work for **10 days**. Primary goal:

> Make Atlas produce **one reliable equity market day from open → close** without manual babysitting — and **own that day in a work journal**.

### 0.1 Identity, not just memory

The reply *“I don’t have a record of my activities today”* is not primarily a memory bug.

| Router | Employee / colleague |
|--------|----------------------|
| “I don’t know.” | “Here’s what I worked on today.” |
| Answers requests | **Owns work** |
| Infrastructure | Agent with continuity |

**Intelligence ≠ ownership.** Humans judge agents through **continuity**.

STAB0 therefore starts with **P0.0 Daily Activity Journal** — structured work events, not debug logs — so “What did you do today?” is a deterministic query. No LLM required.

**Target sentence Atlas must be able to say (example):**

> Today I spent most of my time trying to obtain reliable market marks. I sent eight investor reports, advanced sixty-one research dossiers, evaluated forty-four paper positions, and failed to trade because Yahoo rate limiting left the equity feed five days stale. I have not yet solved that problem.

That is not consciousness. **It is agency.**

**Do not judge the day by whether Atlas buys a stock.**  
Judge it by whether Atlas can **observe** the day with clean data, **journal** the work, and **explain** why it did or did not act.

---

## 0.2 Operator locks (2026-08-12)

| # | Question | **LOCK** |
|---|----------|----------|
| 1 | FNO | **A — pause FNO lab** during STAB0 |
| 2 | Ticks | **Yahoo first** → diagnose clamp → then **effective 4** |
| 3 | Archive | **Force 1** during market hours (even if `.env=2`) |
| 4 | Scope | **Equity-only** first reliable day |
| 5 | Horizon | **10 days** with buffer |
| 6 | Success metric | **Observe + explain**, not buy |
| 7 | SELF0 Phase 5 | **Freeze until ≥5 consecutive clean sessions** |
| 8 | Activity Journal | **Mandatory** — P0.0 before STAB0 complete |

---

## 1. Brutal diagnosis (2026-08-12 evidence)

| Symptom | What it really means |
|---------|----------------------|
| Yahoo **429 × 237**, feed gap **4–5d**, marks unavailable | Perception telescope is dirty — highest *data* blocker |
| “What did you do today?” → “no record” | **Identity / ownership** gap — router, not employee |
| FNO pack = futures, planned = cash `.NS` | Architecture bug → pause lab (Lock 1) |
| Thousands of `session_closed` / `mark_only` | Expected states counted as failure noise |
| 15 starved, ~60 deferred, CPU/RAM headroom | Capacity **policy** starvation |
| `.env` ticks=4 but Ops **effective 2/2** | Profile / Host Guard clamp |
| Mail + 61 dossiers + 0 buys | Not idle — **unfillable + capacity-starved** |
| MEM.1 AttributeError | Belief bridge broken |
| SELF0 Phases 1–4 landed | Mind scaffolding exists; **fuel + ownership** missing |

**One-line verdict:** Clean the telescope **and** give Atlas a work journal — then the mind can think about real days.

---

## 2. Freeze list (LOCKED for STAB0)

Until Phase 0 acceptance passes **two consecutive equity market sessions**, and Phase 5 until **≥5 consecutive clean sessions**:

| Freeze | Why |
|--------|-----|
| SELF0 **Phase 5** soft influence | Beliefs without clean perception = wrong weights |
| FNO lab trading / FNO universe expansion | **Unlocked 2026-08-13** (operator). Re-pause with `ATLAS_STAB0_PAUSE_FNO=1` if Yahoo/ticks starve equity. Still not a STAB0 pass gate. |
| Intraday as “first reliable day” success gate | Equity-only first (Lock 4) — intraday may run but does not define pass |
| New mentor / intelligence features | Adds starved BATCH load |
| AtlasNet / live NN expansion | Marks still dishonest |
| New labs / programs | Multiplies Yahoo + tick pressure |
| Broad BRE LLM densify (except MEM.1) | LLM budget after perception works |
| UI redesign / non-market polish | Distraction |

**Allowed:** bugfixes that unlock P0/P1 acceptance only (journal, Yahoo choke, session honesty, MEM.1, tick clamp, archive=1 RTH, zombie cleanup).

---

## 3. What already exists (consolidate, don’t reinvent)

| Piece | Note | Gap |
|-------|------|-----|
| `day_activity` chat brief | Reconstructs from artifact files | **Not a live journal** — retrofit later to read `activity_events` |
| Yahoo rate gate | Exists | Many callers still race / duplicate |
| `bar_store` / historical bars | Exists | Not sole live mark path |
| Resource OS / Host Guard | Exists | Preferred ≠ effective ticks |
| Belief Core + Living RAG | SELF0 1–4 | Hungry for honest outcomes + ownership |

**MarketDataService** = choke wrapping gate + bar_store + chart fetch — not a second Yahoo client.

---

## 4. Order of work (LOCKED)

```text
P0.0  Daily Activity Journal (ownership)     ← first
P0.1  Yahoo / MarketDataService (perception)
P0.2  Pause FNO (+ pack honesty for active labs)
P0.3  Session-state honesty
P0.4  MEM.1 fix
P1    Starvation / ticks / archive / zombies
P2    Attribution → belief densify
P3    Living RAG harden + transfer (after 0–2)
```

**Do not jump ahead.**

---

## 5. Phase 0 — Operational + ownership (P0)

**Goal:** Own the day in a journal; observe equity market; paper decisions with honest outcomes; no manual babysitting.

### P0.0 — Daily Activity Journal (**NEW · mandatory**)

**Before Yahoo. Before ticks. Before FNO pause mechanics.**  
(Audit Yahoo *in parallel* on Day 1 morning once journal emit path exists.)

Every meaningful Atlas action creates an **Activity Event** — a **work journal**, not debug traces.

#### Schema (proposed)

```text
activity_events
  id
  ts              -- timestamptz (IST-aware in API; store UTC)
  domain          -- market | engineering | personal | cross | system
  worker          -- worker type or service name
  action          -- send_morning_plan | evaluate_hold | yahoo_cooldown | …
  target          -- optional symbol / lab / recipient class
  result          -- completed | skipped | failed | deferred
  summary         -- one human sentence
  evidence        -- jsonb refs (paths, ids) — no secrets
```

Example:

```json
{
  "ts": "2026-08-12T09:42:00+05:30",
  "domain": "market",
  "worker": "investor_mailer",
  "action": "send_morning_plan",
  "result": "completed",
  "summary": "Sent morning investor plan to configured recipients"
}
```

#### Emitters (minimum for STAB0)

| Emitter | Example actions |
|---------|-----------------|
| Investor mailer | morning / hourly / evening sent or skipped |
| Paper trading (equity) | evaluate buy/sell/hold · session_closed · mark_only · capability_gap |
| Market data / Yahoo gate | cooldown entered · batch fetch · cache hit rate summary |
| Research / dossiers | dossiers advanced (batch summary OK) |
| BRE / hypothesis | skipped budget 0 · completed |
| Belief Core | consult N · revise |
| Memory distill | completed / failed (+ error class) |
| Host Guard | deferred tick (reason class) |

#### Chat

“What did you do today?” → deterministic:

```sql
SELECT summary FROM activity_events
WHERE ts::date = :today_ist
ORDER BY ts;
```

(or equivalent repo API). Wire `day_activity` to this store; keep artifact fallback until backfill exists.

#### Acceptance (P0.0)

| Check | Target |
|-------|--------|
| Events written during RTH without manual steps | Yes |
| “What did you do today?” returns ordered journal | No LLM; not “I don’t have a record” |
| At least mail + paper + yahoo-gate + research-summary classes | Present on a test day |
| Not a second copy of `atlas.log` | Summaries are work-shaped, not stack traces |

---

### P0.1 Fix Yahoo / market-data reliability

**Order vs P0.0:** Journal emit path first; **Yahoo audit + choke same Day 1** (journal should record 429 / cooldown events).

| Cause | Likelihood |
|-------|------------|
| A. Too many requests too quickly | High |
| B. Multiple workers same symbol | High |
| C. No shared live mark cache | High |
| D. Parallel overlapping fetches | Medium |

**Implement:**

1. One **MarketDataService** — sole Yahoo chart/quote caller.  
2. Shared **~5 min** mark cache.  
3. Batch / paced fetch through existing rate gate.  
4. **session-fresh bar_store first** — if last bar ≥ last NSE session, use durable; else paced Yahoo + persist; cooldown → honest stale.  
5. Request audit: `ts, worker, symbol, url_class, status, cache_hit`.

**Acceptance:**

| Metric | Target |
|--------|--------|
| Feed gap (equity watched / planned) | **&lt; 30 min** |
| Yahoo 429 (session) | **0** (or rare single + cooldown) |
| Marks available | **&gt; 95%** |
| Valuation basis | Not majority “average cost (marks unavailable)” |

---

### P0.2 FNO — **PAUSE** (Lock 1)

- Pause `india_fno_learner` paper trading for STAB0 (worker/mission paused or schedule gated).  
- Do **not** expand FNO universe mapping in this sprint.  
- Equity lab must not emit futures-only symbols; pack honesty for **active** labs.

**Acceptance:** FNO not consuming ticks / Yahoo budget; equity `capability_gap` from pack mismatch **near 0**.

---

### P0.3 Market session handling honesty

```text
Market closed → evaluate → store observation (+ activity event) → no trade attempted
```

`session_closed` / `mark_only` = **expected idle**, not failed decisions.

**Acceptance:** KPIs / journals separate expected idle vs data/capability blocks.

---

### P0.4 Fix MEM.1 AttributeError

**Acceptance:** Memory distill evening path completes without traceback (structural layers required; LLM optional). Emit activity event success/fail.

---

## 6. Phase 1 — Remove starvation (P1)

**Goal:** Think while equity market is open.

### P1.1 Effective tick slots

Yahoo clean **first** (Lock 2). Then diagnose preferred→effective clamp. Run full RTH at **effective 4** when safe.

### P1.2 Archive = 1 in RTH (Lock 3)

Force archive lane max **1** during market hours regardless of `.env=2`.

### P1.3 Priority lanes (ARMF)

| Lane | Examples |
|------|----------|
| Realtime | paper (equity), market observer, market data, investor reports |
| Cognitive | belief consult, reflection, attribution, research synthesis |
| Background | mentors, archives, historical rebuilds |

### P1.4 Kill duplicate / zombie workers

Preview cleanup; retire duplicates (`decision_meta_learning` ×2, etc.).

**Acceptance:** Starved **&lt; 5** by RTH close (or clear trend); Host Guard ok; no fake duplicate starvation.

---

## 7. Phase 2 — Make Atlas learn (P2)

After Phase 0 (clean perception + journal) and Phase 1 (can think in RTH).

- **P2.1** Belief consultation on meaningful equity decisions  
- **P2.2** Experience attribution (why / evidence / outcome / belief delta)  
- **P2.3** Nightly reflection density (LLM budget here)

---

## 8. Phase 3 — Feel alive (P3)

Living RAG + day brief exist. After 0–2: harden journal-backed identity answers; cross-domain transfer only after clean days + attribution.

---

## 9. Execution calendar (LOCKED)

| Day | Focus |
|-----|--------|
| **D1** | **P0.0 Activity Journal** · Yahoo request audit · MarketDataService choke design |
| **D2** | Shared cache · bar-store first · **FNO paused** · MEM.1 |
| **D3** | Tick clamp diagnosis · archive=1 RTH · duplicate workers |
| **D4–D5** | Clean **equity** market sessions · honest day brief from journal · belief consult metrics |
| **D6–D10** | Attribution · reflection density · identity integration · buffer |

Unit of progress = **equity market session**, not PR count.

---

## 10. Dashboard (every session)

| Metric | Target |
|--------|--------|
| Activity events today | Non-zero; mail+paper+data classes present |
| “What did you do today?” | Journal answer (not “no record”) |
| Yahoo 429 | **0** |
| Feed gap | **&lt; 30 min** |
| Marks available | **&gt; 95%** |
| `capability_gap` (active labs) | **Near 0** |
| `session_closed` | Expected only |
| Starved workers | **&lt; 5** |
| FNO | Paused |
| Archive RTH | **1** |
| Session buys | **Not** a success metric |
| Belief consultations | Track; **&gt; 20/day** after P2 |
| Belief revisions | **0–2/day is fine** |
| SELF0 Phase 5 | Frozen until **≥5** clean sessions |

---

## 11. Acceptance — “One reliable equity market day”

A session **passes** when all are true:

1. **Activity journal** covers the day; chat day-brief reads it.  
2. Feed gap &lt; 30 min for ≥95% of equity planned / watchlist symbols.  
3. Session Yahoo 429 = 0 (or documented single cooldown + recovery).  
4. Equity paper workers tick open→close without manual restart.  
5. Decisions journaled with **honest** reasons (data gap ≠ silent average-cost fiction).  
6. Atlas can say (mail or chat): *what I worked on, what I observed, why I did / did not act*.  
7. Host Guard ok; starved &lt; 5 or trending with zombies retired; FNO paused; archive=1 in RTH.

**Two consecutive passing sessions** → Phase 0 done → Phase 1/2 unlocked → **OI-AGENT1** eligible to unfreeze.  
**≥5 consecutive clean sessions** → SELF0 Phase 5 unfreeze eligible (separate lock).

See [`ATLAS_AGENT1_PERSISTENT_OPERATOR_PLAN.md`](ATLAS_AGENT1_PERSISTENT_OPERATOR_PLAN.md).

---

## 12. Discussion / lock log

| Date | Note |
|------|------|
| 2026-08-12 evening | DISCUSSION draft: clean the telescope first. |
| 2026-08-12 evening | **LOCKED.** Operator locks 1–8. **P0.0 Activity Journal** added as mandatory ownership layer. FNO pause; equity-only; 10-day horizon; Yahoo before ticks; archive=1 RTH; observe+explain; Phase 5 until ≥5 clean sessions. No code yet — await “go”. |
| 2026-08-12 evening | **GO — Day 1 started.** Migration `0051_activity_events`. Journal service + bootstrap bind. Emitters: investor mailer (morning/hourly/evening), paper_trading tick summary, yahoo cooldown (+ audit jsonl), bootstrap. Chat day brief prefers journal. FNO lab short-circuits in `do_tick`. `MarketDataService` scaffold + `/v1/market-data/status` + `/v1/activity/today`. Tests `test_stab0_activity_journal.py`. |
| 2026-08-12 evening | **Day 2 done.** MarketReader bar-store-first (stale before Yahoo network) + MDS tip cache/audit. MEM.1 ChatMessage fix + activity journal emit. Host Guard archive forced to 1 in NSE RTH (`archive_one_in_rth`). Tests extended in `test_stab0_activity_journal.py`. |
| 2026-08-12 evening | **Day 3 done.** Tick clamp: `_budget_pressure` no longer halves slots on single-tick admit miss (Ops 2/2 mirage). Budget snapshot `clamp_reason`/`diagnosis` + activity emit on change. Duplicate-worker cleanup (`include_duplicates` · `decision_meta_learning`). Yahoo soak counters on `/v1/market-data/status`. **Root cause of Ops 2/2:** stale `/etc/atlas/atlas.env` (`conservative`/hard=2) vs repo `.env` overnight/4 — bounce script syncs env. |
| 2026-08-12 evening | **Day 4 landed (code).** Mark honesty (`valuation_basis` / mixed / avg-cost labeled). `yahoo_cooldown` idle bucket. Day brief “why I did/did not act” + belief metrics. KPI valuation line. `GET /v1/market/session-readiness`. Tests `test_stab0_session_honesty.py`. **Operator:** `sudo bash scripts/bounce_atlas_stab0.sh` before next RTH. |
| 2026-08-12 19:46 IST | **hello_watcher CLEAN.** `stab0_finish_hellos.sh`: 2 orphans force-stopped; verify candidates=0. Next: overnight paced bar tip refresh → morning session-readiness (`feed_gap`). |
| 2026-08-12 evening | **OI-AGENT1 locked.** Next milestone after STAB0 = Persistent Operator (agenda / day brief / goals / waiting / check-ins). **Frozen** until two consecutive clean equity sessions. Plan: [`ATLAS_AGENT1_PERSISTENT_OPERATOR_PLAN.md`](ATLAS_AGENT1_PERSISTENT_OPERATOR_PLAN.md). SELF0 Phase 5 still needs ≥5 clean sessions. |
| 2026-08-13 evening | **First equity session observed.** Journal 767 (paper_tick 494 · FNO pause 246 · hourly×9 · morning+evening). Equity book still CIPLA×13 + EICHERMOT×2 — **no IST-day sim fills**; KPI “7 buys today” was untagged historical blotter (honesty fix). Intraday ticked but 0 fills (PLC.A + daily-bar mark_only). **FNO unpaused** (opt-in env). PLC.A skipped for intraday/FNO. UI ledgers show today-fills + idle reasons. Need **2nd consecutive** clean session. |
| 2026-08-13 evening | **Live marks for paper sim.** Operator: Atlas must see session-fresh data. Root cause: MarketReader used any priced durable (FRESH_DAYS=5) before Yahoo, and live ticks never persisted. Fix: session-fresh store → skip network; else paced Yahoo (3/60s) + `persist_symbol_bars`; cooldown/budget → honest stale. Paper tick refreshes open positions first. Hist bootstrap 1mo tip-refresh when dense but stale. **Bounce required.** |
| 2026-08-17 evening | **OI-LOOP0 locked.** Operator: labs empty; need 1m?; close the learning loop. Plan: [`ATLAS_CLOSED_LOOP_LAB_WAKE_PLAN.md`](ATLAS_CLOSED_LOOP_LAB_WAKE_PLAN.md). Equity does **not** wait on 1m. Intraday does (5m first). FNO = index-proxy lot, not cash alts. Belief consult mandatory, Phase 5 still frozen. | |

---

## 13. Sentences to remember

> **Clean the telescope first.**  
> **Atlas must own its work.**  
> Continuity beats another LLM.  
> One reliable equity day — then the mind has something real to think about.
