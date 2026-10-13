# Cognitive Loop C1 — Autonomous Learning

> **Status:** ✅ **C0–C9 implemented and unit-verified 2026-10-05.** The loop ran
> end-to-end on the real 8-episode day and returned **INCONCLUSIVE** — Atlas did not
> confirm its own hunch. `validated` is **0**, which is the honest answer at this stage.
>
> **Still unverified:** everything that needs a live weekday. Write-time episode fields
> (`entry.at`, `features`, `holding_minutes`) populate for *newly written* episodes only,
> so they prove out on tomorrow's close, not retroactively. See §8 for the exact split
> between "verified now" and "verify tomorrow".
>
> **Companions:** [`2026-10-05_P1_P5_PROGRAM.md`](2026-10-05_P1_P5_PROGRAM.md) ·
> [`2026-10-05_MARKET_DAY.md`](2026-10-05_MARKET_DAY.md) ·
> [`ATLAS_MDPH_AND_LEARNING_LOOP_DISCUSSION.md`](ATLAS_MDPH_AND_LEARNING_LOOP_DISCUSSION.md) ·
> [`ATLAS_NOW_CLOSED_LOOP_ROADMAP.md`](ATLAS_NOW_CLOSED_LOOP_ROADMAP.md)
>
> **Prerequisite added 2026-10-06:** [`2026-10-06_OPERATIONAL_HEALTH_LOOP0.md`](2026-10-06_OPERATIONAL_HEALTH_LOOP0.md).
> On Oct 6, cognition had nothing to learn from because the F&O data plane failed silently
> all session. Loop 0 (O1–O5) makes that failure recover automatically, or alert the operator.

---

## 0. The one-sentence goal

Given the eight canonical F&O closed-loop episodes already on disk, Atlas should
**autonomously notice something worth asking about, state a falsifiable hypothesis,
decide whether it is worth compute, test it against independent durable data, record
SUPPORTED / REJECTED / INCONCLUSIVE, and only then produce a learning candidate** —
with live trading behaviour unchanged.

Not: another trading strategy, another indicator, another data source, another F&O
experiment, or more paper trades.

---

## 1. What is true today (verified in code and on disk)

### 1.1 Confirmed working

| Layer | State | Evidence |
|---|---|---|
| Episode closure (P1) | 🟢 | `investment/fno/closed_loop/india_fno_learner/2026-10-05.jsonl`, `pipeline_complete=true`, 8/8 |
| Experience memory | 🟢 | 8 `EXPERIENCE` + 8 `LEARNING_STORY` rows, `prediction_error.status=computed` on all eight |
| Attribution evidence | 🟢 (as evidence) | `causal_factors.status=evidence_backed`, helped/hurt/unknown + `missing_evidence` explicit |
| Operational autonomy (Loop A) | 🟢 | 24 investigations, 5 resolutions, 19 capability gaps, 5 waiting states, work continued after blockage |
| Durable daily OHLCV for the 8 underliers | 🟢 | `market/bars_health/2026-10-05.json`, `all_replayable=true` |
| Scientific infrastructure | 🟢 (exists, under-used) | FEL queue/runner/walk-forward/promotion, `l5_validation` ladder, `hypothesis_learning` store |

### 1.2 Confirmed dormant

| Layer | State | Reason |
|---|---|---|
| Hypothesis generation | 🔴 | No component turns experience clusters into candidate questions. 0 new hypotheses. |
| Hypothesis → experiment bridge | 🔴 | FEL is seeded by hard-coded ids (`E001`, paper_round_trip), never by a discovered question |
| Learning validation | 🔴 | Lessons stay PROVISIONAL; `l5_validation` ladder exists but nothing feeds it from F&O |
| Belief revision | 🔴 | `belief_update=unchanged` ×8; 0 WSO revisions |
| Reflection / global mind | 🔴 | No reflection run; `bre5_global_mind` ok=0 / fail=3 |
| Cross-domain integration | 🔴 | Kernel investigations and F&O episodes are two unconnected streams |

### 1.3 Two findings that change what we do first

**Finding A — `chain_complete=0/5` is not only a stale snapshot.** There are two
code-level causes that will keep it at zero even after the P1 rebuild:

1. `atlas/investment/learning_objects.py::attribution_required_for_close` returns
   `True` only for intraday labs or `strategy_tag ∈ {exit, sell, reduce, eod_flatten}`.
   The F&O session-flat close uses the Lab v1 experiment-close reason, so
   `attribution.required=False` → `satisfied=False`.
2. `atlas/investment/learning_audit.py::classify_learning_level` promotes to **L2**
   when attribution status is in `{unknown_explicit, attributed, partial}` — the
   **strongest** status, `evidence_backed`, is missing from that set. And
   `chain_complete = bool(attr.satisfied and lesson)` requires `satisfied`.

So the F&O episodes are currently classified *below* episodes with weaker attribution.
That is a scoring bug, not a data shortage.

**Finding B — tonight's "timely" evening path now skips the whole nightly cognitive
block.** `preview_evening(timely=True)` (which `send_evening` defaults to) skips
BRE.1 WSO sync, BRE.2 belief revision, BRE.5 global mind, MEM.1 memory distill,
nightly reflection, CWS, and curiosity drain. That was the right fix for mail
punctuality, but it means **reflection and belief revision would now never run**.
Nightly cognition must be moved **off** the mail path into its own tick — not
re-attached to the email.

---

## 2. Architecture: two loops, one bridge

### Loop A — Operational Agent (working)

```text
uncertainty → investigate → acquire → verify → resolve | capability_gap → wait/retry
```

### Loop B — Cognitive Scientist (to build)

```text
observation → pattern/question → hypothesis → prediction → experiment
    → outcome → attribution → learning candidate → validation
    → belief revision → next question
```

### The bridge (the actual missing piece)

```text
closed-loop episodes (P1)
        ↓                        C3  Pattern Detector  (deterministic)
   candidate pattern
        ↓                        C3  Hypothesis Engine (deterministic frame + optional LLM wording)
   structured hypothesis
        ↓                        C4  Agent Kernel: worth compute?
   SCIENTIFIC_EXPERIMENT task
        ↓                        C5  FEL queue → runner → walk-forward
   experiment result
        ↓                        C6  l5_validation ladder
   learning candidate → VALIDATED | FALSIFIED | INCONCLUSIVE
        ↓                        C7  belief version N+1 (proposal → gate)
   belief revision
        ↓                        C8  decision context change → next prediction
   behavioural proof
        ↓                        C9  reflection → next question
```

### Honesty hierarchy (must be preserved in every artifact)

```text
8 closed episodes → 8 learning stories → 0..N candidate patterns
  → 0..N hypotheses → experiments → 0..N learning candidates
  → 0..N validated learnings → 0..N belief revisions → behavioural change
```

Today we are at level 2–3. Nothing in this plan may skip a level.

---

## 3. Phases

Each phase lists: goal · what already exists (reuse) · changes · acceptance · non-goals.

---

### C0 — Decouple nightly cognition from the mail path

**Why first:** without this, C7/C9 can never run, and we would be tempted to undo
tonight's mail fix.

**Exists:** `belief_revision.revise_beliefs_budgeted`, `global_mind.distill_global_mind`,
`world_state.sync_open_book_wsos`, `memory_distill.run_memory_distill`,
`reasoning/reflection.run_nightly_reflection`, `cognitive_work.run_cws_pass` — all
currently only reachable from `preview_evening(timely=False)`.

**Changes:**
- New worker tick (BATCH class, after mail window) that runs the nightly cognitive
  block for each mail lab: WSO sync → BRE.2 → BRE.5 → MEM.1 → reflection → CWS.
- Persist a nightly cognition receipt: `investment/nightly_cognition/{lab}/{day}.json`
  with `ran`, `skipped_reason`, per-stage ok/fail counts.
- Evening mail **reads** that receipt (on-disk snapshot, like the RAG section) instead
  of computing it. Mail stays timely.

**Acceptance:**
- [x] Evening EOD send still completes < 20s — the digest's cognitive read measures
      **0.12 ms** per mail (receipt + cycle, both plain file reads)
- [ ] `nightly_cognition/{lab}/{day}.json` exists with `ran=true` for a weekday —
      **verify tomorrow**; needs a real post-digest tick
- [x] Evening mail reflection section is populated from the receipt, not from a live LLM
      drain — and when no receipt exists it says so ("not run yet today") rather than
      rendering an empty section

**Non-goals:** changing what reflection concludes; raising LLM concurrency.

---

### C1 — Close the P1 residual episode fields

**Goal:** an episode carries enough decision-time context to support *why*, not just *whether*.

**Exists:** `fno_lab_v1.load_entry_prediction` (has `entry_time`, `sma_margin`,
`control_action`, `er_model`), `lab_experience` L10 attach, `learning_objects.build_trading_experience`.

**Changes (three narrow fixes):**

| Gap | Fix | File |
|---|---|---|
| `entry.at = null` | On session-flat close, stamp `entry.at` from the persisted prediction's `entry_time`; derive `holding_minutes` | `workers/paper_trading.py` flatten path → experience build |
| `features = {}` | Pass the control indicators already known at decide time (`sma_fast`, `sma_slow`, `sma_margin`, `rsi` when present) into `features`; absent values stay **UNKNOWN**, never 0 | `workers/paper_trading.py`, `learning_objects.build_trading_experience` |
| `attribution.satisfied = false` | Recognize the Lab v1 experiment-close tag in `attribution_required_for_close`; add `evidence_backed` to the L2 status set in `classify_learning_level` | `investment/learning_objects.py`, `investment/learning_audit.py` |

**Acceptance (rerun Learning Auditor after fixes):**
- [ ] 8/8 episodes: `entry.at` non-null, `holding_minutes` computed — **verify tomorrow.**
      These are written when the episode is created, so today's eight rows (written by the
      old code) still carry `null`. Unit-verified on a synthetic close; the real proof is
      tomorrow's flatten.
- [ ] 8/8 episodes: `features` contains the control indicators known at decide time, with
      absent values **absent rather than 0** — same write-time caveat; **verify tomorrow**
- [x] 8/8 episodes: attribution is required and **satisfied**, because every one of
      today's closes is `evidence_backed`. Derived at read time from the preserved
      status, so rows that store `required=false, satisfied=false` still count, and
      no stored history is rewritten
- [x] `unknown_explicit` and `partial` stay required and do **not** satisfy. A stale
      `satisfied=true` on those statuses does not complete the chain or reach L2.
      Documenting uncertainty does not raise the learning score. `partial` stays short
      of satisfied because material unknowns remain
- [x] Learning audit reports `chain_complete = 8` and level ≥ L2 for those eight, **via the
      normal auditor** (measured: 8 L2 experiences → 8 provisional learnings, all
      `chain_complete`, each L3 `PROVISIONAL`)
- [x] `validated` stays **0** — correct at this stage

**Non-goals:** inventing IV/greeks/news/sector; claiming L5; back-filling intraday paths.

---

### C2 — Learning Auditor integration + acceptance from the normal EOD

**Goal:** the learning layer consumes the canonical dataset without a bespoke report.

**Exists:** `learning_audit.build_and_persist_learning_audit` (already runs on the
paper tick), `fno_closed_loop_dataset.load_closed_loop_day` (tonight).

**Changes:**
- Learning Auditor reads the canonical closed-loop day file as a first-class input
  (cite `closed_loop_experience_id`), so episode ↔ learning record linkage is explicit.
- EOD digest learning section shows the honest ladder counts:
  `episodes / stories / candidates / validated / belief_revisions`.

**Acceptance — the clean test the operator named:**
- [x] The normal auditor already shows the eight episodes as learning inputs with
      `chain_complete=8` and `validated=0`, on today's real file, with no bespoke report
- [ ] **Tomorrow's normal EOD** repeats that from the running service — **verify tomorrow**
- [x] It does not show 0, so there is no integration bug blocking C3. Root cause of the
      earlier `chain_complete=0` was **not** a stale snapshot: `build_trading_experience`
      omitted `evidence_backed` from its satisfied-status set, and
      `attribution_required_for_close` did not recognize the Lab v1 experiment-close tag

**Non-goals:** changing milestone definitions (5 genuine L5 learnings stays the bar).

---

### C3 — Pattern Detector + Hypothesis Engine

**Goal:** experiences → candidate questions, discovered not dictated.

**Hard rule:** the CE/PE asymmetry **must not be hard-coded**. The detector scans
generic dimensions and reports whatever clears a materiality gate.

**Exists:** `hypothesis_learning.create_hypothesis` (statuses
`open/supported/partially_supported/rejected/inconclusive/expired`, `VERDICT_MIN_LINKS=3`),
`research/reasoning.build_hypotheses` (phrasing helper), `fel/contracts.py`.

**Changes — new module `atlas/investment/cognitive/pattern_detector.py`:**
- Input: canonical closed-loop rows (one or more days).
- Deterministic scan over declared dimensions: `option_type`, `underlying_type`,
  `direction`, `mark_source`, `attribution.helped/hurt` membership, `er_model`,
  `holding_minutes` bucket (once C1 lands).
- Output `CANDIDATE_PATTERN` objects: dimension, groups, counts, match rates,
  `n`, `novelty` (unseen vs existing hypotheses), `materiality`, and explicit
  `status=HYPOTHESIS_CANDIDATE` — **never** `LESSON`.
- Fail-closed: `n` below a minimum per group → `status=INSUFFICIENT_SAMPLE`, no hypothesis.

**Changes — new module `atlas/investment/cognitive/hypothesis_engine.py`:**
- Deterministic code owns: evidence selection, sample definition, experiment
  boundaries, falsifier, status. LLM may only phrase `observation` / `hypothesis`
  prose, and a silent/busy LLM yields a deterministic statement (no blocking).
- Structured object (persisted through `hypothesis_learning`, extended via `extra`):
  `hypothesis_id, source_experience_ids[], source_dataset_ids[], observation,
  hypothesis, prediction, expected_effect, falsifier, experiment_spec,
  confidence, novelty, priority, status`.

**Acceptance:**
- [x] Run over the 2026-10-05 dataset emits **4** `CANDIDATE_PATTERN` objects at `n=8`:
      `option_type` (CE 3/4 vs PE 0/4, delta 0.75), `sma_margin_sign`, `holding_bucket`,
      `underlier_direction`
- [x] One structured hypothesis with a falsifier and two `experiment_spec`s (option-premium
      `NOT_EVALUABLE`, underlier restatement `EVALUABLE`)
- [x] Nothing claims a validated effect. The detector is **blind to the dimension name** —
      relabelling CE/PE to ALPHA/BETA surfaces the identical split, which is the test that
      the CE-vs-PE hypothesis was discovered rather than dictated
- [x] With an absent **or silent** LLM the engine still produces the object, from the
      deterministic statement
- [x] The first three patterns are flagged **mutually confounded**: with CE always bought on
      a positive control margin, "CE is better" and "positive margin is better" are one
      claim wearing three names, and the output says so instead of picking one
- [x] The one new hypothesis per cycle is the split this sample can separate, not the
      largest gap. A confounded pattern ranks behind a smaller unconfounded one. On
      today's eight, that puts `underlier_direction` (delta 0.6, separable) ahead of
      `option_type` (delta 0.75, tied to margin sign and holding bucket). The pattern
      file already on disk still lists `option_type` first; the next cycle re-detects
      and spends the slot on the separable split

**Non-goals:** concluding CE > PE; any belief write; any strategy change.

---

### C4 — Agent Kernel owns the hypothesis as work

**Goal:** a discovered question becomes autonomous work with an explicit worth-compute decision.

**Exists:** kernel `observe → _upsert → _select/_is_due → _execute(steps)` with step
kinds for acquire/calculate/lookup_experience/interpret; capability-gap memory;
waiting states; `never_orders`.

**Changes:**
- New observation source `_cognitive_payloads()` alongside `_uncertainty_payloads()`:
  open hypotheses with an `experiment_spec` become observations.
- New task kind `SCIENTIFIC_EXPERIMENT` with a documented admission rubric:
  interesting · testable · sufficiently evidenced · not already tested ·
  required capabilities available (`bars_health.replayable`) · worth compute.
- Refusals are honest and durable: `NOT_EVALUABLE` with reason
  (`insufficient_sample`, `bars_not_replayable`, `already_tested`, `duplicate_hypothesis`).
- Experiment step delegates to the FEL queue (C5). The kernel does not run models itself.

**Guardrails kept:** kernel stays orchestration-only, `never_orders=true`, max one
investigation per tick, existing priority ladder and PLC.A untouched. New task kind
must not outrank live-session or closeout work.

**Acceptance:**
- [x] Kernel surfaces the C3 hypothesis as a cognitive task at **P3** with
      `domain="cognitive"`, so `_select` drops it whenever any P0/P1/P2 task is due
- [x] A second identical hypothesis is refused `duplicate_hypothesis`
- [x] A hypothesis needing a non-replayable symbol is refused `bars_not_replayable`
      (reusing the P2 `market_bars_health.assess_symbols` gate)
- [x] A thin sample is refused `insufficient_sample`; a spec with no falsifier is refused
      `no_falsifier`; every refusal is durable in an append-only queue
- [x] Task cannot emit an order; kernel priority classes and scheduler architecture unchanged

**Non-goals:** new scheduler architecture; changing kernel priority classes.

---

### C5 — Hypothesis → experiment bridge (reuse FEL, build nothing new)

**Exists:** `fel/queue.py` (QUEUED→RUNNING→COMPLETED|FAILED|BLOCKED),
`fel/experiments/dispatch.py`, `workers/fel_experiment.py` (BATCH, yields in RTH),
`fel/experiments/runner.run_experiment` (**baseline required**, walk-forward evaluator,
`promotion_for` never `live_control`), `fel/datasets/builder.build_pit_dataset`,
`market_bars_health` (replay gate), `switch_proof` (NOT_EVALUABLE precedent).

**Changes:**
- New queue kind `hypothesis_test`: `experiment_spec` → PIT dataset from **persisted
  bars only** (no live Yahoo in evaluation) → candidate vs required baseline →
  walk-forward with costs.
- Result is one of `SUPPORTED | REJECTED | INCONCLUSIVE | NOT_EVALUABLE`, written
  durably and linked both ways: `hypothesis_id ↔ experiment_id`.
- Hermetic lab guard already enforced by `assert_lab_hermetic` — keep F&O rows out of
  cash-equity datasets.

**Acceptance:**
- [x] The C3 hypothesis ran through the existing FEL queue and `process_one` reached
      `COMPLETED`, persisting a durable result
- [x] `hypothesis.linked_experiment_ids` and the experiment's `hypothesis_id` agree
- [x] Thin/unreplayable sample → `insufficient_sample` / `NOT_EVALUABLE`, never a verdict.
      An option-premium claim is `NOT_EVALUABLE` because no option intraday history exists,
      and **no daily-bar proxy is substituted** for it
- [x] `promotion` is never `live_control`; `mutates_strategy=false`; `live_orders=false`
- [x] Experiment reads durable bars only — no live Yahoo
- [x] A spec that does not declare a baseline is refused `baseline_not_declared`

**Non-goals:** a second experiment framework; RL; model promotion.

---

### C6 — Learning validation (enforce the ladder)

**Exists:** `l5_validation` — `promote_l3_to_candidate`, `define_subsequent_test`,
`record_test_observation`, statuses `OPEN / VALIDATED / FALSIFIED / INCONCLUSIVE`,
hard law "no L5 without a subsequent-test result".

**Changes:**
- Experiment result feeds the ladder: `SUPPORTED` → L4 belief candidate **with an
  OPEN subsequent test**; `REJECTED` → FALSIFIED record (kept, it is real knowledge);
  `INCONCLUSIVE`/`NOT_EVALUABLE` → stays candidate, no belief write.
- Replication requirement documented: one supported experiment is **not** validated;
  validation needs the pre-declared independent sample to also pass.

**Acceptance:**
- [x] A SUPPORTED result produces exactly one L4 candidate with an OPEN subsequent test
      (never L5) via `l5_validation.promote_l3_to_candidate`
- [x] A REJECTED result is durable and does not silently vanish — the honesty line says the
      result was kept
- [x] INCONCLUSIVE and NOT_EVALUABLE write **no belief at all**
- [x] `validated` count only rises after a second independent pass
      (`REPLICATION_PASSES = 2`, matching the existing `DEFAULT_SESSIONS_N` convention)
- [x] Ladder counts keep questions and validated learnings in separate columns, so
      "4 patterns" can never be read as "4 learnings"

**Non-goals:** auto-promoting to L5; any strategy mutation.

---

### C7 — Validated learning → belief revision (versioned)

**Exists:** `belief_revision.revise_beliefs_budgeted`, `world_state` WSOs,
`global_mind.distill_global_mind`, existing contradiction handling.

**Changes:**
- Belief objects get explicit versioning: `belief_id, version, statement, confidence,
  previous_version, evidence[] (experiment ids), learning_ids[], reason, status
  (PROPOSED | ACCEPTED | REJECTED), at`.
- `PROPOSED → contradiction check → ACCEPTED` only with a VALIDATED learning behind it.
- Belief acceptance remains **advice-level**: it changes decision *context*, never
  order authority, SMA/RSI, PLC.A, or capital allocation.

**Acceptance:**
- [x] A belief revision is `PROPOSED` with cited experiment and learning ids
- [x] Belief version chain is readable (`B.. v1 → v2`) with reason and evidence, append-only
- [x] A revision **cannot be accepted** without a validated learning id — refused
      `no_validated_learning`. Since `validated` is 0, nothing is accepted today, which is
      the point
- [x] No strategy/capital/order change results: each revision records
      `affects: decision_context_only` and names what it does not affect
      (order authority, sizing, capital allocation, SMA/RSI V1, PLC.A)

**Non-goals:** letting beliefs size positions; unfreezing RL.

---

### C8 — Behavioural proof

**Goal:** show the belief actually changes a later decision context — otherwise we
have not demonstrated learning.

**Changes:**
- Decision packets record which belief version they consumed.
- A before/after comparison artifact: same-shaped decision under belief v1 vs v2,
  with the delta stated in confidence/context terms (paper only).

**Acceptance:**
- [x] `belief_context_for_decision` returns only ACCEPTED versions, and
      `behavioural_delta` makes no behavioural claim when nothing changed
- [ ] One decision packet cites belief version N+1 — **cannot be verified yet, by design.**
      No belief is accepted because no learning is validated, so the decision context is
      correctly empty. This box opens only after a hypothesis survives two passes
- [x] Live trading behaviour unchanged; every delta is marked `paper_only`

**Non-goals:** trading differently to prove a point.

---

### C9 — Reflection → next question

**Changes:**
- Nightly cognition (C0) ends by asking the next question: unresolved falsifiers,
  INCONCLUSIVE experiments, and new patterns become the next cycle's candidates.
- EOD shows: *questions open / asked today / answered / rejected*.

**Acceptance:**
- [ ] Reflection runs on a weekday without delaying mail — **verify tomorrow** (the gate is
      proven to refuse every market hour and to wait for the digest; the live tick is not)
- [x] Self-generated next questions persisted and traceable to episodes — **4 open
      questions** after the first cycle
- [x] Loop closes: question → experiment → result → next question. Cycle 2 refused the
      cycle-1 hypothesis as a duplicate and asked a *different* question
      (`sma_margin_sign`) without being told to

**Only after C9 passes may we call the cognitive loop autonomous.**

---

## 4. Sequencing and dependencies

```text
C0 ──┐
C1 ──┼─→ C2 ─→ C3 ─→ C4 ─→ C5 ─→ C6 ─→ C7 ─→ C8 ─→ C9
     │                                    ▲
     └──────────── C0 enables ────────────┘
```

| Phase | Depends on | Blocking risk |
|---|---|---|
| C0 | — | none (isolated worker + receipt) |
| C1 | — | low (three narrow fixes) |
| C2 | C1 | reveals integration bugs early |
| C3 | C1 (features/entry.at improve dimensions) | detector too eager → materiality gate |
| C4 | C3 | kernel priority regression → admission rubric + tests |
| C5 | C4, P2 bars health | thin history → NOT_EVALUABLE |
| C6 | C5 | premature L5 → ladder enforces |
| C7 | C6, C0 | belief without validation → gate |
| C8 | C7 | unobservable change → packet citation |
| C9 | C0, C8 | mail regression → receipt pattern |

---

## 5. Freeze list for this workstream (unchanged)

- ❌ No new trading strategy, indicator, mentor, or agent swarm
- ❌ No new F&O experiment or additional paper trades to "get more data"
- ❌ No new data source or database
- ❌ No FEL promotion to live control; `never_orders` stays true
- ❌ No SMA/RSI, PLC.A, capital-allocation, or order-authority changes
- ❌ No RL unfreeze; HBLPOWER golden replay stays LOCKED
- ❌ No LLM concurrency/model bump (P5 order stands)
- ❌ No inventing PE/ROE/D/E/FCF/price/IV/greeks; web snippets are not numbers
- ✅ Missing data stays UNKNOWN; refusals are durable and explicit

---

## 6. Global acceptance — the C1 milestone

> Given the existing eight canonical F&O closed-loop episodes, Atlas autonomously
> identifies at least one non-trivial pattern, creates a structured testable
> hypothesis, schedules an experiment through the Agent Kernel, executes it through
> the existing FEL runner, records SUPPORTED / REJECTED / INCONCLUSIVE, and produces
> a validated-or-rejected learning candidate — without changing live trading behaviour
> and without the hypothesis being named by the operator.

**This milestone was met on 2026-10-05**, with the verdict INCONCLUSIVE rather than
SUPPORTED. That is a pass: the requirement was that Atlas *reach* a verdict honestly, not
that it agree with the operator's guess.

Checklist:

- [x] C0 nightly cognition is off the mail path; digest read costs 0.12 ms
- [~] C1 episodes: attribution complete now; `entry.at` / `features` / `holding_minutes`
      are write-time and land on tomorrow's close
- [x] C2 normal auditor recognizes 8 episodes, `chain_complete=8`, `validated=0` honest
- [x] C3 pattern + hypothesis discovered, not dictated (name-blindness test passes)
- [x] C4 kernel admits/refuses at P3 with a documented rubric and durable refusals
- [x] C5 experiment ran on persisted data only; verdict durable
- [x] C6 ladder enforced; no premature L5; replication required for VALIDATED
- [x] C7 belief proposal versioned and evidence-cited; acceptance gated on validation
- [~] C8 machinery in place and paper-only; a cited decision packet waits on a validated
      learning, which does not exist yet
- [x] C9 next question self-generated; cycle 2 asked something new

---

## 7. Decisions (finalized 2026-10-05 by operator)

1. **Scope.** Implement **all phases C0 → C9, step by step**, re-verifying tomorrow.
2. **Hard constraint — must not block Atlas activity tomorrow.** Every addition is:
   - **BATCH class**, yielding to live/closeout work; never on the mail or order path
   - wrapped so a failure is logged and skipped, never raised into an existing tick
   - **kill-switchable** via worker config `nightly_cognition: false` (default on, flip to
     off without a deploy)
   - **zero added latency** to morning/hourly/evening mail (verified by timing)
   - **no change** to kernel priority classes, scheduler architecture, or order authority
3. **Materiality gate (C3).** Record the question at `n ≥ 3` per group, but mark
   `INSUFFICIENT_SAMPLE` so no verdict is possible from it.
4. **Independent sample (C5/C6).** Option-specific claims return `NOT_EVALUABLE`
   until an option history exists. First experiments test underlier-direction-conditioned
   claims on durable daily bars. No invented premiums, no daily-bar proxy for options.
5. **Replication for VALIDATED.** Two independent passes, matching the existing
   `DEFAULT_SESSIONS_N` convention in `l5_validation`.
6. **Nightly cognition location.** New BATCH worker tick after the evening mail window.

---

## 8. Work log

| When (IST) | Phase | Result |
|---|---|---|
| 2026-10-05 night | Plan authored | Awaiting finalization; two code-level causes of `chain_complete=0` identified |
| 2026-10-05 night | Plan finalized | Operator chose full C0 → C9, `NOT_EVALUABLE` for option claims, and record-at-`n≥3`-but-`INSUFFICIENT_SAMPLE` |
| 2026-10-05 night | C1 | Two root causes fixed; 8/8 episodes now read as required + addressed, `chain_complete=8`, all L3 `PROVISIONAL`, `validated=0` |
| 2026-10-05 night | C0 | Nightly cognition moved to its own post-digest BATCH window with an on-disk receipt the mail reads |
| 2026-10-05 night | C2 | Auditor consumes the canonical day; derivation moved to read time so no stored history is rewritten |
| 2026-10-05 night | C3 | 4 candidate patterns at n=8, 3 flagged mutually confounded; 1 hypothesis with falsifier and 2 experiment specs |
| 2026-10-05 night | C4 | Admission rubric + append-only decision queue; kernel surfaces the question at P3, `domain=cognitive` |
| 2026-10-05 night | C5 | FEL `hypothesis_test` handler; ran to `COMPLETED` on durable bars, no live fetch |
| 2026-10-05 night | C6 | Verdict **INCONCLUSIVE** — underlier gap 0.25 vs required 0.5 (CE 0.75, PE 0.5, baseline 0.625 n=8). 1 candidate, 0 belief writes, `validated=0` |
| 2026-10-05 night | C7/C8 | Versioned belief proposals, acceptance gated on a validated learning, `affects: decision_context_only`. Nothing accepted, as expected |
| 2026-10-05 night | C9 | Cycle 2 refused the duplicate, asked about `sma_margin_sign`, listed 4 open questions |
| 2026-10-05 night | Verification | 46 new tests pass. Full suite at parity with a clean `HEAD` worktree baseline (40 pre-existing failures, all date- or wall-clock-drift or sandbox-permission) |
| 2026-10-05 night | Guard | Nightly gate refuses 07/11/13/15/16h and 23h, allows 18–22h, and only once the digest flag is set. Fails closed if the flag cannot be read |
| 2026-10-05 night | Scoring correction | `satisfied` is only `evidence_backed` or `attributed`. `unknown_explicit` and `partial` stay required and do not complete a chain. Today's eight are unchanged (`chain_complete=8`) because they are `evidence_backed` |
| 2026-10-05 night | Question ranking | The single hypothesis slot prefers a separable split over a larger confounded one. Next cycle asks `underlier_direction` before `option_type` |

### What the loop actually concluded

Atlas looked at its own eight episodes, found that CE won 3 of 4 while PE won 0 of 4,
and **declined to believe it**. Three separate reasons, all of them deterministic:

1. The option-premium version of the claim is `NOT_EVALUABLE` — there is no option
   intraday history, and a daily-bar proxy was refused rather than invented.
2. The restated underlier-direction claim *is* evaluable, and the gap shrank to 0.25
   against a required 0.5 — **INCONCLUSIVE**, not supported.
3. `option_type`, `sma_margin_sign`, and `holding_bucket` partition the same eight
   episodes identically. With CE always bought on a positive control margin, those are
   one claim with three names, and no sample here can separate them.

So the honest state is: **4 questions asked, 1 tested, 0 learned.** The 8 closed loops are
now visible to the learning layer, which was the operator's P0.

### Two corrections after review

The learning score and the question budget were both slightly too generous.

**Satisfied means the cause was labeled.** `evidence_backed` and `attributed` satisfy
attribution, reach L2, and can complete a chain. `unknown_explicit` (we looked and still
don't know) and `partial` (some factors labeled, material unknowns remain) stay required
and stay unsatisfied. A stored `satisfied=true` does not override those statuses. Today's
eight closes are all `evidence_backed`, so `chain_complete` is still 8.

**The one question is the separable one.** Candidate patterns were ordered by gap size, so
the confounded `option_type` split (0.75) took the only hypothesis slot ahead of
`underlier_direction` (0.60), which this sample can actually separate. Confounded patterns
now rank behind unconfounded ones. The pattern file already written for 2026-10-05 still
lists `option_type` first; the next cycle re-detects and spends the slot on
`underlier_direction`. No hypothesis from the earlier run was stored, so nothing has to
be refused as a duplicate first.

### Carried forward

- Write-time episode fields (`entry.at`, `features`, `holding_minutes`) need tomorrow's close.
- Restarted again at 23:45 IST onto this code (PID 3070186), so tomorrow's
  post-digest tick is the first live cycle under the new ranking and the stricter
  satisfied rule.
- A separating sample for the confounded dimensions requires a CE bought on a *negative*
  margin (or the reverse), which the current control never does. Noted, not acted on —
  adding trades to manufacture contrast is on the freeze list.

### 2026-10-13 — R1–R3: the LLM proposes, fresh trades decide (`9b0b238`)

Operator goal: use the LLM to do research. Review of the loop before building found four reasons it had learned nothing since 10-08:

| Finding | Effect | Fix |
|---------|--------|-----|
| `bar_path("NIFTY")` looked for `NIFTY.NS.json`; the writer stores `_NSEI.json` (same for BANKNIFTY) | Every cycle with an index trade refused admission as `bars_not_replayable` — including the only hypothesis, `5623ea11` | `bar_path` asks `bar_store.symbol_path` first |
| The experiment scored a hypothesis on the episodes it was found in | Any SUPPORTED would have been self-confirmation | Spec carries `exclude_experience_ids` + `asked_as_of`; only later episodes count. Old specs without a holdout → `no_holdout_declared` |
| `underlier_direction` / `holding_bucket` are known only after the trade | `5623ea11` asked a circular, non-actionable question | `POST_HOC_DIMENSIONS`: reported, never a hypothesis; `5623ea11` closes as `post_hoc_dimension` |
| Fallback scored episodes against `bars[-1]` (today's bar) | Old trades judged on the wrong day | Bar for the episode's own session, else unresolved |

**R3 — gate.** `MIN_SPLIT_DELTA = 0.5` replaced by: groups n ≥ 3 **and ≥ 2 sessions** (same-day trades share one market move), gap ≥ 0.15, two-sided Fisher exact p ≤ 0.25, Benjamini–Hochberg at q = 0.25 across the scan. That is a screen for *asking*. The verdict is on the fresh sample only: each group n ≥ 5 over ≥ 2 sessions (else `awaiting_fresh_sample`, re-tested every night), gap ≤ 0 → REJECTED, one-sided p ≤ 0.05 → SUPPORTED, else INCONCLUSIVE. Validation still needs 2 passes.

**Feature space.** Added fixed-edge buckets: `sma_margin_strength`, `entry_time_bucket`, `entry_weekday` (available on all episodes now) and `dte_bucket`, `iv_bucket`, `moneyness_bucket`, `theta_share_bucket` (from decide-time features captured since `82af44e`).

**R1 — trade reviews.** `cognitive/llm_research.py`: newest unreviewed eligible round trip → schema-constrained review (`what_happened`, `main_driver`, `signal_or_luck`, `lesson_candidate`, `data_missing`, optional `testable_idea`) → `investment/cognitive/llm_research/<lab>/trade_reviews.jsonl`. Packet carries decide-time features, prediction, outcome, error, attribution; times in IST.

**R2 — proposals.** Once a day, the LLM gets the per-feature table, constants, never-captured features, already-asked dimensions and review ideas, and returns ≤ 3 questions (dimension restricted by schema to decide-time features). Code validates each (feature in data, both groups present, not asked, mechanism + falsifier present) → `proposals/<day>.jsonl` with verdict. The nightly cycle takes ≤ 1 accepted proposal (last 3 days), rebuilds it as a pattern **from the data** (LLM numbers ignored; confounds computed), and sends it through the normal admission. Statement reads "Proposed question … so far a/b"; never claims the LLM's ordering.

**Where it runs.** `decision_evolution` (the one worker holding the LLM), after the scientist drain: off-hours only (not 09:00–15:45 IST weekdays), ≤ 3 calls / 480 s per tick, ≤ 8 calls per lab per day, last call reserved for the proposal. ~90 s per review, ~190 s per proposal on this host.

**Dry run on a copy of live data (2026-10-13).** 29 eligible episodes. Detector: no candidate (the only uneven split, Thu 7/7 vs Wed 3/6, is one session each). LLM review of TCS26OCT2160PE in 87 s; proposal call 193 s → 3 accepted (`sma_margin_sign` — confounded with `option_type`, `sma_margin_strength`, `entry_time_bucket`). Cycle admitted `entry_time_bucket` (LLM-proposed) → `awaiting_fresh_sample`; `5623ea11` closed as post-hoc. No strategy, sizing or order change.
