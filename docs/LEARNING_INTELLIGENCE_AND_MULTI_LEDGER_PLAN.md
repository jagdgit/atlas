# Learning Intelligence & Market Laboratories Plan

> **Status:** 🔒 **PLAN LOCKED** (2026-08-07) · **Architecture frozen** · **Implement LI.1a → … in order**  
> **After lock:** new ideas become **OI items / future LI phases** — not further architectural rewrites  
> **Governance:** respects [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) —
> **no new top-level OS**; Learning Intelligence is a **Market Intelligence capability** on Decision + Experience + Resource OS  
> **Trigger:** Operator review — learning AI, not busy AI; laboratories, not mere ledgers  
> **Parents:** [`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md) (🔒 DI.1→DI.7) ·
> [`TRADING_STRATEGY_PLAYBOOK.md`](TRADING_STRATEGY_PLAYBOOK.md) ·
> [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md) ·
> [`INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md`](INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md) ·
> [`SCREENER_FUNDAMENTALS_IMPORT.md`](SCREENER_FUNDAMENTALS_IMPORT.md) ·
> [`ATLAS_IMPLEMENTATION_ROADMAP.md`](ATLAS_IMPLEMENTATION_ROADMAP.md) · Resource OS / Host Guard  
> **Open item:** `OI-LI0` — **plan locked**; **LI.1a–LI.6 ✅** (implementation complete)  
> **Next (🔒 locked):** [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) (`OI-MLQ0`) — **LQ.1–LQ.9 ✅ shipped** (does not reopen this architecture)
> **Default laboratory today:** `india_equity_learner` → Equity Swing Laboratory  
> **Migrations:** next free `0049` (only if LI.1a needs schema beyond alias)  
> **Execution rule:** every LI PR must preserve **laboratory hermeticity** (§0.2)

---

## 0. One-sentence verdict

**The bottleneck is not trade count — it is diversity, provenance, and quality of labeled experiences inside independent Market Laboratories.** Decision Intelligence freezes beliefs; this plan adds laboratory identity (ledger is only accounting), hypothesis learning, failure taxonomy, evidence tiers, controlled world-knowledge transfer, and Learning Intelligence / Atlas IQ / evolution memory — under Resource OS — with AtlasNet only when a **quality-gated** decision dataset exists.

**Philosophical redirect:** from *busy fills* to *scientific laboratories that run experiments, record hypotheses, name root causes, and measure whether Atlas itself got smarter — without inventing a new OS pillar.*

---

## 0.1 Governance — protect the finalized roadmap

This document is the **last Market-learning architecture pass** for this family. It must **not**:

- invent a new top-level OS (“Learning OS”)  
- reopen Platform / Resource / Planning architecture  
- spawn endless sibling redesign docs after lock  

**Learning Intelligence = Market Intelligence Program capability**, built on:

| Uses | Does not become |
|------|-----------------|
| Decision Intelligence (packets, timeline, attr) | New OS |
| Experience OS (journal, lessons) | Parallel Experience rewrite |
| Resource OS / Host Guard (cadence, admission) | Scheduler replacement |
| Knowledge / IRA (research versions, evidence) | Separate research product |

After 🔒: refinements → **`OI-LI*`** or LI phase tickets against this file. Aligns with roadmap: *“Stop creating new architectural documents… implement… Prefer tickets / OI items.”*

**Explicitly rejected now (and until quality dataset exists):** reinforcement learning, LLM fine-tuning, deep-learning trading loops. They need attributed experience Atlas does not yet have.

### 0.2 Engineering rule — laboratory hermeticity (every LI PR)

**Not an architecture change — an execution rule.**

Every Learning Intelligence implementation PR **must** preserve laboratory hermeticity.

If a new feature cannot prove that it does **not** leak **statistics, priors, cash, experiments, or outcome labels** across laboratories, the PR is **incomplete**.

Required automated coverage (grow with phases; LI.1a seeds the suite):

| Suite | Protects |
|-------|----------|
| Isolation tests | `laboratory_id` / ledger / KPI paths stay separate |
| Cross-lab contamination tests | No pooled win-rate, expectancy, or return labels |
| Controlled-transfer tests | World facts may flow; strategy/returns must not (LI.0a / later) |
| Provider conflict tests | Evidence tiers (LI.2) |
| Deposit/withdraw audit tests | Capital legs (LI.1b) |
| Laboratory-specific mail tests | Morning / fill / evening lanes (LI.1b) |

Tests protect this architecture better than more documentation. Prefer failing closed (raise / refuse) over silent mixing.

---

## 1. Diagnosis (today’s email is not a failure)

From **2026-08-07** evening digest:

| Signal | Reading |
|--------|---------|
| 39 decisions · 0 fills · 0 sells | Quiet hold; thin cash; trim / cannot size |
| 0 observations · 0 attributions | Sensory + exit labels starved |
| 16 revisits / 0 done | Evolution incomplete |
| PE 0/0 | Empty fundamentals store — honesty |
| Score 32.5 | Process up; outcomes unproven |

**Wrong problem:** not enough trades.  
**Right problem:** not enough **diverse, closed, attributed** laboratory experiences — including rejects, misses, and failed hypotheses.

---

## 2. What already exists (do not rebuild)

| Capability | Status | Gap |
|------------|--------|-----|
| DI.1→DI.7 | ✅ | No LI / IQ / hypothesis / failure taxonomy / evolution log |
| IL.10 portfolios + IL.11 packs | ✅ | Need **Laboratory** container semantics |
| Sim capital / net contributed | ✅ partial | First-class deposit/withdraw per lab ledger |
| Morning/evening mail | ✅ one path | Per-laboratory mail lanes |
| Fundamentals import | ✅ | Provider tiers + Yahoo medium |
| Yahoo bars | ✅ | No yahoo fundamentals yet |
| Never mix strategy_tags | ✅ | Never mix labs; controlled transfer |
| Resource OS | ✅ | Bind observation/mail cadence to Host Guard |
| `live_nn_trading=False` | ✅ | Keep + quality gates |

---

## 3. Think in Laboratories (not “ledgers”)

A **ledger is accounting.** A **Laboratory** is where experiments happen.

```
Market Intelligence Program
        │
        ├── Laboratory: Equity Swing
        ├── Laboratory: Equity Intraday
        ├── Laboratory: Futures
        ├── Laboratory: Options
        ├── Laboratory: ETF
        ├── Laboratory: Macro          (future)
        ├── Laboratory: Crypto         (future / stub)
        └── Laboratory: Global Equity  (future)

Each Laboratory contains:
  Ledger              (cash, positions, fees, deposits/withdrawals)
  Personality         (mentor, risk, capital policy, holding philosophy,
                       confidence calibration, review schedule)
  Strategies          (playbook lanes)
  Experiments         (experiment_id + version + hypothesis link)
  Models              (later — lab heads only)
  Reports             (morning / fill / evening / weekly)
  Memory              (lab-scoped Experience, priors, packets, timeline)
```

Five-year shape: many laboratories, each with **multiple** experiments, strategies, and eventually neural heads — still never pooling win-rates.

Canonical id: `laboratory_id` (alias `lab_id` in code ok). IL.10 `portfolio_key` maps 1:1 to a Laboratory.

### 3.1 Laboratory personality

| Dimension | Swing | Intraday | F&O |
|-----------|-------|----------|-----|
| Mentor | MoS / patience | Session risk | Margin / lot / expiry |
| Risk | Thesis risk OK | Capital preservation | High, pack-gated |
| Capital | Gradual + buffer | Tight day risk; no overnight v1 | Margin aware |
| Holding | Weeks; ignore noise | Flat EOD | Contract lifecycle |
| Calibration | Research depth | Liquidity + timing | Pack readiness |
| Review | D1/W1/M1/Q | Same-day + next open | Expiry-aware |

### 3.2 Never mix vs controlled transfer

**Never mix:** win rate, expectancy, Sharpe, strategy priors, experiment winners, entry soft-bias, NN return labels, pooled “Atlas win rate.”

**Transferable (`transfer_class=world`):** business quality, sector knowledge, management, macro, regulation, filing-tier fundamentals, regime *context*.

Consumers must **cite** transfers on packets. Learning Intelligence tracks transfer usefulness separately from lab edge.

### 3.3 Mail, ledger, capital

| Message | Scope |
|---------|--------|
| Morning plan | Per Laboratory |
| Buy/sell fill alert | Per Laboratory |
| Evening EOD | Per Laboratory |
| Weekly | Per Laboratory + optional cross-lab LI summary (**no** pooled win-rate) |

Each Laboratory: separate sim ledger; first-class **deposit** / **withdraw** with cash-flow audit. No silent cross-lab cash (optional later: explicit two-leg transfer).

### 3.4 Overall learning — yes, correctly

| Layer | Overall? | What |
|-------|----------|------|
| Lab Memory / KPIs / priors | No | Character + edge |
| World knowledge transfer | Yes | Business / sector / mgmt / macro |
| Learning Intelligence / Atlas IQ / evolution log | Yes (meta) | Self-improvement |
| Future AtlasNet | Shared world encoder + lab heads | See §8 |

---

## 4. Evidence tiers & Provider Manager

Evidence Value = `{value, source, provider, as_of, confidence, verified, ttl, raw_ref}`.

| Provider | Quality |
|----------|---------|
| `yahoo_fundamentals` | medium (opt-in auto) |
| `screener_export` | high |
| `filing` / IRA | very_high |
| `manual` | high |
| `licensed_api` | high–very_high (future) |

Reconcile: keep all; prefer verified/high; &gt;15% gap → conflict unknown — **never invent blended PE**. Yahoo is a provider, not Truth.

---

## 5. LI.0a — Learning Infrastructure

### LI.0a.1 — Confidence calibration

Stated confidence vs outcome → lab calibration curves; packets keep original confidence immutable.

### LI.0a.2 — Market regime memory

`regime → decision → outcome → lesson`  
Vocabulary: bull · bear · sideways · high_vol · election · geopolitical · budget · pandemic · rate_cut · rate_hike · unknown (null OK).

### LI.0a.3 — Forgotten opportunities

Kinds: `ignored` · `missed` · `rejected` · `deferred` — later material moves create opportunity outcomes (separate from trade win-rate gates).

### LI.0a.4 — Decision / research aging

Bands: `fresh` · `current` · `stale` · `expired` — decay feature weight; force refresh before strong confidence.

### LI.0a.5 — Experiment framework

`experiment_id` · `strategy_tag` · `version` · link to **Hypothesis** (§5.9). Outcomes attribute to experiment; never merge across laboratories.

### LI.0a.6 — Atlas IQ

Per-laboratory axes (hide below sample gate): Research · Decision · Risk · Execution · Learning · Calibration · Evidence quality. Meta rollup **does not** average win-rates. Start collecting **thin IQ proxies early** (even before full dashboard) — see phase order §9.

### LI.0a.7 — Resource-aware cadence

Observation / mail / deep research budgets ask Host Guard. Example: requested 1000 intraday obs → reduced with journaled `host_guard`. Honesty &gt; coverage theater.

### LI.0a.8 — Research evolution (versioned dossiers)

Immutable Research v1, v2, v3… + diff summary; packets cite `research_version`.

### LI.0a.9 — Hypothesis Learning (**scientific learning**)

Extend the chain:

```
Hypothesis  →  Research  →  Decision  →  Outcome  →  Hypothesis verdict  →  Learning
```

Store durable **Hypothesis** records, e.g.:

> “Lower PE stocks outperform during falling interest rates.”

Fields (v1): `hypothesis_id`, statement, domain tags (valuation/macro/…), `laboratory_id` optional (null = world-level), linked experiments/decisions, created_at, status.

**Verdicts (after enough evidence, gated):**  
`supported` · `partially_supported` · `rejected` · `inconclusive` · `expired`

This is more valuable than “Bought TCS / made money.” Atlas learns **which beliefs about the world were wrong.**

Hypotheses with `transfer_class=world` may inform other laboratories; strategy hypotheses stay lab-scoped.

### LI.0a.10 — Failure taxonomy (one root cause)

Every materially bad outcome (losing trade, rejected thesis, failed experiment, missed opportunity with large adverse move) **must** carry a primary **root_cause** (exactly one), optional secondary tags.

| Root cause | Meaning |
|------------|---------|
| `research_failure` | Thesis / business understanding wrong |
| `evidence_failure` | Missing, stale, or conflicted evidence used as if solid |
| `execution_failure` | Fill, timing, session, sizing mechanics |
| `portfolio_failure` | Concentration, trim, cash, correlation |
| `market_regime_failure` | Edge failed in this regime (or regime mislabeled) |
| `risk_failure` | Stops, margin, overnight, lot |
| `psychological_policy_failure` | Process proxies: FOMO, plan violation, revenge, overconfidence |
| `resource_limitation` | Host Guard / cadence / capability starved the decision |
| `data_unavailable` | Feed / bar / fundamentals gap |
| `provider_conflict` | Evidence tiers disagreed; wrong tier trusted |

Attribution / evening mail: prefer `Root cause: evidence_failure` over only `Loss −₹200`.

### LI.0a.11 — Long-term evolution memory

Atlas remembers **its own becoming**, not only research:

```
2026-08  Research IQ 61
2026-09  Research IQ 68  · reason: evidence tiers + provider manager
2026-10  Research IQ 74  · reason: confidence calibration improved
```

Store append-only **Evolution Events**: `{at, axis, from, to, reason, phase_id, laboratory_id?}`.  
Feeds Learning Intelligence yearly “how Atlas got smarter” narratives. Distinct from Research Versions (company understanding) and Hypothesis verdicts (world beliefs).

---

## 6. Learning Intelligence (capability, not OS)

**Asks:** What did I become better at?  
**Atlas IQ:** Where do I stand?  
**Evolution memory:** How did I change over years?  
**Hypothesis layer:** Which beliefs survived contact with reality?

Uses DI.6 proposals + D6; deepens skill axes, transfer usefulness, failure-cause histograms, dataset quality readiness, resource-throttled honesty.

---

## 7. Neural nets — quality-gated; architecture shape

**Enable training only when all are true:**

1. Enough closed **attributable decisions** (not fills alone) — gates per `(laboratory_id, strategy_tag)`.  
2. High feature completeness (business, valuation, technicals, macro/regime, portfolio, outcomes).  
3. Evidence provenance on valuation fields used.  
4. Multiple regimes in the closed set.  
5. Sample gates met per lab + strategy.  
6. Failure taxonomy + hypothesis linkage present on a minimum fraction of closed rows (quality signal).

Smaller high-quality dataset ≻ large incomplete set.  
`live_nn_trading=False` until lab-scoped walk-forward beats rules.

**Future AtlasNet shape (design only — matches controlled transfer):**

```
Shared World Encoder
        ↓
  Business · Sector · Macro · Management   (reusable)
        ↓
Laboratory Heads
  Swing · Intraday · F&O · ETF · …         (not reusable across labs)
        ↓
Meta Decision                              (combines; never trains on mixed-lab return labels)
```

Business knowledge reusable; trading behavior not.  
**Reject for now:** RL, LLM fine-tuning, deep-learning live loops.

---

## 8. Implementation phases

> Code only after 🔒. Prefer thin vertical slices; measure early.

### LI.0 — Lock & inventory

Operator ✅ §12; inventory portfolio/mail/DI/Resource hooks; map portfolio_key → laboratory_id.

### LI.0a — Infrastructure contracts

Schema/API sketches for: laboratory container, transfer bus, calibration, regime, opportunities, aging, experiments, hypotheses, failure taxonomy, Atlas IQ proxies, evolution events, resource cadence, research versions.  
Not one mega-sprint — but **not TBD**.

### LI.1a — Laboratory identity, isolation, ledger separation

✅ **Shipped 2026-08-07**

- `laboratory_id` 1:1 alias of `portfolio_key` — `atlas/investment/laboratory.py`  
- Registry + `create_laboratory()`; packets stamp `laboratory_id`  
- Thesis priors path `…/<program>/lab_<id>/priors.json`  
- `classify_exits_by_strategy` / `refuse_pooled_edge_metrics` fail closed on mix  
- Tests: `tests/test_laboratory_li1a.py`  

**Done when:** two laboratories run same day; stats cannot mix; hermetic isolation tests green. ✅

### LI.1b — Personality, capital flows, per-lab communications

✅ **Shipped 2026-08-08**

- Laboratory personality presets (`swing` / `intraday` / `futures` / `options`) via `create_laboratory(..., personality_kind=…)`  
- Per-lab morning / evening / trade mail subjects + **per-lab** sent-flag dedup (`lab|date`)  
- Fill emails stamp `laboratory_id`  
- Deposit/withdraw remain on `/v1/market/portfolios/{id}/…` (lab id = portfolio_key)  
- Outage resume: `POST /v1/market/laboratories/{id}/resume` — mark ledger, never invent fills  
- Tests: `tests/test_laboratory_li1b.py`  

**Done when:** operator can fund/withdraw and receive lab-labeled mail for two labs. ✅ (mail subjects + dedup; deposit API pre-existing)

### LI.2 — Provider Manager + Yahoo fundamentals

✅ **Shipped 2026-08-08**

- Evidence Value + Provider Manager (`atlas/investment/evidence_providers.py`)  
- Yahoo quoteSummary provider, medium confidence (`yahoo_fundamentals.py`) — no yfinance dep  
- Store keeps multi-provider history; reconcile prefers verified/high; &gt;15% gap → `*_conflict` (never blend)  
- `POST /v1/market/fundamentals/yahoo-enrich` · GET fundamentals `coverage.by_provider`  
- Packets surface `pe_conflict` etc. · evening shows PE by provider  
- Tests: `tests/test_laboratory_li2_providers.py`  

### LI.3a — Partial observation density (resource-aware) ✅

- Quiet books get `mark_snapshot` observations (LI.3a density) via `MarketObserverWorker` v4  
- Host Guard cadence stub (`observation_cadence.py`) — reduced/zero mark budget under pressure  
- `complete_revisit` always mirrors JSON so evening `pending/done` matches Postgres drain  
- Bootstrap wires `host_guard` into Market Observer  
- Tests: `tests/test_laboratory_li3a_observations.py`

### LI.5a — Partial Learning Intelligence / Atlas IQ (early measurement) ✅

- `learning_intelligence.py` — thin Atlas IQ axes + append-only evolution events  
- Attributions accept `failure_cause` (LI.0a.10 taxonomy; aliases normalized)  
- `GET /v1/market/learning-intelligence` · DI dashboards + evening “learned today” section  
- Tests: `tests/test_laboratory_li5a_learning_intelligence.py`

### LI.4 — DI hardening under laboratories ✅

- Sample gates per `(laboratory_id, strategy_tag, experiment_id)` — `lane_key` / display `strategy@exp`  
- Packets stamp `experiment_id` (default); attributions stamp lab + experiment  
- Replay filters (`build_replay` + `GET /v1/market/replays`) — mismatch → no invented data  
- Export quality report: regime / provenance / hypothesis link / failure_cause rates (lab-scoped)  
- APIs: `GET /v1/market/export-quality` · ml-export status includes `quality` + `closed_by_lane`  
- Tests: `tests/test_laboratory_li4_di_hardening.py`

### LI.3b — Complete observations ✅

- Opportunity tracker (`opportunity_tracker.py`) — `ignored|missed|rejected|deferred`, lab-scoped; material-move outcomes ≠ win-rate  
- Company/macro helpers: `mgmt_event`, `operating_metric`, `filing_event`, `macro_event`  
- Gov worker dual-writes macro pulse; Decision Evolution v2 injects observations into revisits  
- `what_changed` answers “new observations?” + management_note  
- APIs: `GET/POST /v1/market/opportunities`, resolve endpoint  
- Tests: `tests/test_laboratory_li3b_observations.py`

### LI.5b — Complete Learning Intelligence ✅

- Full skill-axis Atlas IQ reports (`axis_report` + failure-cause histogram)  
- Hypothesis Learning store + gated verdicts (`hypothesis_learning.py`; ≠ thesis_tracker)  
- Evolution narratives + evening/API polish (`Root cause:` on attributions)  
- Dataset quality **readiness gauge** on export-quality (`live_nn_trading` still False)  
- Packets accept `hypothesis_id`; APIs: hypotheses CRUD/verdict · richer learning-intelligence  
- Tests: `tests/test_laboratory_li5b_learning_intelligence.py`

### LI.6 — AtlasNet prep only ✅

- Quality-gated lab-partitioned export (`atlasnet_prep.py`) under `…/atlasnet_prep/lab_{id}/{day}/by_lane/`  
- Walk-forward **contract** stub (fold boundaries + rules baseline; `learned_model=None`)  
- Sample gate + LI.5b readiness required (or force_override + note)  
- `live_nn_trading=False` / `atlasnet_status=prep_only` — no training, no paper NN  
- APIs: `GET/POST /v1/market/atlasnet-prep` · ml-export may side-write partitions  
- Tests: `tests/test_laboratory_li6_atlasnet_prep.py`

---

## 9. Implementation order (amended)

```
LI.0 lock
  → LI.1a isolation
  → LI.1b personality + capital + mail
  → LI.2 providers
  → LI.3a partial observations
  → LI.5a partial Atlas IQ / evolution / failure labels   ← measure early
  → LI.4 DI hardening
  → LI.3b complete observations
  → LI.5b complete Learning Intelligence
  → LI.6 AtlasNet prep
```

LI.0a contracts land as needed inside these slices (hypothesis + failure taxonomy especially before LI.5b).

---

## 10. Non-goals

- Busy-trading / forced fills  
- Pooled win-rate across laboratories  
- Silent cross-lab cash or strategy-prior contamination  
- Screener HTML scrape; Yahoo as sole truth  
- New top-level “Learning OS”  
- RL / LLM fine-tune / DL trading before quality dataset  
- Autonomous F&O ranking in LI.1  
- Broker orders (P10)  
- Ignoring Host Guard for observation vanity  
- Further architecture rewrites after lock (use OI items)

---

## 11. Principles

1. P10 simulation only.  
2. Learning AI ≻ busy AI.  
3. **Laboratory ≻ ledger** — ledger is one subsystem.  
4. Never mix lab outcome stats / strategy priors / return labels.  
5. Controlled transfer of world knowledge only.  
6. Hypothesis learning — scientific verdicts, not only P&L.  
7. One primary failure root cause on material losses.  
8. Evolution memory of Atlas-the-product.  
9. Never invent fundamentals or regimes.  
10. Evidence tiers with provenance.  
11. Decision quality ≠ market P&L.  
12. Non-buys are decisions.  
13. Research ages and versions.  
14. Confidence calibrates to outcomes.  
15. Sample gates 30/100/300 per `(laboratory, strategy_tag)`.  
16. Resource OS binds cadence.  
17. LI proposes; playbook accepts strategy edits.  
18. No live NN until quality gates + walk-forward.  
19. Market capability — **not** a new OS.  
20. After lock: OI items, not redesign docs.

---

## 12. Operator lock checklist

| # | Question | Locked decision | ✅ |
|---|----------|-----------------|---|
| 1 | First new laboratory? | Equity Intraday, then Futures demo | 🔒 |
| 2 | Terminology | Laboratory contains ledger (not “lab = ledger”) | 🔒 |
| 3 | Intraday bars | Yahoo + session gates; no tick replay v1 | 🔒 |
| 4 | Yahoo fundamentals | Opt-in medium provider | 🔒 |
| 5 | PE conflict | &gt;15% → conflict | 🔒 |
| 6 | Hypothesis learning | World + lab-scoped; verdicts gated | 🔒 |
| 7 | Failure taxonomy | Single primary root_cause required | 🔒 |
| 8 | Evolution memory | Append-only IQ/axis history | 🔒 |
| 9 | Per-lab mail | Morning + fill + evening | 🔒 |
| 10 | Capital | Deposit/withdraw per lab ledger | 🔒 |
| 11 | Transfer bus | §3.2 | 🔒 |
| 12 | Split LI.1 | LI.1a then LI.1b | 🔒 |
| 13 | Phase order | §9 (partial LI.5 early) | 🔒 |
| 14 | AtlasNet shape | Shared world encoder → lab heads → meta | 🔒 |
| 15 | Reject RL/LLM-FT/DL now | Yes | 🔒 |
| 16 | No new OS / roadmap respect | Yes | 🔒 |
| 17 | After lock | OI items only for new ideas | 🔒 |
| 18 | Hermeticity rule (§0.2) | Every LI PR + test suite | 🔒 |
| 19 | Promote to 🔒 PLAN LOCKED | **Locked 2026-08-07** | 🔒 |

---

## 13. Status checklist

1. ✅ Busy vs learning philosophy.  
2. ✅ `OI-LI0` registered.  
3. ✅ DI successor link.  
4. ✅ v2 LI.0a base.  
5. ✅ v3 Laboratory / hypothesis / failure / evolution / AtlasNet / LI.1a/b / roadmap.  
6. ✅ Operator ✅ §12 (2026-08-07).  
7. ✅ 🔒 PLAN LOCKED.  
8. ✅ Code **LI.1a** isolation + hermetic tests (2026-08-07).  
9. ✅ Code **LI.1b** personality + per-lab mail + outage resume (2026-08-08).  
10. ✅ Code **LI.2** Provider Manager + Yahoo fundamentals (2026-08-08).  
11. ✅ Code **LI.3a** partial observations (resource-aware) (2026-08-08).  
12. ✅ Code **LI.5a** early Atlas IQ + evolution + failure labels (2026-08-08).  
13. ✅ Code **LI.4** DI hardening under laboratories (2026-08-08).  
14. ✅ Code **LI.3b** complete observations (2026-08-08).  
15. ✅ Code **LI.5b** complete Learning Intelligence (2026-08-08).  
16. ✅ Code **LI.6** AtlasNet prep only (2026-08-08).  
17. ✅ **OI-LI0 implementation track complete** (LI.1a→LI.6).  

---

## 14. Coding kickoff

**LI.1a–LI.6 ✅ — locked plan implementation complete.**

Ops: accumulate closed attributable decisions, clear readiness gates, then use
`POST /v1/market/atlasnet-prep` for lab-partitioned datasets.  
**Do not** enable live/paper NN until walk-forward `learned_beats_rules` on paper
(future work outside this locked slice). New ideas → OI items, not redesigns.

---

## Appendix A — Operator narrative map

| Statement | Home |
|-----------|------|
| Laboratories not ledgers | §3 |
| Hypothesis learning | LI.0a.9 |
| Failure taxonomy | LI.0a.10 |
| Evolution memory | LI.0a.11 |
| Shared world encoder / lab heads | §7 |
| Partial LI.5 early | §9 |
| Split LI.1a / LI.1b | §8 |
| Hermeticity PR rule | §0.2 |
| No RL/LLM-FT now | §0.1, §7, §10 |
| Protect implementation roadmap | §0.1 |
| Per-lab mail + deposit/withdraw | §3.3 |
| Overall learning correctly | §3.4 |

## Appendix B — Ops during LI.1a

1. Swing PE/FCF import still helps, or wait for LI.2.  
2. Drain Decision Evolution revisits.  
3. Do not fund F&O until LI.1a isolation lands.

## Appendix C — Review trajectory

| Pass | Notes |
|------|-------|
| v1 | Multi-lab, providers, LI, deferred NN |
| v2 | Personality, transfer, LI.0a, mail/capital, Resource OS |
| v3 | Laboratory noun, hypothesis, failure taxonomy, evolution memory, AtlasNet shape, LI.1a/b, measure-early, roadmap shield |
| **🔒** | Locked 2026-08-07 — implement; OI items for new ideas |

---

*End of locked plan — execute LI phases; do not reopen architecture.*
