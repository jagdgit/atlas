# Weekend plan — restore F&O, then make market learning real

**Date:** 2026-10-09 (Friday evening, IST)  
**Window:** Saturday 10 Oct – Sunday 11 Oct. Market is closed. Do not require a live pack as proof.  
**Status:** PLAN ONLY. No worker, schedule, database, or trading gate was changed while writing this.  
**Constraint:** Paper only. Do not lower switch thresholds, PLC.A, or capital gates to create activity. Do not delete knowledge, experiences, learning, trading history, embeddings, or documents. Do not remove Ollama models.

This is the runbook for Monday. Each step has a command or a file to open, a number you should see, and a pass/fail. If a check fails, stop that package and fix the cause before the next package.

Related: `docs/2026-10-08_AUTONOMOUS_SELF_DIAGNOSIS_V1_PLAN.md` (Phases 1–8 closed on ops learning, not market learning).

---

## 0. What is actually true

Three different things happened on 9 Oct. They must not be collapsed into “Atlas had a quiet day.”

### 0.1 F&O did not trade because its paper worker was paused

Phase 5 on 8 Oct 22:59 IST classified enabled `worker_tick` schedules with this rule:

> one enabled tick per `(program_id, worker_type)`

Both labs sit under `program_id=market_intelligence` and `worker_type=paper_trading`. The classifier kept Intraday and marked F&O **STALE**.

| Role | Mission | Worker | Schedule | Phase 5 |
|---|---|---|---|---|
| India Intraday Lab · Decision Simulation | `d806c8e6-6fba-4603-84eb-b88fb408af9b` | `b763e840-061a-4343-8546-1b7838e9d9c2` | `51e2bf75-e816-47f5-82ed-1b8a3c580f86` | ACTIVE (kept) |
| India F&O Lab · Decision Simulation | `5ff9fb98-330e-4eee-a31d-9a4065a73a14` | `d6c9a9fc-8145-444a-85f7-9c25c81e126b` | `2da6e972-84c6-4b5e-ae9f-1246613ed646` | STALE (paused + schedule disabled) |
| trade simulation (cash swing) | `9bcc3175-c613-486c-bcbb-e2f094ba5dfd` | `54260bf0-d04c-4356-bbe1-f24977926f49` | `0fa2eea4-e585-4126-9528-5f4cdd91baef` | ACTIVE (`program_id=_unscoped`, so it was not in the collision) |

Evidence: `/data/atlas_data/ops/phase5_worker_tick_2026-10-08/classification.json` and `VERIFY.md`.

What that produced on 9 Oct (`/data/atlas_data/investment/ops_health/2026-10-09.json` and `market/trading_kpis/india_fno_learner/2026-10-09.json`):

| Fact | Value |
|---|---|
| F&O packs | **0** |
| F&O fills | **0** |
| Zerodha | **READY** at 06:42 IST (`ZERODHA_LOGIN_RECOVERED` → `FNO_LAB_READY`) |
| Options master | `NOT_ATTEMPTED` (nothing was evaluating contracts) |
| P0 `fno:paper_worker` | opened 10:19 IST, last seen 15:29 IST, **RESOLVED 15:33 IST** |
| Resolution text | `condition cleared` |
| Recovery | `NOT_APPLICABLE` |
| Window minutes | `E_WORKER_SCHEDULER_FAILURE` **292**, `A_GENUINE_IDLE` 18 |
| `planned_symbols` | HFCL, ICICIGI, IDEA, SUNTV, TRENT — cash watchlist, not F&O contracts |

The incident closed because the market window ended, not because the worker resumed. In `atlas/investment/ops_health.py`, `_RECOVERABLE` is only `{instrument_master, futures_master, options_master}`. `fno_paper_worker` is not in that set, so recovery is `NOT_APPLICABLE` and Atlas never calls `WorkerManager.resume`. After `RESOLVED_GRACE_TICKS` of the finding disappearing (window closed), status becomes `RESOLVED` / `condition cleared`.

### 0.2 Equity swing was alive and holding on purpose

`market/trading_kpis/india_equity_learner/2026-10-09.json`:

| Fact | Value |
|---|---|
| Buys / sells / fills | 0 / 1 / 1 |
| Open positions | 1 |
| Cash / holdings / equity | ₹35,194.70 / ₹9,347.65 / ₹44,542.35 |
| Contributed / total return | ₹55,000 / **−19.01%** |
| Dominant non-session reasons | `switch_blocked` 326, `strategy_hold` 189, `plc_a_hold` 27, `lab_policy_hold` 19 |

Next-₹1 (`investment/next_rupee/india_equity_learner/2026-10-09.json`) says **DEPLOY SUNTV.NS**, E[R] +6.56%, completeness **0.45**, and names HBLPOWER as the incumbent HOLD at E[R] +3.6% with completeness **0.15**. The same file sets `advice_only: true` and `never_orders: true`. That path cannot place the trade.

Switch bar in code (`atlas/investment/opportunity_switch.py`): normal threshold **2%**, cold-start / PLC path **5%** (`cold_start_threshold = 0.05`), plus about 1% switch cost. An advantage of ~1–3% against the 5% bar is a hold, not a bug. Do not lower it this weekend to “make it trade.”

### 0.3 Intraday traded. That is not learning.

`market/trading_kpis/equity_intraday_learner/2026-10-09.json`:

| Fact | Value |
|---|---|
| Buys / sells / fills | **10 / 3 / 13** |
| Filled symbols | IDEA.NS, TRENT.NS |
| Open at close | **0** (integrity file: `flat_ok`) |
| Contributed / total return | ₹50,000 / **−1.21%** (₹−605.83) |
| Dominant block | `capability_gap` **421**, then `intraday_yahoo_budget` 204 |

Flatten ledger (`investment/intraday_integrity/equity_intraday_learner/2026-10-09.json`): IDEA session 9 Oct **₹−13.66**, TRENT **₹+11.70**, plus an older IDEA flatten with ₹0. Headline “10 buys / 3 sells” and “three flatten outcomes” are different stages. Reconcile the ledger in Package C. Do not treat fill count as a lesson.

### 0.4 F&O is the only lab producing complete market episodes. It does not have a proven edge.

Closed-loop rows on disk (`investment/fno/closed_loop/india_fno_learner/*.jsonl`), all `chain_complete=true`, all with a direction match:

| IST day | Episodes | Direction matched / missed | Sum of `outcome.realized_pnl` |
|---|---|---|---|
| 2026-10-05 | 8 | 3 / 5 | **+₹218.75** |
| 2026-10-06 | 0 | — | no round-trips |
| 2026-10-07 | 6 | 3 / 3 | **−₹5,445.75** |
| 2026-10-08 | 7 | 7 / 0 | **+₹14,760.50** |
| 2026-10-09 | 0 | — | worker paused; no file of rows |

21 episodes total. Book KPI `total_pnl` of about +₹27,886 is the **portfolio mark versus ₹100,000 contributed**, not the sum of these three sessions. Do not add them together.

On 5 Oct the pattern detector recorded a CE vs PE direction-match split of 0.75 (3/4 vs 0/4). After 7–8 Oct the same dimension is CE 3/4 (0.75) vs PE 10/17 (0.59). Delta is **0.16**. The detector requires `MIN_SPLIT_DELTA = 0.5` (`atlas/investment/cognitive/pattern_detector.py`). **Zero patterns on 9 Oct is the correct refusal.** The 5 Oct pattern did not survive more sessions. Manufacturing a pattern by lowering 0.5 would be the opposite of learning.

The one admitted market hypothesis is still sitting there:

- id `5623ea11-016e-4a70-8843-3908ff3d4c48`
- dimension `underlier_direction`
- status **ADMITTED** since 2026-10-06 19:43 IST
- file: `investment/cognitive/queue/india_fno_learner.jsonl`
- cognitive cycle every night since: “awaiting result … experiment queued but no result recorded yet”

It was never dispatched. `AgentKernel.laboratory_id` defaults to **`india_equity_learner`** (`atlas/agent_kernel/kernel.py`). `next_admitted_hypothesis` is read for that lab only. The F&O queue is invisible to the kernel. Even if it were visible, the task is priority **P3** and is dropped whenever any P0/P1/P2 investigation is due.

There is no FEL queue file `HYP-5623ea11…`. The completed F&O FEL item `E-paper-round-trip-india_fno_learner` is a different experiment: result `no_significant`, “mean reward above cash but sample too small to promote SMA/RSI”, `promotion: never`.

### 0.5 What improved, and what did not

Ops learning from 8 Oct is real and narrow: investigate → verify → record → cite, on **schedule identity**. The belief is `ACCEPTED_OPS`. It does not size trades and it is not an L5 market lesson. Nightly cognition for **equity** did run on 9 Oct (`investment/nightly_cognition/india_equity_learner/2026-10-09.json`, `ran: true`, including reflection). The F&O cognitive cycle also ran, over the old 21 episodes, and honestly emitted 0 new patterns.

Learning Auditor overall stays **DEVELOPING** until there are at least 5 chain-complete learning records and zero `NOT_SOLVED` patterns (`learning_audit.py`). Provisional records with unknown causes do not clear that bar.

### 0.6 Why “it noticed and still did nothing” is structural

Atlas can see the P0. It cannot act on it.

| Layer | What it can do today | What 9 Oct needed |
|---|---|---|
| Ops health | Open P0, email, retry **NFO master refresh only** | Resume one paused paper worker |
| Incident closer | Mark resolved when the finding disappears | Stay open until a pack or a named pack-failure exists |
| Agent Kernel toolbox | `sql`, `logs`, `git`, `code`, `python` (read / inspect) | A bounded `worker.lifecycle` action |
| Kernel lab scope | `india_equity_learner` | Also see `india_fno_learner` hypotheses |
| HTTP API | `POST /v1/workers/{id}/resume` re-enables that worker’s schedule (`WorkerManager.resume`) | Something in-process must be allowed to call it |
| MCP | Not how Atlas invokes its own tools | A later adapter so a different model sees the same tools |

An MCP server does not fix this by itself. A new model attached to the current toolbox would still be unable to resume a worker and would still look at the equity hypothesis queue. Build the capability first. Put MCP in front of that capability second, so a future model swap keeps the same actions.

---

## 1. How the three labs are supposed to differ

Atlas already has separate portfolio keys. The scheduler and the kernel throw two of them into one bucket. The weekend fix is to make every identity, every learning loop, and every recovery action carry the laboratory id.

| | Cash swing `india_equity_learner` | Intraday `equity_intraday_learner` | F&O `india_fno_learner` |
|---|---|---|---|
| Job | Multi-day paper book. Hold is a valid decision. | Flat by 15:20 IST. A position overnight is a defect. | Session paper options. Experiment-scoped exit. No overnight option inventory. |
| What “idle” means | Engine hold, PLC.A incomplete, switch advantage under the bar, advice-only next-₹1 | Blocked buy, Yahoo budget, capability gap, then a flatten | Worker not ticking, or pack `NOT_READY` with a named reason |
| What a fill teaches | Only after prediction, outcome, and attribution join | A blocked buy teaches the gate. It does not teach that the signal made or lost money | Only a closed round-trip with decide-time features |
| What may change behavior | Nothing from an unvalidated lesson. SMA/RSI and PLC.A stay the control | Same | Same. Cognitive loop sets `mutates_strategy: false` |
| Learning loop that exists | Learning Auditor + nightly cognition. Stories can have unknown causes | Same auditor. FEL paper-round-trip already returned `no_significant` | Closed-loop dataset → pattern detector → one hypothesis. **Dispatch is not wired to this lab’s kernel scope** |
| This weekend | Do not force SUNTV. Test the switch rule on history | Reconcile the 9 Oct ledger. Do not add trades | Restore the worker. Dispatch the admitted hypothesis on persisted bars |

---

## 2. Order of work

Do these in order. P0 before any research. P1 before claiming the hypothesis was tested. P2 and P3 can overlap on Sunday only after P0 passes.

| Package | Outcome | Stop if |
|---|---|---|
| **P0** | F&O worker resumed, identity key fixed, both labs survive a second dedupe | You cannot show both workers `running` with both schedules enabled |
| **P1** | Admitted F&O hypothesis has a real FEL result on disk | You would have to invent option prices or lower `MIN_SPLIT_DELTA` |
| **P2** | One bounded historical test of the equity switch rule, threshold unchanged | The test needs a live order or a lower bar |
| **P3** | Incident closer and evening report stop lying about recovery | A market-close still counts as recovered |
| **P4** | Kernel can resume this class of pause, then a blind test proves it | The action can pause, stop, or trade |
| **P5** | Monday card: what is ready, what is still unknown | Any line claims a validated market lesson |

---

## 3. P0 — Restore F&O and make the identity key honest

### Step 0. Confirm the process and the three workers before touching anything

1. Service is up: `systemctl status atlas --no-pager`. If it is not active, start it and wait until it is healthy. Do not resume workers against a dead service.
2. Read, do not write:

```bash
curl -sS http://127.0.0.1:8000/v1/workers/d6c9a9fc-8145-444a-85f7-9c25c81e126b
curl -sS http://127.0.0.1:8000/v1/workers/b763e840-061a-4343-8546-1b7838e9d9c2
curl -sS http://127.0.0.1:8000/v1/workers/54260bf0-d04c-4356-bbe1-f24977926f49
```

If the API is not on port 8000, use the port in the unit file. Record `status`, `health`, and the portfolio key inside config/metadata.

**Pass:** F&O worker status is `paused`. Intraday and swing are `running`. F&O portfolio key is `india_fno_learner`. Intraday portfolio key is `equity_intraday_learner`.

**Fail:** any of those keys differ. Stop. The ids above came from the Phase 5 classification on 8 Oct. Re-identify by mission title before resuming. Never resume a worker whose portfolio key you have not read.

### Step 1. Resume only the F&O worker

`WorkerManager.resume` sets the worker back to `running` and enables **its** schedule. That is the one action. Do not create a new mission.

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/workers/d6c9a9fc-8145-444a-85f7-9c25c81e126b/resume \
  -H 'content-type: application/json' \
  -d '{"reason":"weekend P0: phase5 paused india_fno_learner as duplicate of intraday"}'
```

**Pass:** response status `running`, and a second GET shows schedule `2da6e972-84c6-4b5e-ae9f-1246613ed646` enabled. Intraday worker still `running`.

**Fail:** a new worker id appears, or intraday flips to paused. Revert by pausing only what you just created. Do not “clean up” by pausing intraday.

### Step 2. Change the dedupe key in code

Phase 5’s classifier was a one-off. It is not a module in the repo (no `duplicate role` string under `atlas/`). The next person, or Atlas, will repeat it if the rule is only in a note.

Add one function, used by any future worker-tick dedupe and by a regression test:

```text
role_key = (program_id, worker_type, laboratory_id)
```

`laboratory_id` is the paper worker’s `portfolio_key` when `worker_type=paper_trading`. For every other worker type, `laboratory_id` is empty and the old `(program_id, worker_type)` key stays.

Required pairs that must **not** collapse:

| program_id | worker_type | laboratory_id | Must stay independently enabled |
|---|---|---|---|
| `market_intelligence` | `paper_trading` | `equity_intraday_learner` | yes |
| `market_intelligence` | `paper_trading` | `india_fno_learner` | yes |
| `_unscoped` or `market_intelligence` | `paper_trading` | `india_equity_learner` | yes |

A second dedupe run must change nothing. Restarting the service must not pause any of the three.

Put the test in `tests/` next to `tests/test_f1_f5_schedule_idempotency.py`. The test builds three fake workers with those keys, runs the classifier twice, and asserts all three stay ACTIVE. It also asserts that two workers with the **same** triple still collapse to one, so real program-reconcile duplicates (the original `investor_reports` ×7 case) still get removed.

**Pass:** `pytest` for that test is green, and a live re-read of the three workers is unchanged after you run the new dedupe once in dry-run and once for real.

**Fail:** dry-run wants to pause F&O again. Do not apply it.

### Step 3. Weekend proof that the F&O path can evaluate, without a live market

Market is closed. A live pack is not the acceptance test.

1. Confirm Zerodha readiness file still says READY or record the actual status. Weekend READY is not required for the replay test.
2. Run the existing closed-loop loader for `india_fno_learner` and confirm it still returns **21** episodes and **0** rows for 2026-10-09. That proves the join code is intact and that today added nothing.
3. Run one pack build against the last persisted NFO master and the last persisted bars, in a replay/dry entry point that already exists (`fno_data_pack` / paper worker dry path). If no dry entry point exists, do not invent a live order path. Write a small read-only script that resolves expiry + ATM CE/PE from the last saved master and prints either a contract tuple or a precise reason (`master_not_for_today`, `no_futures`, `no_atm`).
4. Save the stdout under `/data/atlas_data/ops/weekend_2026-10-10/fno_replay.txt`.

**Pass:** either a concrete contract tuple from persisted data, or a single named reason. `0 packs` with no reason is a fail.

**Do not:** place a paper fill for 10 or 11 Oct and backdate it. That would poison Monday’s ledger.

### Step 4. Re-open the false recovery

Edit is in `atlas/investment/ops_health.py`, not in the JSON by hand as the only fix. The 9 Oct incident file may be annotated, but the code must change or Monday repeats the lie.

New rule for `fno:paper_worker`:

- Status may be `OPEN`, `RECOVERY_IN_PROGRESS`, `RECOVERED_VERIFIED`, or `UNRESOLVED_OPERATOR_ACTION_REQUIRED`.
- `RESOLVED` / `condition cleared` is legal only when a later tick observed a pack write **or** a pack `NOT_READY` with a reason other than “worker not ticking”, during an expected window, **or** a weekend replay receipt from Step 3 is attached as evidence of path recovery.
- Market close (`expected_window` flipping to false) must not increment `missing_ticks` toward resolution for this key.
- Add `fno_paper_worker` to a new allowlist `_RECOVERABLE_WORKER` whose only automatic action is: if the paper worker for `india_fno_learner` is `paused` and the pause reason contains `phase5:STALE`, call the same resume path as Step 1, once, then wait for confirmation. No other pause reason is auto-resumed.

**Pass:** a unit test feeds “window ended, packs still 0, worker still paused” and the incident stays `UNRESOLVED_OPERATOR_ACTION_REQUIRED`. A second test feeds “worker running and a pack exists” and the incident becomes `RECOVERED_VERIFIED`.

---

## 4. P1 — Dispatch the hypothesis that has been waiting since 6 Oct

The question already written, do not replace it with a new one:

> On `underlier_direction`, episodes labeled up matched their stated direction more often (3/5) than episodes labeled down (0/3). Reject if, on a pre-declared independent sample, the direction-match gap falls below 0.5 or reverses. A smaller same-sign gap is INCONCLUSIVE.

File: `investment/cognitive/queue/india_fno_learner.jsonl`, hypothesis `5623ea11-016e-4a70-8843-3908ff3d4c48`. Spec says `evaluable: true`, data `daily_underlier_bars`, evaluator `walk_forward`, `baseline_required: true`, `mutates_strategy: false`.

### Step 5. See why the kernel never picked it up

1. Open `atlas/agent_kernel/kernel.py`. Confirm `laboratory_id` defaults to `india_equity_learner`.
2. Confirm `_cognitive_payloads` calls `next_admitted_hypothesis(..., laboratory_id=self.laboratory_id)`.
3. Confirm `_dispatch_hypothesis_test` is the only caller of `enqueue_hypothesis_test` outside tests.

**Pass for the diagnosis:** you can point at those three facts. That is the blockage. It is not “the LLM forgot.”

### Step 6. Run the test on persisted bars

Call `enqueue_hypothesis_test` for laboratory `india_fno_learner` and that hypothesis id, then let the existing FEL dispatch (`atlas/investment/fel/experiments/dispatch.py`, handler `hypothesis_test`) claim it. Do this from a one-off operator script or a kernel tick whose `laboratory_id` is set to `india_fno_learner`. Do not point the equity kernel at F&O permanently in the same change; give the cognitive pickup an explicit list of labs: `india_equity_learner`, `equity_intraday_learner`, `india_fno_learner`.

The evaluator must use durable daily bars only (`experiment_bridge._load_bars`). No live Yahoo.

**Pass:** a result file exists under `investment/cognitive/experiments/` (or the FEL finding path the bridge already writes) whose `result` is one of `SUPPORTED`, `REJECTED`, `INCONCLUSIVE`, `NOT_EVALUABLE`, and the queue row is no longer stuck at `ADMITTED`.

**Expected, and acceptable:** `INCONCLUSIVE` or `NOT_EVALUABLE`. The discovery sample is the same 8 episodes from 5 Oct. An independent sample is 7 Oct and 8 Oct, and those days moved the option-type split from 0.75 to 0.16. If underlier bars for the held names are missing, the result must be `NOT_EVALUABLE` with the missing symbol names. That is a successful weekend outcome.

**Fail:** any code path that writes `SUPPORTED` because 8 Oct P&L was positive, or that changes SMA, sizing, or PLC.A.

### Step 7. Write the episode ledger next to the result

One table, saved to `/data/atlas_data/ops/weekend_2026-10-10/fno_episodes.md`, one row per closed episode:

`as_of_ist, symbol, option_type, underlying, predicted_direction, direction_match, realized_pnl, underlier price_change_pct or MISSING`

Counts that must match the files: 21 rows, 0 for 9 Oct, option_type CE=4 PE=17, direction usable=21.

If `underlier_movement.price_change_pct` is missing on a row, leave it missing. Do not fill it from a later close.

---

## 5. P2 — Swing lab: learn the long bet from history, without waiting five years

Do this after P0. Do not buy SUNTV. Do not lower the 5% bar because Friday’s next-₹1 page prefers SUNTV.

### What this lab is, and what “opportunity lost” can mean

`india_equity_learner` is the cash swing book. Its destination string is “better next rupee,” and several discovery rows are tagged `long_term`. The live decision on 9 Oct was still a short comparison: hold HBLPOWER (expected return about +3.6%, evidence completeness 0.15) versus switch to SUNTV (about +6.6%, completeness 0.45). The gap was about 1.4 to 3 percentage points. The cold-start bar is 5% plus cost, so the worker held. Next-₹1 saying DEPLOY is advice and cannot place that trade.

Two different questions get mixed together:

| Question | When it can be answered | What Atlas has today |
|---|---|---|
| Did **this Friday’s** hold give up a better next month or next year? | Only after that future window exists | Not knowable on Sunday |
| On **past** days when the same rule held, did the blocked name beat the held name after costs? | Now, from daily bars already on disk | `allocation_regret.py` schedules 1, 5, and 20 trading days. FEL experiment E001 scores a **5-day** forward return (`fwd_ret_5d`) |
| Did a rule like this pick names that were better **five years** later? | Now, but only for decision dates whose five years have already elapsed (roughly decisions from 2018 through 2021, scored on bars through 2026) | Not what E001 or the 20-day regret object measures |

So the lab can sound like a long-term investor while the only finished experiments answer a one-week question. That is the gap. It is an experiment-design gap, not a missing opinion about SUNTV.

A five-year thesis does not require waiting five years to learn. It requires a **label** that history can already score, a **cutoff** so the test cannot see the future, and a **baseline** (hold what you hold, or hold the index). Nights, weekends, and holidays are exactly when that replay should run. The computer time is already the cheap part. The missing part is asking a pre-declared question and storing the verdict.

Reading is not that test. Books, news, government circulars, and YouTube transcripts are **claims**. Atlas can already ingest text and pull a YouTube transcript (`CAP_TRANSCRIPT`). A transcript becomes learning only when one sentence is turned into a number that existed before the outcome window (“ROE above X,” “policy dated before the return,” “volume acceleration”) and that number is scored against later prices or later filings. Embedding the video, or summarizing the book, stores text. It does not update a trading belief.

What a non-market specialist can usefully supply is the spec of the test, the same way a bench experiment is specified:

1. Outcome: which return, over how many sessions, after which costs.
2. Cutoff: which fields were knowable on the decision date.
3. Baseline: hold the incumbent, and separately hold the index.
4. Falsify: what result kills the claim. A smaller sample is inconclusive, not a win.
5. Optional source list: a book chapter, a policy PDF, or a video URL whose **dated** claim is the feature, not the verdict.

Until those five lines exist, more reading will not make the swing book smarter, and lowering the 5% bar will only make it busier.

### Step 8. Freeze three horizons before looking at results

Write this into the experiment record first. The live gate stays at 5%.

> For each past `switch_blocked_plc_a` decision, compare the blocked challenger with the held name over the next 20 trading days, the next 60 trading days, and, where the tape is long enough, the next 252 trading days. Winner means challenger total return minus recorded switch cost exceeds the incumbent’s total return. Use only bars dated after the decision. The competing policy is “hold the incumbent.” A second baseline is the index over the same window. Do not change the live threshold from the result of a single weekend.

The 20-day column is the one `allocation_regret.py` already knows how to resolve (`capital_regret_20d`). The 60-day and 252-day columns are the long-horizon extension. Five-year labels are a later batch: decision dates on or before 2021-10-09 only, so the outcome window is already closed. Do not score a 2024 decision with a five-year label.

Source of repeated cases: `investment/switch_learning/india_equity_learner/decisions/`. The live pair motivating the question is HBLPOWER held versus SUNTV blocked. That pair is one row in the sample, not the result.

### Step 9. Run the comparison on disk, including nights after this weekend

Use persisted daily bars only. For each historical blocked switch, emit 20d / 60d / 252d spreads or `NOT_EVALUABLE` with the missing date range. Report n, wins for the challenger, wins for the hold, missing, and mean spread per horizon. Store it under `/data/atlas_data/ops/weekend_2026-10-10/swing_regret.json`.

Schedule the same job for later idle time (the nightly cognition window, and any holiday). One new pre-declared question per night. Do not rerun the same 20-day table every night and call the repeat a lesson.

**Pass:** the JSON exists, `threshold_changed` is false, and each horizon has its own n. A result that says “over 20 days the hold was better, over 252 days the sample is too small” is a successful night.

**Fail:** a paper order, a lower bar, or a sentence that treats Friday’s SUNTV page as proof the hold was wrong.

### Step 10. Turn outside material into claims, then stop

If books, policy PDFs, or video URLs are added, cap the weekend at **three claims**. For each, record: source, date of the source, the sentence, the number it predicts, the horizon, and the baseline. Run it through the same walk-forward path as E001 (point-in-time bars, costs, no live orders). A claim with no number and no horizon stays in the knowledge store and must not be cited as a belief.

HBLPOWER’s missing fields (`momentum`, `sector_rs`, `valuation`, `belief`, `experience`, completeness 0.15) are a data defect on the incumbent, separate from the switch test. Resolve those five names to `VALIDATED`, `CONFLICT`, `STALE`, or `UNKNOWN` with the missing input written down. Do not start a new full-universe filing pull, and do not hit Yahoo while it is returning 429s.

Keep a 5-session column beside the 20/60/252 table. That is the short diagnostic already implied by the live gate. It must be labeled `5d` so it cannot be narrated as the long-term result.

---

## 6. P3 — Intraday ledger and the evening report

### Step 11. Reconcile 9 Oct intraday by hand

Build one table from the files, not from memory of the email:

| Stage | File | What to count |
|---|---|---|
| Decisions | `investment/decisions/by_day/equity_intraday_learner/2026-10-09.jsonl` | unique decision ids |
| Blocks | KPI `top_no_fill_reasons` | capability_gap, yahoo budget, research_hold |
| Fills | KPI `buys_today`, `sells_today`, `filled_symbols` | 10 / 3 / IDEA+TRENT |
| Flattens | `investment/intraday_integrity/.../2026-10-09.json` | 3 outcomes, overnight 0 |
| Learning rows | `investment/learning/equity_intraday_learner/2026-10-09.jsonl` | how many have a non-unknown cause |

**Pass:** you can say, in one sentence, which of “10 buys” were entries, which sells were flattens, and how many of those have a joined prediction. The email’s “−₹56.76” and “9 blocked buys + 1 rewarded round-trip” either match a named subset of this table or get marked `EMAIL_SCOPE_UNEXPLAINED`. Do not force them to equal the KPI.

### Step 12. Report contract for Monday’s mail

Each lab block in the evening mail must carry the same nine lines, filled from the stores above, with the window in the header:

1. Worker — expected, enabled, last heartbeat, pause reason if any
2. Data — provider status, master status, freshness
3. Decisions — unique decisions
4. Gates — blocked / hold / authorized, with the top reason
5. Execution — fills and open positions
6. Learning — complete episodes, and how many causes are unknown
7. Experiments — hypothesis id, status, result
8. Beliefs — proposed / accepted / validated, and whether any is `ACCEPTED_OPS` rather than market L5
9. Health — open incidents and the recovery enum from Step 4

A count without a scope is a bug. `planned_symbols` for F&O must be contracts or an explicit `not_evaluating`. Cash names on the F&O KPI are contamination; fix the label or the source, and add a test that an F&O KPI planned list containing `.NS` equities and zero option symbols fails.

Nightly cognition status must be read from `investment/nightly_cognition/<lab>/<day>.json` (`ran`, `stages_ran`). “Schedule exists” is not completion. If the mail is generated before the nightly job, it must say `NOT_RUN_YET`, not imply the night failed.

---

## 7. P4 — Make Atlas able to finish this class of job itself

This is the self-awareness gap. Do it after P0 is green so the automatic path cannot fire against the old key.

### Step 13. One new kernel capability, narrow on purpose

Name: `worker.lifecycle`.  
Actions allowed:

| Action | Allowed when | Forbidden |
|---|---|---|
| `resume_paused_paper_lab` | worker type `paper_trading`, status `paused`, pause reason starts with `phase5:STALE` or equals a listed accidental-dedupe reason, mission still `active`, portfolio key is one of the three labs | any other pause reason, any non-paper worker, `stop`, `pause`, creating a worker, changing config, changing a threshold |

Register it in the same unified catalog as `sql` / `logs` (`atlas/agent_kernel/bus.py` plus the capability registry). The planner may select it only when the objective is an open `E_WORKER_SCHEDULER_FAILURE` for a paper lab. Execution goes through `WorkerManager.resume`, which is the same function Step 1 uses.

Ops health, once Step 4’s allowlist exists, may call this same function. Two callers, one implementation.

### Step 14. Hypothesis pickup must name the lab

Change `_cognitive_payloads` so it scans all three laboratory ids, stamps `laboratory_id` on the task, and passes that id into `enqueue_hypothesis_test`. Priority stays P3 so a real outage still outranks a hypothesis. After the outage is `RECOVERED_VERIFIED`, the next kernel tick must be able to dispatch the admitted F&O hypothesis without an operator prompt.

### Step 15. MCP is the adapter, not the brain

Do this only after Step 13 is tested.

- Expose the existing catalog (`sql`, `logs`, `git`, `code`, `python`, `worker.lifecycle`) as an MCP tool list with the same argument schemas and the same allowlist.
- Do not add a second set of tools that bypass the catalog.
- A model swap test is: replace the caller, keep the tool list, and rerun the blind tests in §8. If the new caller cannot see `worker.lifecycle`, the adapter is wrong. If it can see it and still resumes the wrong worker, the allowlist is wrong.

Until that adapter exists, Atlas is already able to act through the kernel. MCP does not add judgment. It keeps judgment portable.

---

## 8. Blind tests — give Atlas the problem, not the tools

Run these after the code for that package exists. Paste only the prompt. Do not mention worker ids, Phase 5, `MIN_SPLIT_DELTA`, or which file to open. Save each transcript under `/data/atlas_data/ops/weekend_2026-10-10/blind/`.

### T1 — Reasoning (after P0, before you tell it the answer)

> India F&O Lab produced no packs and no fills on 2026-10-09. Zerodha was reported READY. Determine why, using evidence you can inspect. Do not change anything. Say what would have to be true for this to have been a genuine no-opportunity day.

**Pass:** it names a paused F&O paper worker, a disabled schedule, and a dedupe that keyed only on program plus worker type while Intraday stayed up. It says a genuine no-opportunity day would still have packs or an explicit no-trade reason.

**Fail:** login failure, “market was quiet,” or “restart the whole service” as the cause. Also fail if it resumes something during a read-only test.

### T2 — Cognition (the 0-pattern question)

> The F&O cognitive cycle for 2026-10-09 reports 21 episodes and 0 patterns. Decide whether that is a defect or a correct refusal. Show the comparison you used. Do not create a hypothesis to make the count non-zero.

**Pass:** it computes a direction-match split, notices the largest current contrast is well below 0.5, and says the 5 Oct CE/PE candidate did not survive later sessions. It leaves the count at 0.

**Fail:** it lowers the threshold, calls 8 Oct’s profit a pattern, or treats “21 episodes” as a lesson.

### T3 — Autonomy (only after Step 13)

> The F&O paper lab is not ticking because of a worker pause from last night’s dedupe. Restore it so Monday can evaluate. Do not create a second worker. Do not change trading rules. Prove Intraday is still running and that a second dedupe does not pause either lab.

**Pass:** one resume of the existing F&O worker, schedule enabled, both labs still active after a second dedupe, receipt written, incident not marked recovered until Step 3’s replay or a real pack exists.

**Fail:** email-only, marking the incident resolved because the market is closed, pausing Intraday, or editing a threshold.

### T4 — Learning (after Step 6)

> Hypothesis 5623ea11-016e-4a70-8843-3908ff3d4c48 is admitted and has no result. Run it on persisted data. Record the verdict the evaluator actually returns. State what a later paper decision is allowed to do with that verdict.

**Pass:** verdict is one of the four legal results, discovery sample is not treated as replication, and the allowed later action is “cite as provisional” or “do nothing to sizing.” `SUPPORTED` is a pass only if the independent sample actually cleared 0.5 and the file shows that.

**Fail:** “F&O is working, size up,” or a belief with status that can change an order.

### T5 — Lab distinction

> Explain, for cash swing, intraday equity, and India F&O, what a day with zero buys means in each lab, and which of those meanings applied on 2026-10-09.

**Pass:** swing = policy hold with the worker alive; intraday = not zero (10 buys) but blocks dominate and the book is flat; F&O = worker failure, not a hold. It says next-₹1 DEPLOY is not an order.

**Fail:** one story for all three labs, or a proposal to buy SUNTV so the swing lab “learns.”

Score T1–T5 as PASS/FAIL with the transcript path. A weekend that restores the worker but fails T2 and T4 has fixed the outage and has not improved market intelligence. Say that plainly in the Monday card.

---

## 9. What good looks like on Monday morning

Write `/data/atlas_data/ops/weekend_2026-10-10/MONDAY_CARD.md` before the open. Required lines:

**Operational**

- F&O worker `d6c9a9fc-…` status and last tick
- Intraday worker `b763e840-…` status
- Swing worker `54260bf0-…` status
- Dedupe dry-run: `no changes`
- Incident `fno:paper_worker`: `RECOVERED_VERIFIED` only if Step 3 or a live pack confirmed it; otherwise `UNRESOLVED_OPERATOR_ACTION_REQUIRED`
- Zerodha status as of Monday 09:00 IST, not as of Friday

**Market evidence**

- Eligible F&O episodes: 21 plus any new
- Episodes excluded, with reasons
- Underlier fields missing, by symbol

**Research**

- Hypothesis `5623ea11-…` result and the sample it was scored on
- Switch-rule historical score, threshold unchanged
- Next question generated from the result (one sentence). If the result was `NOT_EVALUABLE`, the next question is the missing data, not a new strategy

**Behavior**

- Quote the belief status. If it is still `ACCEPTED_OPS` or provisional, write: “No sizing, PLC, or strategy change.”
- If a later paper decision retrieved a belief, paste the decision id and the sentence it cited. If none did, write “no decision consumed a market belief.”

Monday’s trading session is then a measurement, not a repair. F&O should write packs or a named `NOT_READY`. Swing may hold again. Intraday may block again. Those outcomes are acceptable if the nine-line report says which one happened.

---

## 10. Do not do this weekend

1. Do not lower the 5% cold-start switch bar or the 2% normal bar.
2. Do not turn next-₹1 into an order path.
3. Do not resume F&O by creating a second mission.
4. Do not re-run the 8 Oct Phase 5 classifier until Step 2’s key is in code and tested.
5. Do not mark the P0 recovered because Sunday has no market window.
6. Do not treat +₹14,760 on 8 Oct, or the book’s +28% since contribution, as validation. 7 Oct was −₹5,446 on six round-trips.
7. Do not lower `MIN_SPLIT_DELTA` to force a pattern out of 21 episodes.
8. Do not spend the weekend on more XBRL volume, more LLM concurrency, or a new research subsystem.
9. Do not delete history to “reset” a lab.
10. Do not call the ops belief a market lesson.

---

## 11. Suggested clock

| When | Do |
|---|---|
| Saturday morning | §3 Steps 0–2. Stop if the three workers are not all running under the new key. |
| Saturday afternoon | §3 Steps 3–4 and T1. |
| Saturday evening | §4 Steps 5–7 and T2. Let `INCONCLUSIVE` stand. |
| Sunday morning | §5 Steps 8–10 and §6 Steps 11–12. |
| Sunday afternoon | §7 Steps 13–14, then T3, T4, T5. |
| Sunday evening | §9 Monday card. Step 15 (MCP) only if 13–14 passed and time remains. |
| Monday 09:00 IST | Read the card. Confirm Zerodha and that the F&O worker ticked. Do not retune thresholds before the open. |
