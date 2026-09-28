# Atlas Feature & Experiment Laboratory

> **Status:** 🔒 **OPERATOR-LOCKED** 2026-09-03 · Amendment A · **Amendment B** · **Amendment C** (sockets / work pool) · **Amendment D** (alive+constrained+conservative; do not loosen gates; scheduler churn = burst OI)  
> **Date:** 2026-09-03 (rev 5) · C (`fel_experiment_runner` + tiny queue wrapping E001) in code 2026-09-03  
> **Codename:** `OI-FEL0` (Feature & Experiment Laboratory)  
> **Parents (do not reopen / do not fork):**  
> [`LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md`](LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md) ·  
> [`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md) ·  
> [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) ·  
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) ·  
> [`ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md`](ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md) ·  
> [`ATLAS_NOW_CLOSED_LOOP_ROADMAP.md`](ATLAS_NOW_CLOSED_LOOP_ROADMAP.md) ·  
> [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md) ·  
> [`UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md`](UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md) ·  
> [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md) ·  
> [`BELIEF_REVISION_AND_LLM_INTELLIGENCE_DISCUSSION.md`](BELIEF_REVISION_AND_LLM_INTELLIGENCE_DISCUSSION.md)  
> **Connect, do not rebuild:** `bar_store` · ranking / E[R] · DI packets · LI laboratories · `hypothesis_learning` · Belief Engine · Experience OS · Decision Genealogy · Learning Intelligence · `curiosity` · Cognitive Core · `ml_export` / AtlasNet **prep** · `evidence_lineage` · `evidence_completeness` · Next-₹1 · Learning Auditor · `OI-EXP-LANE0` · `OI-HIST-OPP0`  
> **Does not reopen:** SMA/RSI Strategy V1 as live **control** · silent strategy mutation · AtlasNet live NN / `live_nn_trading` · adding capital · SELF0 Phase 5 · AGENT-1 freeze · LangChain-as-brain · MCP-as-intelligence · LLM → BUY/SELL · RL on raw prices  
> **Unit of truth:** a **belief about a relationship** became better supported or weaker under controlled evidence — not model accuracy, not a universal metric list, not “the LLM got better at trading”

---

## 0. Locked north star

```text
Atlas is a general learning system.
Trading is currently its richest laboratory.
FEL is the quantitative scientific instrument.

Domain-specific = laboratory + evidence.
The learning architecture is not finance-shaped.

Not: a trading AI we gradually sprinkle intelligence onto.
Not: add ML / RL / LangChain / MCP / PyTorch as the product.
Not: finish every Open Item before FEL.
```

Those are **mechanisms**. The objective is:

> Atlas observes the world, forms hypotheses, experiments, learns from outcomes, uses its LLM to reason and research, discovers useful representations, tests strategies, and gradually becomes better — while remaining incapable of fooling itself or silently taking control.

**Being able to do something ≠ being authorized to do it.**

That distinction is the whole plan.

---

## 1. Locked operator decisions (2026-09-03)

| # | Decision | Lock |
|---|---------|------|
| D1 | Project goal is a **learning agent**, not an ML trading model | 🔒 |
| D2 | **Architecture now** for LLM / features / ML / PyTorch / backtest / RL / tools — **authority later** | 🔒 |
| D3 | Curiosity → hypothesis → FEL → Auditor → new belief → new curiosity is **first-class** | 🔒 |
| D4 | Five roles: Observer · Scientist · Experimentalist · Strategist · Learner | 🔒 |
| D5 | Plugin seam is the engineering lock. **OLS vs Random Forest is only an example** of “add a method without rewriting the loop.” First *real* plugins wrap **existing** Atlas methods (`rules_sma_rsi`, `er_prototype_v1`, `ranking_v1`). A second plugin (fake in tests, then any learned method) proves the seam. | 🔒 |
| D6 | Live paper **control** stays SMA/RSI V1 until a challenger earns Level 10 | 🔒 |
| D7 | LLM never BUY/SELL. Promotion, completeness, and fills stay deterministic | 🔒 |
| D8 | FEL is the **quantitative arm** of existing learning (hypotheses, beliefs, experiences, genealogy, Auditor) — not a parallel ML product | 🔒 |
| D9 | Every new capability starts in observation / research / challenger mode | 🔒 |
| D10 | First code: FEL.0–3 (contracts, feature registry + genealogy, PIT, runner). **Not** sklearn/torch/MCP. Curiosity→LLM loop is **after** one experiment | 🔒 |
| D11 | Modest first universe (`india_equity_learner` daily bars); expand when leakage tests are green | 🔒 |
| D12 | Optional extras (`[ml]`, later `[torch]`) — Atlas **boots without them**; missing plugin → `blocked_unavailable`, never silent substitute | 🔒 |
| D13 | **Socket now, appliance later.** Reserve `ModelPlugin` ids (`xgboost`, `torch_mlp`, `torch_sequence`, `rl_policy`) with `available()=False` in FEL.0. Do **not** implement sklearn/torch/RL/MCP/LangChain intelligence until one honest experiment exists | 🔒 |
| D19 | FEL is the **direction**. Open Items is the **work pool**. Interrupted sessions: inspect → **one** finishable task → leave Atlas better. Integrity that can poison evidence still beats UI | 🔒 |
| D14 | Trading is the current lab; same five roles should later serve engineering / research / career / ops | 🔒 |
| D15 | Work kinds: **correctness that can poison evidence** → **learning loop** → intelligence extras → operator convenience. P0 ≠ work today. | 🔒 |
| D16 | First success = **one** end-to-end scientific experiment (not 100 models). Named: volume acceleration vs existing mom/RS for `buy_name`. Mission class: `OI-HIST-OPP0` question — not a Bosch detector. | 🔒 |
| D17 | Learning unit = **belief revision from controlled tests**, not “RF accuracy > OLS” | 🔒 |
| D18 | Feature registry is **scientific memory** (why the feature exists) — connect genealogy / hypotheses / Auditor; no new system | 🔒 |
| D20 | **Do not loosen** thesis / completeness / concentration / lab-isolation / switch-cost gates to make Atlas “look active.” No new buys ≠ idle | 🔒 |
| D21 | Operational reading: Atlas is **alive, constrained, and currently conservative** — not dead | 🔒 |
| D22 | `TaskCompleted` ~1000/min is **observability integrity** (`OI-SCHED-CHURN0`): not a FEL blocker, not a trading bug. Preferred next **burst** if still this noisy; if larger than one session, stop and take FEL.0 | 🔒 |

---

## 2. Capability vs authority

Do **not** read the build order as “wait six months before Atlas may have an LLM loop, a PyTorch slot, or an RL environment.”

Read it as: **give every capability a place in the architecture now; unlock what it is allowed to *do* only with evidence.**

**Socket vs appliance:** registering `torch_mlp` with `available()=False` is architecture. Installing PyTorch and training a net is an appliance. FEL.0 includes the sockets. Appliances wait for a scientific reason.

FEL is the north-star **direction**. `OPEN_ITEMS.md` is the **available work pool** for interrupted time — not a competing backlog to finish before FEL, and not frozen while FEL exists. A 45-minute session may close a small integrity bug **or** land FEL.0. A convenient UI tweak may not displace either.

**Session protocol** (when the operator has 30–90 minutes):

```text
1. Inspect: OPEN_ITEMS ACTIVE NOW · live labs · tests/logs since last session
2. Choose ONE task (not five)
3. Finish it (fix+test+update the registry row)
4. Leave Atlas better
```

Ask, in order: anything poisoning evidence? a small Open Item we can actually close? the smallest FEL slice that advances the loop? Can we finish one thing?

**Do not** auto-assign “next, FEL.0” when a burst can close poisoning or a finite OI (D22). **Do not** chain FEL.0→…→PyTorch in one sitting. Stop after **one** finished unit.

Do **not** pretend Atlas is a full-time software project. Do **not** exclusive-lock months for FEL while ignoring a live F&O contamination. Do **not** finish every P0 before FEL.0.

---

## 1b. Live operating interpretation (locked 2026-09-03 — Amendment D)

Evidence day: NSE **2026-09-03** RTH. Zerodha READY. Workers ticking. Hourly/KPI jobs running.

**“No new buys” is not evidence that Atlas is idle.**

| Lab | What happened | Reading |
|-----|----------------|---------|
| Swing | Cash. WELCORP technical BUY + Next-₹1 DEPLOY, but thesis **WATCH** and completeness **NOT_EVALUABLE** (PE/FCF/MoS). Further ticks `mark_only` (same daily bar). | Correct gating |
| Intraday | CYIENT bought then held; no add (`concentration`); IDEA `thesis_watch_insufficient`; WELCORP switch `switch_blocked_costs`. | Correct constraints |
| F&O | NIFTY exited; cash; `fno_no_cash_alts` / lab-instrument reject of cash names. | Isolation working |
| Same bar | `mark_only` | Does not invent a new decision |
| Scheduler | ~1000 `TaskCompleted`/min, ~35% CPU, paper ticks 1–2/min | Real **observability** issue — not inactivity |

The swing path is the FEL philosophy in production:

```text
Technical BUY exists
  + Next-₹1 may propose DEPLOY
  + thesis WATCH / completeness NOT_EVALUABLE
  → cannot authorize the fill
```

Estimates and proposals do **not** become actions because a rule liked them (D7). Loosening WATCH/MoS/completeness to generate activity is **going backwards** (D20).

Maturity (honest):

```text
OBSERVE ✅ → CONSTRAIN ✅ → DECIDE ✅ → OUTCOME ✅
  → LEARN 🟡 → EXPERIMENT 🟡 (FEL.0–3 not in code)
```

The missing piece is not “more AI.” It is the scientific experiment that can test a belief, record evidence, revise the belief, and ask the next question.

**Preferred next burst (if churn still present):** `OI-SCHED-CHURN0` — identify duplicate/unnecessary `TaskCompleted` emissions → tests → confirm log/CPU drop → update Open Items. If it is not a burst-sized fix, **stop** and land FEL.0 instead. Do not start another architecture document. Do not install PyTorch/RL/MCP.

| Capability | Atlas can have now | Authority initially |
|------------|--------------------|---------------------|
| RAG | Yes | Research / knowledge |
| LLM | Yes | Hypothesis / reasoning / interpretation |
| Feature engineering | Build now | Candidate generation / testing |
| Learned models (any `ModelPlugin`) | Seam now; first implementations when useful | Experimental only |
| PyTorch | **Interface now** (`ModelPlugin` family reserved) | Experimental model — no live NN |
| LLM hypothesis generation | Wire now (into FEL candidates) | Candidate only — never auto-promote |
| Backtesting | Build now | Research / measure |
| RL environment | Design + grow with the backtester | Research |
| RL policy | Later implementation | Research until Level 10 |
| MCP | Introduce where it simplifies tool access | Tool access — not intelligence |
| LangChain | Introduce where it reduces LLM-workflow glue | Orchestration — not the brain |
| Paper challenger | Existing `OI-EXP-LANE0` | Measure-only |
| Live V1 | Existing | SMA/RSI control |
| Autonomous BUY/SELL via LLM | **Never** | Deterministic decision engine only |

Phasing below is **authority and implementation density**, not “the interface does not exist yet.”

---

## 3. The agentic loop (what we are actually building)

```text
             ATLAS
               │
       ┌───────┴────────┐
       │                │
   UNDERSTAND        LEARN
       │                │
   LLM + RAG       EXPERIMENTS
       │                │
   research        features
   evidence        models
   reasoning       strategies
       │                │
       └───────┬────────┘
               ↓
          DECISION
               ↓
          ACTION / TEST
               ↓
            OUTCOME
               ↓
          REFLECTION
               ↓
        BELIEF REVISION
               ↓
        NEW HYPOTHESIS
               ↺
```

Atlas is an agent **because this loop closes**, not because it uses an LLM.

### 3.1 Curiosity is first-class (not a later phase)

Connect existing `OI-CURIOSITY0` (unknowns → research queue) to FEL. Curiosity today mostly fetches **missing data**. FEL adds: *what don’t I understand about this decision, and what should I test?*

```text
             ┌──────────────────────────┐
             │          ATLAS           │
             │ "What don't I understand?"│
             └────────────┬─────────────┘
                          ↓
                     CURIOSITY
                          ↓
                    HYPOTHESIS
                          ↓
                   RESEARCH / RAG
                          ↓
                    LLM REASONING
                          ↓
                  FEATURE PROPOSAL
                          ↓
                 EXPERIMENT PROPOSAL
                          ↓
                   FEL EXPERIMENT LAB
                          ↓
                   WALK-FORWARD TEST
                          │
              ┌───────────┴───────────┐
              ↓                       ↓
           FAILED                   WORKED
              ↓                       ↓
          LEARN WHY             INVESTIGATE
                                    ↓
                              MORE TESTING
                                    ↓
                              CONDITIONAL?
                                    ↓
                              PROMOTE?
                                    ↓
                             PAPER CHALLENGER
                                    ↓
                               REAL OUTCOME
                                    ↓
                           AUDITOR / LEARNING
                                    ↓
                               NEW BELIEF
                                    ↓
                               NEW CURIOSITY
```

LLM generates hypotheses and candidate features. FEL tests them. The evaluator decides whether they work. The feature registry remembers. The **Auditor** decides whether Atlas *learned*. Belief Engine / Experience OS store the revision. That is already Atlas’s architecture — FEL must plug into it, not bypass it.

### 3.2 Atlas generates its own work

Success looks like an overnight report, not “Reliance looks bullish”:

```text
I ran 17 experiments.
9 rejected · 5 inconclusive · 3 survived the first validation gate.

Volume acceleration appears useful for buy_name in high-momentum regimes,
not for sell_incumbent.

Ranking quality adds little after relative-strength features.

Two new candidate experiments queued.
Exit hypothesis: insufficient samples — will not promote.
```

That is the operator-facing product of the agent loop. Throughput (LLM calls, ticks) remains a weak metric.

---

## 4. Five learning roles

FEL is **role 3**. The agent is all five.

### 4.1 Observer

```text
World → Data → Observations → Knowledge
```

Collect broadly. Do not require usefulness in advance. Price, volume, volatility, momentum, RS, sector, index, fundamentals, valuation, earnings, news, events, macro, breadth, portfolio state, previous decisions, confidence, outcomes, …

Existing: `bar_store`, fundamentals, world evidence, packets, observations, WSO. **Preserve the instinct. Do not dump everything into one model.**

### 4.2 Scientist (LLM + RAG)

Asks: why did this happen? what might explain it? what should we test? what feature represents this concept?

Produces a **structured proposal**, then **leaves the numerical loop**:

```text
hypothesis_id
feature: volume_acceleration × sector_relative_strength
target: forward_return_5d
decision_type: buy_name
reason: …
```

Never: `LLM → BUY RELIANCE`.

Existing: Cognitive Core, scientist packets, IRA, RAG. Wire **output schema → FEL candidate**.

### 4.3 Experimentalist (FEL)

Asks: does the hypothesis survive reality? Not: does it sound intelligent?

```text
feature generation → dataset → model plugin → walk-forward
  → baseline comparison → costs → regime → stability → store
```

Lineage (required):

```text
observation → feature → dataset → model artifact → experiment
  → (optional) challenger → decision → outcome
```

Without this, “I learned that volume is useful” is folklore.

### 4.4 Strategist (predictions in, decisions out)

Models produce **estimates**, not orders:

```text
expected_return
probability_positive
expected_volatility
confidence
```

The deterministic Decision Engine / lab contracts / Next-₹1 admit or reject.

Plugin registry is how Strategist stays swappable: callers use `ModelPlugin.fit/predict`. They never import sklearn / torch / an RL library directly.

**OLS vs Random Forest** in this document means: *two methods behind one contract.* It is **not** a commitment that those two are the product, nor that RF must ship in the first PR. XGBoost, a PyTorch MLP, a sequence model, an ensemble, later an RL policy — same contract, new file, same runner.

Existing formulas wrap as the first plugins so the Strategist is not empty: `rules_sma_rsi`, `er_prototype_v1`, `ranking_v1`.

### 4.5 Learner

```text
I believed X → I tested X → X worked / failed
  → I understand why → belief changed
  → future experiments account for this
```

**Not learning:** `RF accuracy 61% > OLS`. That is a diagnostic number.

**Learning:**

```text
BELIEF   "Volume acceleration helps identify opportunities."
  →  TEST (N experiments, named decision_type, same folds/costs)
  →  RESULT  useful for buy_name in momentum regime;
             not useful for sell_incumbent
  →  REVISION  "Conditionally useful for opportunity discovery, not exits."
  →  NEXT     "Does it add information after sector-relative strength?"
```

Existing: Belief Engine, Experience OS, Decision Genealogy, Learning Auditor, Hypothesis Learning, Learning Intelligence.

FEL writes **experimental facts** into those systems. It does not become a second memory.

Auditor remains the **instrument** of learning proof (`stored ≠ observed ≠ understood ≠ predicted ≠ learned ≠ improved`). FEL metrics are not L5 learning records by themselves.

---

## 5. Autonomy ladder (capability vs permission)

| Level | Atlas may | Authority |
|-------|-----------|-----------|
| **0** | Observe | On |
| **1** | Analyze (deterministic summaries) | On |
| **2** | Generate hypotheses (LLM) | Advice / candidate |
| **3** | Design experiments | Candidate records |
| **4** | Run experiments (FEL BATCH) | Offline |
| **5** | Evaluate (walk-forward, costs, baseline) | Research |
| **6** | Form / revise beliefs | Gated (existing BRE sample rules) |
| **7** | Propose improved models | Candidate artifacts |
| **8** | Paper-test challengers | Measure-only (`OI-EXP-LANE0`) |
| **9** | Demonstrate persistent improvement | Auditor + out-of-sample |
| **10** | Operator-authorized deployment | Human unlock — still not LLM orders |

Climbing a level requires evidence, not a library install. Live V1 stays at “control” until Level 10.

---

## 6. Where Atlas actually is (honest)

| Layer | Today | Gap |
|-------|-------|-----|
| Observer | Bars, fundamentals, world evidence, packets | No feature store; usefulness untested |
| Scientist | Cognitive Core, RAG, curiosity → IRA data gaps | Hypotheses not FEL-shaped; curiosity ≠ experiment design |
| Experimentalist | `experiment_id` **stamp**; AtlasNet walk-forward **stub** | No PIT matrix, no experiment runner, no promotion machine |
| Strategist | Fixed ranking + E[R] prototype + SMA/RSI | Not plugins; cannot add a method without a rewrite |
| Learner | Beliefs, experiences, Auditor, genealogy | Not fed by quantitative experiment results |
| Control | SMA/RSI V1 | Must stay until Level 10 |
| Isolation | Labs + lane `(lab, strategy_tag, experiment_id)` | FEL inherits this — no pooled labels |

FEL is a **Market Intelligence capability** (`atlas/investment/fel/`). Not a new OS. Do not overload `atlas/learning/` (Experience OS component keys).

---

## 7. Decisions, not a universal metric list

Give Atlas a large **observation space**. Do not hand it “the 37 metrics.”

The agent asks: *what information might explain this decision?*

| Decision type | Example | Typical targets |
|---------------|---------|-----------------|
| `buy_name` | Buy this stock? | P(forward return > cost), rank |
| `size_name` | How much? | E[R], vol, P(drawdown) |
| `sell_incumbent` | Exit? | thesis-failure vs temporary drawdown |
| `switch` | Replace incumbent? | advantage after costs (UTS) |
| `hold_cash` | Next ₹1 is cash? | E[R] vs cash, completeness |
| `event_react` | Did news/earnings change the thesis? | residual vs peers |

A feature useful for `buy_name` in a bull regime may be useless for `sell_incumbent`. Registry keys **decision_type** + regime, not a global scoreboard.

Collection philosophy (lock):

```text
A. Collect everything → feed everything into the model.     ❌
B. Collect broadly → store cheaply → engineer selectively
   → test usefulness → promote what works.                  ✅
```

---

## 8. Plugin architecture (engineering lock)

Pattern Atlas already uses: `MarketFeedAdapter`, `OCREngine`, `SearchProvider`, `InstrumentPack`, `DecisionRule`. FEL copies **Protocol + Registry + honest `available()`** — not kernel plugins, not LangChain tools as the model layer.

OLS vs Random Forest was the **teaching example**: add a method, keep the previous one, runner unchanged. The lock is the **seam**, not those two algorithms.

### 8.1 Four independent registries

```text
FeatureComputer     ModelPlugin         EvaluatorPlugin     TargetSpec
     │                   │                    │                 │
  return_5d         rules_sma_rsi        walk_forward      fwd_ret_5d
  vol_20d           er_prototype_v1      expanding         rank_in_universe
  rs_vs_nifty       ranking_v1           purged_cv         p_drawdown
  volume_z × rs     <any learned plugin>                   decision_quality
                    (ols, rf, xgb, torch, rl_policy, …)
```

Adding a model never edits the feature engine. Adding a feature never edits a model. Switching the **active** predictor is a **promotion record**, not a code fork.

### 8.2 ModelPlugin contract

```text
ModelPlugin
  plugin_id, version
  tasks: {regression, classification, ranking, probability}  # RL policy later as its own task
  available() -> bool
  fit(matrix, target, params) -> FittedArtifact
  predict(artifact, matrix) -> Predictions
  explain(...) -> optional importances / coefficients
```

**Hard rules:**

1. Identity = `plugin_id` + version + params hash — not “whatever is imported.”
2. **No silent substitution.** Requested plugin unavailable → `blocked_unavailable`. Never run plugin B and stamp plugin A.
3. **Plugins are never deleted** to make room for a new one. Retired = status, still replayable.
4. **Day-one plugins wrap existing Atlas methods** so the registry is real before any new estimator lands.
5. **A second plugin** (hermetic fake in tests, then a learned method when we choose one) must register **without** editing `ExperimentRunner` / Next-₹1 / paper_trading.
6. **Comparison is mandatory.** A new method records a baseline on the **same** folds.
7. Live book reads a **promoted artifact id**, not a global `model: <library>` config.

Reserved `plugin_id` families (implement when useful; register stubs/`available()=False` if the extra is missing):

```text
ModelPlugin
  ├── rules_sma_rsi          # live control — wrap
  ├── er_prototype_v1        # wrap
  ├── ranking_v1             # wrap
  ├── ols                    # example learned linear
  ├── random_forest          # example tree ensemble
  ├── xgboost                # later
  ├── torch_mlp              # later — interface reserved now
  ├── torch_sequence         # later
  └── rl_policy              # later — allocator, not price
```

Callers do not care which technology produced the artifact. Six months later Atlas may honestly say: linear was enough; trees helped; the relationship is nonlinear; a temporal model helped. That is the point of the seam.

### 8.3 FeatureComputer / Evaluator

```text
FeatureComputer
  feature_id, version, sources, formula, timeframe, lookback
  availability_time rule
  compute(pit_context) -> value | missing
```

Missing stays missing (never invent 0). Seed computers wrap `sma` / `rsi` / ranking components.

LLM may propose a computer → `status=candidate` → test. Proposal ≠ promotion.

**Evaluator default:** walk-forward (not 2015–2026 one-shot). Costs + slippage are evaluator inputs. Other evaluators are additional plugins; walk-forward cannot be removed.

### 8.4 Optional dependencies

| Extra | Role | Boot |
|-------|------|------|
| *(core)* | Contracts, wraps, stdlib features, runner | Always |
| `[ml]` | sklearn / similar — **when we add that plugin** | `available()=False` if missing |
| `[torch]` | PyTorch plugins | Same |

Do not put sklearn or torch in core `dependencies`. Heavy FEL work is **BATCH**, Host Guard aware, **yields during NSE RTH**.

---

## 9. Registries, dataset, lineage

### 9.1 Feature registry

`feature_id` / version / source / formula / timeframe / `availability_time` / data_quality / usage_count / predictive_score (task-specific) / stability / correlation / importance (from a **named** artifact) / last_evaluated / status (`registered` · `candidate` · `promoted` · `conditional` · `retired` · `deceived`) / lineage (human, `hypothesis_id`, wrap).

“Worked 2020–2022, then died” is `stability` / `conditional` — not a deleted row.

### 9.2 Experiment registry

Every run is recorded. Fields: `experiment_id` (not live stamp `default`) · `hypothesis_id` · `decision_type` · `laboratory_id` · universe / `dataset_id` · `feature_ids` · `model_plugin_id` + version + params · **required** `baseline_plugin_id` · evaluator · folds · costs · metrics vs baseline · result (`improve` · `no_significant` · `worse` · `invalid` · `blocked_unavailable`) · promotion (`never` · `candidate` · `paper_challenger` · **not** `live_control` without Level 10).

Lane key stays `(laboratory_id, strategy_tag, experiment_id)`. Packet `experiment_id="default"` remains **V1 control**. FEL ids never overwrite it.

### 9.3 Point-in-time dataset

as-of × symbol × features + target. Only `availability_time` ≤ as-of. Same bars Atlas already trusts. Universe as-of that date. Decision/confidence features only if knowable then. jsonl under `data_dir` first; no new DB in the first slices.

### 9.4 Lineage (pipeline)

Extend `evidence_lineage` / `decision_genealogy`. A later session must answer: why this buy — which features, plugin, folds, costs?

```text
observation → feature → dataset → model → experiment
  → (optional) challenger → decision → outcome
```

### 9.5 Feature genealogy (scientific memory — connect, do not rebuild)

The feature registry must also answer: **why does this feature exist?**

Example (schema, not a new store):

```text
feature: volume_acceleration_20d
origin: hypothesis H-0241
scientist_reason: "Unusual participation may confirm price movement"
source_concepts: volume, momentum, liquidity
derived_from: volume_5d, volume_20d
tested_for: buy_name
tested_models: <plugin_ids used — example names only>
result: useful in high-momentum regime
not_useful_for: sell_incumbent
current_status: conditional
```

Write these fields on the existing feature registry row. Link `hypothesis_id`, Experience, Auditor. **Do not** create a parallel genealogy product.

---

## 10. Anti-self-deception

10,000 features × models × windows × params will find an accident.

| Control | Rule |
|---------|------|
| Walk-forward | Required |
| Baseline | Required (V1 wrap and/or another plugin) |
| Costs | Required on economic metrics |
| Many names | No Bosch detector — winners, losers, false positives |
| Regimes | Single-regime shine → `conditional`, not promoted |
| Lab hermeticity | No pooled return labels |
| Multiple-testing | Candidates untrusted until OOS + sample gates |
| No look-ahead | `availability_time` + Auditor LOOKAHEAD |
| No live mutation | Promotion ≠ replacing V1 |
| Auditor | FEL score ≠ learning record until L5 chain |

In-sample R² / accuracy deltas are debug. They are not a promotion argument and they are not a learning record.

---

## 11. PyTorch, RL, MCP, LangChain (architecture now)

### 11.1 PyTorch

A `ModelPlugin` family for nonlinear / sequence problems — **not** “AI = PyTorch.” Reserve the interface in Phase 0 (`plugin_id` + `available()=False` stub is enough). Implement when data and a named job exist. AtlasNet `live_nn_trading=False` / LQ.9 still bind. Possible later **separate** heads (combine in the decision engine, not one soup): momentum, medium return, vol, regime, event residual.

### 11.2 RL

Learn **how to manage capital**, not tomorrow’s price.

```text
predicted opportunities → E[R] / risk / regime / portfolio state
  → RL policy → allocation (lab-contract constrained)
```

State: book, cash, positions, regime, predicted E[R]/vol, confidence, path, drawdown.  
Action: buy / sell / hold / increase / reduce.  
Reward: return − costs − drawdown / risk / turnover penalties.

The **environment** grows with the backtester (authority: research). The **policy plugin** is later. Raw-price RL is refused.

### 11.3 MCP / LangChain

Add **if** they make the agent loop better — not because they are fashionable.

LLM may eventually call: search, RAG, market data, FEL, backtester, portfolio simulator, knowledge, filesystem, research. MCP can standardize those **tools**. LangChain can orchestrate LLM workflows **if** it cuts custom glue.

Neither is Atlas’s intelligence. Decision Engine stays native and deterministic.

**Do not wait for “Phase 6” to leave a tool-shaped hole.** If a tool interface is needed in the Scientist loop, design the capability now; pick MCP or native Atlas plugins when it actually simplifies.

---

## 12. Connection to live Atlas

```text
FEL (offline / BATCH)
  → estimates + importances + experiment facts
  → Learner systems (hypothesis verdicts, beliefs, experiences, Auditor)
  → Scientist packet may include FEL summaries (advice)
  → Strategist estimates may later version E[R] as a plugin
  → Next-₹1 still fail-closed on unknown
  → fills: V1 until Level 10
```

If FEL is broken, the book still trades V1. Challenger lanes stay measure-only until operator unlock.

---

## 13. Immediate path (stop designing)

No new architecture document. This file is sufficient.

**Do not implement** PyTorch, RL, LangChain, MCP, XGBoost now. They stay reserved interfaces. Before one honest experiment they are toys.

### 13.1 Three kinds of Open Item (do not treat equally)

| Kind | Examples | Rule |
|------|----------|------|
| **A. Integrity** — can make evidence untrustworthy | STAB unclean days, F&O contamination, bar/PIT leakage, lab mix, invented learning records, silent Yahoo on live-required | Fix **only** what can poison the first experiment |
| **B. Intelligence** | FEL, HIST-OPP, hypothesis→test, model plugins, backtest | **This is the work** after A is narrow-gated |
| **C. Operator** | AGENT-1, richer UI, chat inherit densify, extra dashboards, Scale Lab theater | **Wait** |

Priority: **Correctness that can poison learning → learning loop → intelligence extras → operator convenience.**

Not: finish every P0 → every P1 → eventually FEL.

`OPEN_ITEMS.md` remains the **registry** so nothing is lost. **ACTIVE NOW** (see that file) is the roadmap. P0 does not mean “today.” AGENT-1 is P0 and **frozen**.

### 13.2 Stabilization gate (narrow)

Work only items that can **invalidate** a PIT experiment or its labels:

- session / ledger honesty that would stamp false outcomes (`OI-STAB0` to the extent it poisons closes)
- F&O / lab-contract contamination (`OI-FNO-CONTRACT` — do not mix FNO labels into the equity experiment)
- market / historical bar integrity used as-of (`OI-HIST-BARS`, `OI-MKT-COV`, data-plane freshness/provenance)
- experiment leakage / lab isolation (FEL tests themselves)
- scientist drain **only when** the Scientist is in this experiment’s path (FEL.0–3 first experiment may be **deterministic** and skip LLM)

Everything else yellow-P0 (ICR densify, Scale Lab, chat inherit, WEB-EVID polish, AGENT-1, …) is **not** a gate for FEL.0–3.

FEL.0–3 **code** can proceed in parallel with that narrow gate. The first experiment must not consume known-corrupt tapes.

### 13.3 Build FEL.0 → FEL.3, then one experiment

| Slice | What lands |
|-------|------------|
| **FEL.0** | Contracts, four registries, wraps of V1 / E[R] / ranking, seed features, reserved plugin ids `available()=False`, fake second plugin test |
| **FEL.1** | Feature registry + **feature genealogy fields** (§9.5). Broad observation space; do not discard raw data because usefulness is unknown; do not let untested info into the decision model |
| **FEL.2** | PIT dataset, leakage tests, modest universe |
| **FEL.3** | Runner, walk-forward, baseline, costs |

**First complete experiment (success test — not 100 runs):**

> Does volume acceleration add information **beyond** existing momentum / relative-strength features for `decision_type=buy_name`?

Atlas (even if the operator still kicks the runner once) must: name the hypothesis → candidate features → PIT data → baseline → candidate → walk-forward → costs → significant/stable/conditional/fail → store lineage + genealogy → tell the Scientist what happened → **next question**. Fills unchanged.

If Atlas cannot do that, more architecture is the wrong next commit.

**Mission class (not a second product):** `OI-HIST-OPP0` — “what information was actually useful in identifying future opportunities?” Winners + false positives + losers; Bosch = stress case, never a detector. Full 500–1000 multi-vintage lab is **after** the one-experiment loop works — same FEL, not a fork.

**Landed after E001 (C, not D):** tiny on-disk queue (`QUEUED → RUNNING → COMPLETED | FAILED | BLOCKED`) + BATCH worker `fel_experiment_runner`. Live 2026-09-03 14:59: worker claimed skip-complete E001 → COMPLETED (`worse`); duplicate enqueue is a no-op. Yields during NSE RTH unless the next item is a cheap skip. Host-Guard pause respected. No Redis, Celery, priority scheduler, dashboards, LLM-generated experiments, or parallel workers. Next scientific step is a **named E002 hypothesis**, not HIST-OPP at scale.

### 13.4 Then (only then)

```text
LLM hypothesis loop (FEL.4–5)  →  more experiments  →  a second ModelPlugin
  →  backtester  →  PyTorch if residuals demand it  →  RL allocator in simulator
```

A second model matters because **same dataset, target, folds, costs, evaluator — different plugin**. “Linear was enough” is a successful experiment. RF beating OLS on accuracy is not, by itself, learning (D17).

### 13.5 Later slices (unchanged ids, later authority)

FEL.4 curiosity/scientist schema · FEL.5 Learner feed · FEL.6 learned plugin · FEL.7 backtest · FEL.8–10 torch / RL / tools — **not this sprint.**

**Done (this milestone):** one honest experiment recorded with lineage, genealogy, belief-shaped result, no fill change.

---

## 14. Module layout

```text
atlas/investment/fel/
  contracts.py           # roles, decision_type, autonomy notes, Protocols
  registry.py            # feature / model / evaluator / target
  curiosity_bridge.py    # proposal schema from scientist / curiosity queue
  queue.py               # C — QUEUED → RUNNING → COMPLETED | FAILED | BLOCKED
  features/
  models/
    baselines.py         # wraps existing Atlas methods
    learned/             # optional extras; one file per plugin_id
  datasets/builder.py
  experiments/store.py
  experiments/runner.py
  experiments/dispatch.py  # C — claim one; wrap existing runners (E001)
  experiments/e001_vol_accel.py
  evaluation/walk_forward.py
  lineage.py
  promotion.py           # status only; never mutates V1
  digest.py              # overnight experiment report (not C)
```

```text
{data}/investment/fel/
  features/  datasets/  experiments/{lab}/  artifacts/{plugin_id}/  queue/
```

Worker: BATCH `fel_experiment_runner` — not in the decide tick.

---

## 15. Freeze / non-goals

| Do not | Why |
|--------|-----|
| Treat this as “add sklearn to Atlas” | Wrong goal |
| Replace SMA/RSI control without Level 10 | Science needs a control |
| LLM → BUY/SELL | Role split |
| Silent plugin substitution | Identity |
| Feed raw everything into one model | §7 |
| Raw-price RL | Wrong RL problem |
| LangChain / MCP as brain | Tools only |
| New Learning OS | Roadmap |
| Increase capital | NOW lock |
| Invent missing = 0 | Honesty |
| Pool labs | Hermeticity |
| Bosch detector | HIST-OPP |
| Claim learning from FEL counts | Auditor is the instrument |
| Delay all interfaces until a late phase | Authority ≠ existence |
| Finish every Open Item before FEL | Registry ≠ roadmap |
| Treat RF>OLS accuracy as learning | D17 |
| Implement torch / RL / LangChain / MCP before one experiment | Toys until the loop works |
| HIST-OPP as a Bosch detector or a second lab | Same FEL, later scale |
| Loosen WATCH / completeness / concentration / F&O isolation to look busy | D20 — constraints are intelligence |

---

## 16. Acceptance

**FEL.0–3:** registries, wraps, fake second plugin, no silent swap, PIT leakage test, walk-forward default, costs, lab isolation, BATCH/RTH, boot without sklearn/torch, fills unchanged.

**Milestone (the one that matters):** Atlas completes the named `buy_name` / volume-acceleration experiment (§13.3) with feature genealogy, baseline comparison, and a **belief-shaped** result (supported / weaker / conditional / insufficient sample) — not an accuracy headline. No L5 record from in-sample shine. LLM loop not required for this first run (may be operator-initiated).

**Not acceptance:** new dashboards, AGENT-1, PyTorch, MCP, a 500-name HIST-OPP product.

---

## 17. Summary

| Theme | Stance |
|-------|--------|
| Goal | General learning system; trading = current lab; FEL = instrument |
| Now | Burst: `OI-SCHED-CHURN0` if still noisy; else smallest FEL slice. Then one `buy_name` experiment |
| Not now | Torch / RL / MCP / LangChain / finish-all-P0s / **loosen gates for activity** |
| Operating | Alive, constrained, conservative — no new buys ≠ idle |
| Danger | Architecture as the project; log throughput mistaken for work |

Next burst: scheduler churn if still ~1000 `TaskCompleted`/min; otherwise FEL.0. Not another plan.
