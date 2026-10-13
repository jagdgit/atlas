# Decision → Evidence → Outcome → Learning Integrity Plan

> **Status:** LOCKED FOR START — review #2 applied 2026-10-12 20:55 IST. Read-only steps
> (0A, 1, 1B) may begin. No code changes yet; Step 0B must land before the next deploy.
> **Date:** 2026-10-12
> **ID:** `OI-DELI0` (Decision–Evidence–Learning Integrity) · single implementation tracker (D6)
> **Builds on:** [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md),
> [`2026-10-06_COGNITIVE_LOOP_C1_PLAN.md`](2026-10-06_COGNITIVE_LOOP_C1_PLAN.md),
> [`2026-10-08_AUTONOMOUS_SELF_DIAGNOSIS_V1_PLAN.md`](2026-10-08_AUTONOMOUS_SELF_DIAGNOSIS_V1_PLAN.md)

---

## 0. Bottom line

Atlas has the right building blocks: decision packets, a capability registry, entry
predictions, experiences, learning stories, and a provisional-vs-validated distinction.
They are **not connected into one chain**. As a result:

- activity counts look large (4,649 LLM inferences, 41 experiences, 9 stories);
- what matters is zero (0 validated lessons, 0 belief revisions, 0 evidence-backed
  causes, 0 validated advice contributions);
- reports disagreed (F&O day P&L +₹22,319 in the ledger vs +₹1,822.50 in the EOD mail).

**Governing rule (applies to every step and every record):**

> Atlas must never confuse a missing record with a known fact, a profitable outcome with
> a validated explanation, or recorded activity with demonstrated learning.

**Goal:** every important decision is explainable; every explanation traces to evidence
that existed at decision time; every claimed lesson has a validation status; every
promoted lesson is tested for whether it improves the next decision.

**Non-goals:** more LLM calls, more learning stories, more paper trades, AtlasNet/NN
training, higher Yahoo request rates, live broker orders, any change to the control
strategy to make a trace or check "pass".

**Hard constraint:** paper trading continues normally throughout (§2).

---

## 1. Verified findings (live machine, 2026-10-12)

| # | Finding | Evidence | Status |
|---|---------|----------|--------|
| F1 | EOD mail F&O "Today P&L +₹1,822.50" was wrong; ledger is **+₹22,319.00** (8 PE round trips) | Old `_add_cash_and_pnl_metrics` on `recent_trades[:10]` of the newest-first ledger reproduces 1,822.50 exactly | Root cause found; fix live, uncommitted (§1.1) |
| F2 | F&O/intraday KPI `day_pnl` was `null` on flat EOD books; lifetime `fees_paid` (₹603.26) leaked into the day scorecard | `market/trading_kpis/*/2026-10-12.json` before rewrite | Fixed; today's KPI files rewritten |
| F3 | F&O option buys link to an engine decision that says **HOLD** the underlier | `sim.trades.decision_id` → `decision.decisions.why` = "Chose 'hold' … no actionable signal" for all 8 PE buys | Open — causal-chain defect |
| F4 | The F&O entry reason exists only in a side file | `investment/fno/lab_v1_predictions/NIFTY26OCT22550PE.json`: "Control SMA margin −0.0309 → long ATM PE; E[R]=8% over session_flat" | Open |
| F5 | The engine said HOLD and the overlay said BUY PE for the same tick | Same `decision_id` `0cb0d567…` | Open — overlay is a CONTROLLED_EXPERIMENT (D3) |
| F6 | All 8 F&O sells have `decision_id = NULL` | `sim.trades`; `paper_trading.py` passes `decision_id=None` at several exit call sites | Open |
| F7 | Entry predictions stored one file per contract symbol | `lab_v1_predictions/<CONTRACT>.json` | Re-entry overwrites the earlier record |
| F8 | F&O prediction is a fixed default (E[R]=0.08, p=0.7, "up" = premium up) for every contract | All 8 experiences | Not a calibrated forecast; must not support a validated claim |
| F9 | F&O stored attribution: 4/8 `partial`, 4/8 `evidence_backed` (daily underlier move only); IV, Greeks, timing, news always unknown | Experience `attribution.causal_factors` | Labels overstate what the evidence establishes (§4.1) |
| F10 | TRENT had a full engine "why" (SMA10 > SMA30, margin +0.68%, RSI 63.4); mail and session notes truncate it with `…` | `decision.decisions.why` vs session-note samples | Open — presentation + linkage |
| F11 | TRENT cause `unknown_explicit`; all lesson fields null except relative-opportunity | Learning story | Honest; no lesson exists |
| F12 | Fill mail shows a short tick summary and a few decision fields only | `atlas/investment/reports.py` `format_trade_report` | Open |
| F13 | HBLPOWER shown at mark ₹760 = average cost; timeline ≈ ₹719.05 | EOD report | Hypothesis: avg-cost fallback. Verify, do not assume |
| F14 | "Price coverage 100%" next to "ranking not yet trustworthy" | EOD report | Metric conflates universe scan with decision-ready data |
| F15 | 55 autonomous investigations: 6 resolved, 45 failed, 0 new hypotheses | EOD report | No terminal state or next action |
| F16 | 0 decide-time LLM rationales; 692 advice joins, 27 "useful", 0 validated | `decide_rationale/`, learning audit | "Useful" undefined; no baseline |
| F17 | **Two Atlas instances, 18:36–20:39 IST.** A hand-started `atlas serve` held port 8000; systemd (`Restart=always`) relaunched its copy **173 times**. Each copy started scheduler + workers, logged "Atlas is ready", then died on `Errno 98`, i.e. ≈ 30 s of live scheduler per launch | `journalctl -u atlas`; boot order `atlas/cli/main.py:393` → `atlas/kernel/application.py` | Contained 20:39 (systemd PID 1233554 only). 0 fills since 18:36; 0 emails in `atlas.log`. No guard exists. Full audit = Step 0A |
| F18 | **Fee semantics of the ledger** (read from `atlas/trading/portfolio.py::apply_trade`): buy fee is taken from cash but **excluded from `avg_price`**; buys book `realized_pnl = 0`; a sell books `realized_pnl = (price − avg) × qty − sell_fee`. So stored realized P&L is **net of exit fees only**; entry fees appear in cash/equity, never in `realized_pnl`. Index-proxy lots use a different cash path (`close_cash_credit`) | Code read 2026-10-12 20:50 | Locked into the accounting contract (§4.2). Consequence: today's P0.1 flat-book fallback (Σ sell `realized_pnl`) omits entry fees. Harmless under zero-fee `paper_demo`, wrong under any fee profile → fixed in Step 4 |

### 1.1 Code already changed today (before this plan)

Uncommitted and live since the 20:39 systemd start:

- `atlas/workers/investor_reports.py` — `_add_cash_and_pnl_metrics` uses the full day
  ledger, falls back to same-day realized P&L on flat books, adds `fees_paid_today`.
- `atlas/investment/trading_kpis.py` — recomputes `day_pnl` from today's trades when
  missing; day scorecard uses day fees.
- `atlas/api/routes.py` — ledger endpoint computes `day_pnl` without requiring open marks.
- `tests/test_day_pnl_round_trip.py` — 2 new tests (23 related tests pass).

Approved to commit (D1) via Step 2. Known limitation: F18.

---

## 2. Trading continuity guardrails

1. **Additive first, shadow before enforce.** New checks ship `off` → `shadow` (compute,
   log, report; never alter a decision or fill) → `enforce`, per lab, in
   `config/defaults.yaml`. Default `shadow`.
2. **Never fail a fill on new code.** New writes are wrapped like the mail path; a
   failure follows §4.3 (integrity failure record), and the trade proceeds.
3. **No schema-breaking migrations during market hours.** Additive only, after 15:45 IST
   or weekends.
4. **No change to control-strategy behaviour** (`sma_cross_rsi.v1`, PLC exits, F&O lab v1
   sizing). D4 policies are future gates, applied only after shadow review.
5. **Restarts:** only through `systemctl`, by the operator, after 15:45 or before 08:45 IST.
   **Agents never kill and relaunch Atlas** (A20). **No restart is needed for Steps 0A,
   1, 1B** — do not restart to begin them.
6. **No deploy before Step 0B.** The first deploy of Step 0B itself is done by the operator
   with the drill in §9.4.
7. **Post-deploy smoke (next session):** ≥ 1 decision tick per lab, F&O pack readiness
   passes, fills still mailed, no new `task_failures` category, single instance confirmed.
   Regression → flag `off`, debug offline.
8. **Shadow → enforce** needs ≥ 3 sessions of reviewed shadow output, per lab
   (intraday → F&O → swing).
9. **Kill switch per phase** (`integrity.<phase>.enabled`) without code rollback. The
   single-instance lock has a separate, operator-only emergency override (§4.6).

---

## 3. Execution order (locked)

| Step | Deliverable | Exit condition | Restart? |
|------|-------------|----------------|----------|
| **0A** | Read-only audit of the 18:36–20:39 duplicate-instance window → `docs/incidents/2026-10-12_DUPLICATE_INSTANCE_AUDIT.md` | Scheduler claims, task failures, mail idempotency, Zerodha token-mail handling, DB writes, file writes in the window examined and documented | No |
| **1** | `scripts/trace_trade.py` + `docs/traces/2026-10-12_NIFTY26OCT22550PE_70109538.{md,json}` | Every cell sourced or marked MISSING / CONFLICT / AMBIGUOUS / CALCULATED / LOG_ONLY / NOT_APPLICABLE; ≥ 5 cells hand-verified | No |
| **1B** | TRENT trace + most recent closed equity-swing trace | Same procedure; actual trade dates recorded | No |
| **2** | Isolated P0.1 commit (§9.5) | Only approved hunks + documented minimum prerequisites committed; tests pass | No |
| **3** | Decision gate (§9.6) | Shared first implementation target named from the three traces; post-gate priorities recorded | No |
| **0B** | Single-instance protection (§4.6, §9.4) | Ownership model documented; I1–I13 pass; operator drill passes | Yes (operator, after 15:45) — **required before any deploy** |
| **4** | P0.2 accounting source + P0.3 reconciliation (§9.7, §9.8) | All consumers follow §4.2; mismatches surface as findings, never silent overwrites | Yes (after 0B) |
| **5** | P0.4 lineage (+ order intent) then P0.5/P0.6 decision chain; entry-evidence persistence | New fills have required records **or** explicit integrity failure (§4.3) | Yes (after 0B) |
| **6** | Decision-ready market data (P1) | Evidence states, timestamps, per-field freshness rules, per-lab requirements | Yes |
| **7** | Causal learning (P2) | Attribution and candidate lessons consume the trusted chain; nothing invented | Yes |
| **8** | Evaluation and promotion (P4) | Pre-registered experiments decide whether a finding improves decisions after costs | — |

Changed because (2026-10-12 Step 3): Steps **2** and **3** are non-deploy (commit + plan edit) and may run before **0B**. Step **0B** remains the hard gate before any subsequent deployment or restart. Deployed lineage/accounting changes (4–5) start only after 0B.

---

## 4. Locked contracts

### 4.1 Record vocabulary

**Cell status** (one per traced field, A1):
`OK` · `MISSING` · `CONFLICT` · `AMBIGUOUS` · `CALCULATED` · `LOG_ONLY` · `NOT_APPLICABLE`.
`CONFLICT` and `AMBIGUOUS` are statuses, not gap classes.

**Gap class** (only on non-OK cells; the cause type):

| Class | Meaning |
|-------|---------|
| `PERSISTENCE` | Required data was never durably captured, or was overwritten |
| `LINKAGE` | Data exists durably but is not connected to (or is wrongly connected to) the trade's chain |
| `COMPUTATION` | Inputs are right but a stored derived value uses the wrong formula (e.g. return denominator) |
| `ATTRIBUTION` | Evidence is linked but the explanation ignores it, is circular, or overstates it |
| `LEARNING` | No defined hypothesis, test, or validation |

**Dimension** (where the cell sits in the dependency chain; used by the first-fix rule):
`IDENTITY` → `ACCOUNTING` → `DECISION_LINKAGE` → `DECISION_EVIDENCE` → `ATTRIBUTION` → `LEARNING`.

**Attribution state** (describes the evidence, not profitability):

| State | Rule |
|-------|------|
| `NOT_EVALUABLE` | No observation that could distinguish the proposed cause from alternatives (e.g. no entry-to-exit underlier path, no IV) |
| `PARTIAL` | Some relevant evidence exists; material alternatives unresolved |
| `EVIDENCE_SUPPORTED` | Explanation supported by identified evidence, alternatives (market, sector, IV, time decay, execution) considered |
| `CONTRADICTED` | Evidence conflicts with the proposed explanation |

The outcome itself (e.g. "premium rose") is never a cause. A profitable round trip with
`NOT_EVALUABLE` attribution is an honest, valid record.

**Prediction contract** (A23). Every prediction record carries:
`prediction_type` ∈ {`rule_output`, `forecast`, `risk_estimate`, `execution_assumption`} ·
`target_variable` · `horizon` · `prediction_time` · `model_or_rule_version` ·
`calibration_status` ∈ {`uncalibrated_default`, `uncalibrated_model`, `calibrated(<test id>)`}.
Historical fixed defaults (F8) are kept for audit, labelled `uncalibrated_default`, and
cannot support a validated claim. `sma_margin = −0.0309 → buy PE` is a `rule_output`, not
a forecast.

**Three evaluation dimensions** (A26), kept separate in every learning record:

1. **Process quality** — did the decision follow its rules and use the required evidence?
2. **Forecast quality** — did a defined forecast match the outcome over its horizon?
3. **Economic performance** — did the strategy beat its baseline after costs and slippage?

### 4.2 Accounting contract

**Ledger semantics (F18, verified):**

| Event | Cash | `avg_price` | `realized_pnl` |
|-------|------|-------------|----------------|
| Buy | − (qty × price + fee) | gross-weighted, **fees excluded** | 0 |
| Sell | + (qty × price − fee) | unchanged (or position deleted) | (price − avg) × qty − **sell fee** |
| Index-proxy lot | `open_cash_debit` / `close_cash_credit` paths | as above | as above |

**Definitions (formula version `acct.v1`):**

| Metric | Definition | Authority |
|--------|-----------|-----------|
| `realized_ledger` | Σ `sim.trades.realized_pnl` of sells (exit-fee net, entry fees excluded) | **Authoritative reported value** (A3). Never overwritten |
| `fees_by_fill_day` | Σ `fee` of all fills whose IST date is the day, both sides | Each fee belongs to its fill's IST date; never moved to the exit date |
| `round_trip_net` | `realized_ledger` of the exit − entry fees allocated to the exited quantity | Reported separately, `CALCULATED` |
| `return_on_cost` | `round_trip_net` ÷ (exited qty × avg entry price + allocated entry fees) | Formula `roc.v1` (A4) |
| Allocation | Average-cost, pro-rata by quantity, matching the ledger's own avg-cost model (partial exits, multiple entries) | Same as ledger |
| `day_pnl` | Change in equity over the IST day excluding cash movements, reported with components: (a) realized on today's sells measured from the **prior close** for lots held overnight, from the fill price for lots opened today; (b) mark-to-market change on positions open at day end; (c) fees of today's fills. Each fee counted once | If a needed prior close or current mark is missing, that component is `UNKNOWN` and `day_pnl` is `partial` with the known components shown. Never fabricated |

**Accounting truth vs evaluation truth:** the paper ledger (`paper_demo`, zero fees) is
accounting truth and is labelled "zero-fee paper result". Strategy evaluation uses a
separate, versioned realistic-cost profile, chosen **before** evaluation starts (D5, A17).

**Acceptance for P&L:** one authoritative ledger value · an independent recomputation as
a check · an explicit finding on any mismatch · identical values across KPI, EOD mail,
API, and learning consumers for the same metric and time window. Recomputation is not
required to equal the ledger until both semantics are documented (they now are, above).

**Step 4 implementation invariant (F18 — no double-subtract of exit fees):**

1. Start from stored sell `realized_pnl`, which is **already net of the sell fee**.
2. Account separately for **entry fees** not already reflected in that realized figure
   (entry fees are cash-only today; they are not in `avg_price` or sell `realized_pnl`).
3. Count each fee **exactly once**, including for partial exits and overnight positions
   (pro-rata allocation of entry fees by exited quantity; fee day = fill IST date).
4. Test with a **non-zero-fee fixture** in `tests/test_pnl_truth.py` (not only
   `paper_demo` zero fees). A wrong implementation that subtracts `fees_day` again from
   Σ sell `realized_pnl` must fail that test.

### 4.3 Acceptance populations and failed writes

| Population | Rule |
|------------|------|
| **Historical trades** (before Step 5 deploy) | Trace reproduces what exists, flags missing/contradictory data, identifies the first fix. Nothing is invented or back-filled to look complete |
| **New trades** (after a fix deploys) | Required records persisted and linked, **or** an explicit integrity failure exists |
| **Failed non-blocking write** (A25) | 1) trade proceeds unchanged; 2) integrity counter + structured failure record (`investment/integrity/write_failures/<day>.jsonl`); 3) trade marked `lineage_incomplete`; 4) reconciliation lists it; 5) EOD discloses it. A later retry may repair a link only from sufficient source data; never reconstruct a rationale from the outcome |

Replacement acceptance criterion for lineage: **every new trade has its required records
or an explicit, detectable integrity failure. Historical gaps stay visible.**

### 4.4 Evidence classification

Classify each observation by what it actually establishes:

| Observation | Establishes | NIFTY trade status |
|-------------|-------------|--------------------|
| Daily bar `_NSEI` 2026-10-12 (O 22,657 · C 22,383.1; prior close 22,612.6) | **Session context**: open-to-close −1.21%, close-to-close −1.02% (both `CALCULATED`, labelled) | `OK` as context |
| Underlier move between entry fill and exit fill | Requires entry- and exit-time prices or intraday bars | `MISSING(PERSISTENCE)` |
| Entry-time spot / ATM / LTP snapshot | Requires the pack as of entry | `MISSING(PERSISTENCE)` (overwritten) |
| Strike 22,550 | Contract identity; context hint about the ATM at entry | `OK` as identity; **not** a spot quote (A7) |
| IV, Greeks | Never captured | `MISSING(PERSISTENCE)` |
| Stored attribution saying "no durable underlier session bar" | False: the session context existed but the attribution lookup did not find it | `LINKAGE` on the attribution-input cell only |

`MISSING(LINKAGE)` is used only when the evidence that answers the question exists but is
not connected. A daily bar is not a linkage failure for an intraday-path question.

**Freshness rule per critical field** (A24), configured per strategy and field, never one
universal threshold: market session · maximum age · provider timestamp · ingest timestamp ·
price type (`live`/`delayed`/`close`/`fallback`/`stale`) · behaviour when timestamp or
source cannot be verified. F&O (once enforced): missing fresh underlier or option LTP →
entry ineligible; IV optional but visibly missing, never defaulted.

### 4.5 Completeness metrics (A29)

Each metric has a named population and denominator; "100%" never excludes unlinked fills.

| Metric | Population (denominator) |
|--------|-------------------------|
| Fill → decision linkage | All fills in the window |
| Fill → prediction linkage | All entry fills of labs that require predictions |
| Decision-time evidence completeness | All entry decisions × required critical fields (per strategy) |
| Exit-trigger completeness | All exit fills |
| Outcome reconciliation | All closed round trips |
| Attribution evaluability | All closed round trips (share not `NOT_EVALUABLE`) |
| Candidate lessons with defined tests | All candidate lessons |
| Validated findings | All candidate lessons |
| Findings passing promotion | All validated findings |

### 4.6 Single-instance ownership model (A18–A22)

| Layer | Owner | Mechanism | Failure behaviour |
|-------|-------|-----------|-------------------|
| **L1 process lock** | The `atlas serve` process, for its lifetime | `flock(LOCK_EX|LOCK_NB)` on `/data/atlas_data/run/atlas.lock`. File created once (`O_CREAT`, mode 0640) and **never unlinked, renamed, or replaced**; diagnostics (pid, start time, `INVOCATION_ID`, git sha, host) are written through the locked fd | Held by another → one clear log line naming the holder, exit **75**, no service started |
| **L2 listening socket** | Same process | Bind the listening socket **before** `app.start()`; hand the bound socket to uvicorn. A "port is free" check alone is not used (race) | Bind fails → exit 75 before any service starts |
| **L3 per-service DB locks** | Each side-effecting singleton service: scheduler, paper-trading worker, investor mailer, Zerodha token-mail poller (final list from Step 0B side-effect inventory) | Each service opens its own dedicated DB connection and holds `pg_try_advisory_lock(<service key>)` for its lifetime. Instances of the same service contend for the same key | Not acquired → service stays passive (no ticks, claims, fills, mails) and raises an incident |
| **Side-effect proof** | The service that owns the lock | A side effect (task claim, fill, mail send, IMAP state change) executes only inside the owning service, which checks **its own** lock connection before acting (`SELECT 1` on that connection; connection loss = lock lost). No other connection "checks" a lease it does not hold | Lock lost → stop side effects, try to reacquire, incident if not reacquired |
| **L4 systemd** | Unit `deploy/systemd/atlas.service` (repo) → `/etc/systemd/system/` | `RestartPreventExitStatus=75`; `StartLimitIntervalSec=300`, `StartLimitBurst=5`; `Restart=always` kept for real crashes | Conflict does not crash-loop |
| **L5 manual start** | Operator | Outside systemd (no `INVOCATION_ID`) `serve` refuses unless `--manual`; `--manual` still takes L1–L3 | — |
| **L6 detection** | `scripts/ops_watchdog.py` | Exactly one `atlas serve`; L1 holder pid = systemd `MainPID`; no `Errno 98` in the interval; each L3 key held by that pid's connections | Violation → P0 incident + mail |
| **L7 idempotency** | Scheduler / paper trading / mailer | Verified by tests: one fill per (lab, decision tick, symbol, side); one mail per (kind, lab, day[, hour]) | Duplicate attempt → no-op + counter |

**Emergency override** (replaces `ATLAS_INSTANCE_LOCK=off`):
`ATLAS_INSTANCE_LOCK_OVERRIDE=I_CONFIRM_SINGLE_INSTANCE`, set only by the operator in
`/etc/atlas/atlas.env`. It disables **only L1** (e.g. lock path broken); L2 and L3 stay
enforced. Atlas logs CRITICAL at boot and hourly; the watchdog raises P1 while it is set.
Safe-use condition: operator has confirmed no other instance exists on this host or any
host using the same DB. Agents may not set it.

Verified facts for L1: `/data/atlas_data` is local ext4, owned by `jagd`; the unit runs
as `User=jagd` with `ReadWritePaths=/data/atlas_data`; `run/` does not exist yet and is
created by Step 0B (one-time, mode 0750).

---

## 5. Phases (scope; detailed steps in §9)

### P0 — Trustworthy learning dataset (accounting + linkage)

| Task | Detail | Mode |
|------|--------|------|
| P0.1 | Commit day-P&L fix (§1.1) | live |
| P0.2 | One accounting module implementing §4.2; KPI, EOD mail, fill mail, ledger API, learning outcome all call it; remove the parallel formula in `routes.py`; fix F18 | shadow compare → switch |
| P0.3 | Reconciliation (§9.8) | shadow → enforce on report only |
| P0.4 | `trade_lineage` record: `entry_decision_id`, `overlay_decision_id`, `parent_decision_id`, `order_intent`, `fill_trade_id`, `exit_decision_id`, `exit_reason_code`, `prediction_id`, `evidence_snapshot_ref` (+ content hash) | shadow write, §4.3 on failure |
| P0.5 | Exit decision record on every sell path (lab-v1 close, FNO-PAPER-001, EOD flatten, PLC, switches) | direct |
| P0.6 | F&O overlay gets its own decision record; engine decision becomes `parent_decision_id`; trade class `CONTROLLED_EXPERIMENT` (D3) | direct |
| P0.7 | Predictions keyed by `prediction_id`; contract file becomes a pointer; prediction contract §4.1 | direct |
| P0.8 | Horizon mandatory; missing → `horizon_unknown`, outcome not evaluable | shadow |
| P0.9 | Record kinds `FILL` → `ROUND_TRIP` → `OBSERVATION` → `ATTRIBUTED_EXPERIENCE` → `CANDIDATE_LESSON` → `VALIDATED_FINDING` | — |

**Acceptance:** §4.2 P&L acceptance + §4.3 population rules + §4.5 metrics reported.

### P1 — Decision-ready market data

Evidence-state enum on decision-packet fields (`unavailable`, `not_applicable`,
`acquired_unvalidated`, `validated`, `stale`, `conflicting`, `calculated`) · per-strategy
critical/optional field lists · per-field freshness rules (§4.4) · missing-critical policy
per D4 in shadow · price observation record (provider ts, ingest ts, instrument, price
type, age, validation, session) · investigate F13 before changing anything · coverage
split (universe / latest / fresh / history depth / decision-ready / learning-ready) ·
fundamental lineage (source → filing → parsed → normalized → calculation → validation →
use; pinned definitions) · keep Yahoo 429 suppression.

### P2 — Causal learning

Hypothesis → prediction → test → outcome → attribution → candidate as a schema · attribution
states §4.1 with `evidence_refs` and `alternatives_considered` (market, sector, IV, time
decay, execution always checked) · F&O inputs = fill-time underlier, premium, IV/Greeks when
present, time in trade · observation vs candidate vs validated finding · belief revisions
only from validated findings, with prior, evidence, test, posterior, falsifier · unvalidated
advice cannot change sizing/side (assert + counter).

### P3 — Why-buy / why-sell explanations

Depends on P0.4–P0.6. Fill mail reads `trade_lineage`: untruncated entry `why`, prediction
with its §4.1 labels, evidence states, rejected alternatives, risk controls · trade-class
banner `RESEARCHED` / `CONTROL_RULE` / `CONTROLLED_EXPERIMENT` · sell mail: trigger,
consistency with entry rule/risk policy, `round_trip_net`, attribution state · contradiction
between linked decision and fill prints `LINKAGE CONFLICT`, not a reason.

### P4 — Prove learning improves decisions

Pre-registration per hypothesis (A27), **before** looking at results: hypothesis and
falsifier · baseline and metric · point-in-time dataset and permitted features · horizon ·
minimum sample and coverage · cost/slippage profile · promotion criteria. No universal
thresholds. Results recorded as `promoted` / `rejected` / `inconclusive` / `provisional`,
never discarded. Advice evaluation table (advice id, decision id, evidence, baseline
decision, proposed change, accepted?, horizon, outcome, vs baseline, status); "useful" =
beats baseline on the pre-registered metric.

### Cross-cutting

- **Autonomous investigations (F15):** terminal state ∈ {`resolved`, `partially_resolved`,
  `capability_gap_confirmed`, `blocked_by_implementation`, `waiting_for_event`} + `next_action`;
  no retry without a changed condition; registry records the operation that would resolve a gap.
- **EOD mail:** A what happened (reconciled, zero-fee label) → B why (per trade, class,
  unverified explanations) → C learned (validated / provisional / failed / open; "NOTHING
  VALIDATED TODAY" when true) → D blockers (ranked) → E next (≤ 5, each with question,
  evidence, test, done-condition). Counters to appendix. Ships after P0.2/P0.3.

---

## 6. Decisions

| ID | Decision | Status |
|----|----------|--------|
| D1 | Keep the P&L fix; commit via worktree + hunk-level isolation (§9.5) | **Approved**, commit pending |
| D2 | First trace = `NIFTY26OCT22550PE` | **Agreed** |
| D3 | Keep paper trading; F&O overlay = `CONTROLLED_EXPERIMENT`; fix record linkage without changing strategy | **Agreed** |
| D4 | Future gate policy: intraday = provisional with explicit missing-evidence status; F&O = defer when fresh underlier or option LTP missing; swing = defer when critical evidence missing. Shadow first; not a change to the control strategy today | Recommended; thresholds and enforcement pending |
| D5 | Separate, versioned realistic-cost profile for evaluation only; chosen before evaluation; ledger unchanged | Recommended; configuration pending |
| D6 | `OI-DELI0` is the single tracker; link from `OPEN_ITEMS.md` and older plans | Recommended; link edits pending |

---

## 7. Status board

| Item | State |
|------|-------|
| F17 duplicate instance | contained 20:39 IST; systemd PID 1233554 only |
| Step 0A incident audit | **done** → [`docs/incidents/2026-10-12_DUPLICATE_INSTANCE_AUDIT.md`](incidents/2026-10-12_DUPLICATE_INSTANCE_AUDIT.md) |
| 0A remediations R1–R6 | R1=0B (gated); R2 operator SQL pending; R3 missed Hourly 19 optional; R4 watchdog with 0B; R5 receipt retention; R6 listening≠ownership |
| Step 1 NIFTY trace | **done** → [`docs/traces/2026-10-12_NIFTY26OCT22550PE_70109538.md`](traces/2026-10-12_NIFTY26OCT22550PE_70109538.md) + `.json`; `scripts/trace_trade.py`; 16 unit tests pass |
| Step 1 first blocking (NIFTY alone) | ACCOUNTING/`stored_realized_return_pct` CONFLICT(COMPUTATION); next DECISION_LINKAGE (HOLD≠BUY, exit decision null); then DECISION_EVIDENCE entry snapshot PERSISTENCE |
| Step 1B TRENT | **done** → [`docs/traces/2026-10-12_TRENT.NS_c8ce4b9e.md`](traces/2026-10-12_TRENT.NS_c8ce4b9e.md) + `.json` (decisions `e6180671…` / `97bdd505…`) |
| Step 1B swing | **done** → COALINDIA.NS entry **2026-09-24** / exit **2026-10-09** → [`docs/traces/2026-09-24_COALINDIA.NS_0d9a5313.md`](traces/2026-09-24_COALINDIA.NS_0d9a5313.md) + `.json` |
| Step 1B provisional compare | superseded by Step 3 decision (§9.6) |
| 0A R2 operator SQL | **still open** — journal shows no fills; that is not proof of no other DB writes |
| Step 2 P0.1 commit | **done** `d0f85aa` (§9.5); no restart; F18 limitation remains until P0.2 |
| Step 3 decision gate | **done** (§9.6) — shared first target = P0.4 lineage + order_intent; F&O linkage coupled; NIFTY return not shared-first |
| Step 0B single-instance protection | **live** — unit installed; MainPID=lock pid; `--manual` → exit 75; watchdog `ok`; L1–L6 + L3 shadow |
| P0.4 trade lineage | **shadow live after restart** — dir appears on first fill; committed in `d2375af` |
| P0.5 / P0.6 decision chain | **code ready** — exit mint + overlay BUY + sell→entry resolve from lineage; today's 10 experiment_close sells had exit ids but null entry (pre-fix); **operator restart to load** |
| P0.7 prediction + snapshot | **code ready** — `prediction_id` + by_id store; contract file is pointer; entry evidence snapshot under `lab_v1_entry_snapshots/`; lineage gets ref on fill | 
| F&O finite capital | **code ready** — max 2 open option experiments; 30% starting_cash reserve floor; `auto_top_up=false` hard; no operator infinite refill assumed |
| Post-gate deploy order | after 0B: Priority 1 P0.4 (in progress) → Priority 2 P0.5/P0.6 → Priority 3 entry snapshot + prediction id → Priority 4 P0.2/P0.3 |
| F13 HBLPOWER mark | not started (P1) |

---

## 8. Pre-trace inventory — `NIFTY26OCT22550PE` (read-only, 2026-10-12 20:20 IST)

Provisional until `trace_trade.py` reproduces it.

### 8.1 Identifiers

| Thing | Value | Store |
|-------|-------|-------|
| Lab / portfolio | `india_fno_learner` / `9f237a93-0945-4bcd-8309-d2eda576b4fa` | `sim.portfolios` |
| Entry fill | `70109538-b48c-4d03-a600-5e2482d606e1`, BUY 65 @ 264.50, 10:15:59.87 IST | `sim.trades` |
| Exit fill | `17b5cb05-a102-40c4-b5b3-35594405f127`, SELL 65 @ 342.95, 15:32:29.70 IST | `sim.trades` |
| Entry `decision_id` | `0cb0d567-2ee9-4a91-a564-e2adbd3b75fc` (engine HOLD NIFTY, created 10:15:51.02 IST) | `decision.decisions` |
| Exit `decision_id` | NULL | `sim.trades` |
| Experiment family | `FNO-ATM-NIF-001` — identifier only; no definition found (A16) | prediction + closed-loop row |
| Experience / story | `26b739c7…` / `20d26197…` | `investment/learning/india_fno_learner/2026-10-12.jsonl` |

### 8.2 Stores found

`sim.trades`, `decision.decisions`, `investment/fno/lab_v1_predictions/NIFTY26OCT22550PE.json`,
`investment/fno/packs/NIFTY_2026-10-12.json`, `investment/fno/lab_v1_integrity/2026-10-12.json`,
`investment/fno/closed_loop/india_fno_learner/2026-10-12.jsonl`,
`investment/learning/india_fno_learner/2026-10-12.jsonl`,
`investment/learning_audit/india_fno_learner/2026-10-12.json`,
`investment/fel/datasets/india_fno_learner/DS-E-paper-round-trip-india_fno_learner.jsonl`,
`investment/decisions/by_day/india_fno_learner/2026-10-12.jsonl`,
`investment/decisions/timeline/NIFTY26OCT22550PE.jsonl`,
`investment/thesis_tracker/market_intelligence/NIFTY26OCT22550PE.NS.json`,
`investment/research/market_intelligence/NIFTY26OCT22550PE.NS.json`,
`investment/switch_learning/india_fno_learner/by_id/*.json` (≈ 14),
`market/bars/_NSEI.json`, `logs/atlas.log` (rotates ≈ 10 MB, ~1–2 days).

### 8.3 Provisional verdicts (reclassified per §4.1/§4.4)

| Dimension / step | What the records show | Provisional status |
|------------------|-----------------------|--------------------|
| IDENTITY | One buy 65, one sell 65, same portfolio + contract + day; no other fills of this contract today | `OK` (to confirm) |
| ACCOUNTING | Realized +5,099.25 = 65 × (342.95 − 264.50); fees 0 both legs (zero-fee paper). Stored `realized_return_pct` 22.8751% = P&L ÷ exit notional 22,291.75; `roc.v1` = 29.66%. BANKNIFTY same pattern | P&L `OK`; return `CONFLICT(COMPUTATION)` |
| DECISION_LINKAGE (entry) | Fill → engine HOLD NIFTY (no packet for that engine id). Overlay BUY PE has no decision record; its rationale is only in the prediction file (`v1_buy_atm_pe`). Later packet `f0c639ed` (10:30) on the contract: hold / `lab_instrument_rejected` | `CONFLICT(LINKAGE)`; prediction file = historical overlay evidence only (A5) |
| DECISION_LINKAGE (exit) | Sell `decision_id` NULL; trigger in integrity file `fno_lab_v1_experiment_close`, `exit_policy=session_flat` | Exit decision `MISSING(LINKAGE)`; trigger `OK` from integrity file |
| DECISION_EVIDENCE | Pack overwritten each tick (current `as_of` 15:26:34 IST); entry snapshot gone; log 10:15:53 has no values. No order intent. IV/Greeks never captured. Daily session context exists (§4.4) | Entry snapshot, order intent, IV/Greeks `MISSING(PERSISTENCE)`; session context `OK` |
| Prediction | Recorded 10:15:53.78 IST, before the fill; E[R] 0.08, p 0.7, horizon `session_flat`, `fno_lab_v1_control_signal.v1`; same defaults on all 8 | Present; `prediction_type=rule_output`, `uncalibrated_default` |
| ATTRIBUTION | Stored `partial`, helped = `option_premium_path` (the outcome). LLM review REVIEWED, conf 0.85, circular; falsifiers untestable. Stored claim "no durable underlier session bar" is false | Trace classification `NOT_EVALUABLE` (no entry-to-exit path, no IV); `ATTRIBUTION` defects flagged; attribution-input lookup `LINKAGE` |
| LEARNING | Lesson "direction matched — thin sample"; no hypothesis; belief unchanged. FEL row features null though `sma_margin` stored | `MISSING(LEARNING)`; FEL features `MISSING(LINKAGE)` |
| Side records | Thesis tracker opened for `NIFTY26OCT22550PE.NS` as an equity (`long_term`, `idle`); 2 Yahoo 404 calls | `CONFLICT(LINKAGE)`; guard is a later task (A13) |

### 8.4 Provisional answer

**Both, plus one wrong link and one formula defect.** Captured but not connected: SMA
margin, prediction, session context, expiry/strike, exit trigger. Never captured:
entry-time snapshot, order intent, entry-to-exit underlier path, IV/Greeks, exit decision.
Wrongly linked: entry → engine HOLD. Formula defect: return denominator. Expected first
fix (to be confirmed at Step 3): decision linkage + entry-snapshot persistence.

---

## 9. Step-by-step implementation

### 9.1 Step 0A — Duplicate-instance window audit (read-only)

**Window:** 2026-10-12 18:36:19 → 20:39:17 IST.
**Output:** `docs/incidents/2026-10-12_DUPLICATE_INSTANCE_AUDIT.md`.
**Writes:** only the output doc. No restart.

| # | Check | Source | Question answered |
|---|-------|--------|-------------------|
| 1 | Boot count, PIDs, lifetimes, exit codes; which services each launch started | `journalctl -u atlas --since/--until` | How long each duplicate ran with live services |
| 2 | Log lines from non-main PIDs, grouped by logger | journal (has PID) vs `atlas.log` | What the duplicates actually did |
| 3 | Scheduler/task rows created, claimed, started, completed, abandoned in the window, by owner | task/schedule tables used by `atlas/repositories/task_repo.py`, `schedule_repo.py`, `recovery_repo.py` (read schema first) | Duplicate claims or orphaned tasks |
| 4 | `task_failures.jsonl` rows in the window | `investment/ops_health/` | New failures caused by duplicates |
| 5 | Mail: "email sent" lines; `market/investor_reports_sent.json` keys for 19:00/20:00 hourly and evening | log + journal + file | Duplicate or missed mails |
| 6 | Zerodha token-mail poller: IMAP polls, messages marked seen/processed, token writes | logs + token state files | Whether a duplicate consumed or altered mailbox state |
| 7 | DB writes: `sim.trades`, `sim.cash_movements`, `decision.decisions`, other tables with `created_at` in window | `psql` read-only | Side effects on ledgers/decisions |
| 8 | Data-dir files modified in the window | `find /data/atlas_data -newermt … ! -newermt …` | File-store side effects (learning, KPIs, notes) |
| 9 | Ops-health incidents/events in the window | `investment/ops_health/2026-10-12.json` | Whether self-diagnosis noticed |

Each check ends in: `no effect` / `effect found` (with records) / `cannot determine`
(with reason). **Exit condition:** all nine documented; any effect found gets a
remediation item in §7.

### 9.2 Step 1 — `scripts/trace_trade.py` and the NIFTY trace (read-only)

**Interface**

```text
.venv/bin/python scripts/trace_trade.py --trade-id <uuid>
    [--data-dir /data/atlas_data]
    [--out-md docs/traces/<ist_date>_<SYMBOL>_<entry_id8>.md]
    [--out-json docs/traces/<ist_date>_<SYMBOL>_<entry_id8>.json]
    [--include-logs]   # secondary evidence, LOG_ONLY
    [--strict]         # exit 1 on any critical non-OK cell (later CI)
```

Accepts entry or exit id. Without `--out-*`, prints Markdown.

**Read-only guarantees:** DB session `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`;
files opened read-only; output paths must be outside `--data-dir`; no network; no Atlas
runtime service, worker, mailer, or kernel imported (A14). Pure functions are testable
without importing Atlas runtime.

**Cell model**

```text
{ dimension, step, field, value, status, gap_class, blocked_by[], sources[], note }
sources[] = { kind: db|file|log, ref: "sim.trades:<id>" | "<relpath>#<json-pointer>",
              sha256, mtime_ist, original_ts, original_tz }
```

Every evidence reference records the file's content hash and mtime at trace time, and the
original timestamp + timezone (A11, A28). A record whose `as_of`/`mtime` is later than the
decision is reported as "later version", never as the decision-time evidence.

**Algorithm (in order)**

1. **Identity:** load the trade; load all fills of the same portfolio + symbol; build the
   round trip from trade ids and quantities. FIFO only when unambiguous; otherwise
   `AMBIGUOUS` with the candidates listed (A28).
2. **Accounting:** ledger values; recompute per §4.2; compare stored `realized_pnl`,
   `realized_return_pct`, KPI file, closed-loop row.
3. **Decision linkage:** `decision.decisions` for each fill's `decision_id`; packets in
   `decisions/by_day/<lab>/<day>.jsonl` and `decisions/timeline/<symbol>.jsonl` by
   `decision_id` / `engine_decision_id` / `fill_trade_id`; entry prediction (require
   `trade_id` = entry fill, else `CONFLICT(PERSISTENCE)` "overwritten"); exit trigger
   from `lab_v1_integrity/<day>.json` by exit trade id.
4. **Decision evidence:** pack `fno/packs/<UNDERLYING>_<day>.json` (later than entry →
   `MISSING(PERSISTENCE)` for the entry snapshot, stored copy shown as later version);
   instrument expiry/strike/lot; daily bar via alias table (`NIFTY → _NSEI | ^NSEI`,
   `BANKNIFTY → ^NSEBANK`, stock → `<SYM>.NS`) labelled session context with open-to-close
   and close-to-close both `CALCULATED`; intraday bars `market/bars_intraday/<sym>/<day>.json`
   for the entry-to-exit path; order intent; IV/Greeks.
5. **Attribution:** stored labels reported verbatim; trace assigns its own §4.1 state;
   mechanical flags only (outcome used as cause, untestable falsifier, false "missing"
   claim) (A12).
6. **Learning:** experience/story rows by trade id, closed-loop row, learning audit,
   FEL row, thesis tracker/research by symbol; hypothesis and test present?
7. **Logs** (`--include-logs`): matching lines, every value `LOG_ONLY` (A9).

**First-fix rule:** walk dimensions in order IDENTITY → ACCOUNTING → DECISION_LINKAGE →
DECISION_EVIDENCE → ATTRIBUTION → LEARNING. Each non-OK cell lists `blocked_by` (upstream
cells that make it unassessable). The first fix is the **earliest blocking dependency
shared by the affected trades** across all traces (decided at Step 3), not the class with
the most cells.

**Output:** header (trade, lab, generated_at IST, script version, git sha), cell table by
dimension, gap summary (counts by status × class × dimension), first blocking dependency,
raw sources with hashes. JSON mirrors it with sorted keys.

**Tests** — `tests/test_trace_trade.py`, fixtures under `tests/fixtures/trace/`

| # | Test | Expectation |
|---|------|-------------|
| T1 | Golden NIFTY fixture (sanitised copies) | entry decision `CONFLICT(LINKAGE)`; exit decision `MISSING(LINKAGE)`; entry snapshot `MISSING(PERSISTENCE)`; session context `OK` with o2c −1.21% and c2c −1.02% `CALCULATED`; entry-to-exit move `MISSING(PERSISTENCE)`; return `CONFLICT(COMPUTATION)`; attribution `NOT_EVALUABLE` |
| T2 | Synthetic fully-linked trade | no non-OK cells; no first fix |
| T3 | All optional stores absent | all `MISSING`, no exception |
| T4 | Prediction `trade_id` ≠ entry | `CONFLICT(PERSISTENCE)` "overwritten" |
| T5 | Pack `as_of` after entry | entry snapshot `MISSING(PERSISTENCE)`; stored copy shown as later version |
| T6 | Return | `roc.v1` 29.66% `CALCULATED`; stored 22.8751% `CONFLICT(COMPUTATION)` |
| T7 | Read-only | fixture hashes/mtimes unchanged; fake DB records no writes; output inside data dir refused |
| T8 | Determinism | identical bodies across runs |
| T9 | Pairing | entry and exit ids resolve to the same round trip; 2 buys + 1 sell unambiguous FIFO |
| T10 | Ambiguous pairing | two equal-size re-entries with no ids linking them → `AMBIGUOUS`, candidates listed, no silent choice |
| T11 | Aliases | `NIFTY` → `_NSEI`; unknown underlier → `MISSING(PERSISTENCE)` listing aliases tried |
| T12 | Evidence refs | every source has sha256 + mtime + original ts/tz |
| T13 | Attribution states | fixtures for each of the 4 states classify correctly; profit does not change the state |
| T14 | First-fix | missing identity blocks accounting cells (`blocked_by`), and first fix = identity |
| T15 | Accounting semantics | sell `realized_pnl` treated as exit-fee net; entry fee allocated once in `round_trip_net`; no double subtraction |
| T16 | CLI | `--help`; unknown id → exit 2 with message |

**Live acceptance:** run after 15:45 IST · hand-verify ≥ 5 cells (commands in the doc
appendix) · snapshot `find /data/atlas_data -newer <marker>` before/after shows no writes ·
trace doc reproduces or corrects every row of §8.3.

### 9.3 Step 1B — TRENT and swing traces

TRENT round trip `e6180671…` (buy) / `97bdd505…` (sell). Swing: the most recent **closed**
equity-swing round trip, with its actual trade date recorded (A15). Same script, same
acceptance. Where a field is not applicable to the strategy (e.g. IV for cash equity),
`NOT_APPLICABLE` with reason.

### 9.4 Step 0B — Single-instance protection (`OI-OPS-1INST`)

**Sub-steps**

1. **Side-effect inventory (doc, no code):** list every component that claims tasks,
   trades, sends mail, or changes external state (IMAP, Zerodha session), whether it runs
   in-process, and which connection it uses. Output appended to this section. This fixes
   the final L3 service list.
2. **Read the serve path** (`atlas/cli/main.py` serve, `atlas/kernel/application.py`) and
   document how uvicorn is started, to confirm L2 can pass a pre-bound socket. If not
   possible, document the alternative before coding.
3. Implement in rollout order: L6 detection → L4 unit → L1 lock → L2 pre-bound socket →
   L5 manual policy → L3 per-service locks (shadow: log "would be passive" for 3 sessions)
   → L3 enforce → L7 idempotency tests.
4. Operator installs the unit and restarts via `systemctl` after 15:45 IST; run the drill.

**Tests** — `tests/test_instance_lock.py`, `tests/test_serve_boot_order.py`,
`tests/test_service_locks.py`, `tests/test_side_effect_idempotency.py`

| # | Test | Expectation |
|---|------|-------------|
| I1 | Two L1 acquisitions in separate processes | second fails fast with holder info |
| I2 | Holder SIGKILLed | lock re-acquirable immediately |
| I3 | Lock file identity | inode unchanged across acquire/release/restart; never unlinked |
| I4 | `serve` with lock held | exit 75; kernel `start()` never called |
| I5 | Boot order | socket bound before schedules/workers start |
| I6 | Socket already bound by another process | exit 75 before any service starts |
| I7 | Per-service DB lock | second instance of the same service cannot acquire its key and stays passive; different services do not block each other |
| I8 | Lock connection lost | owning service stops side effects, attempts reacquire, raises incident |
| I9 | Side effect outside owner | attempting a fill/mail/claim from a component that does not own the service lock is rejected |
| I10 | Unit file | `RestartPreventExitStatus=75`, `StartLimitIntervalSec`, `StartLimitBurst` present |
| I11 | Watchdog | 2 processes → P0; L1 pid ≠ MainPID → P0; L3 key held by other pid → P0 |
| I12 | Manual / override | no `INVOCATION_ID` and no `--manual` → refuse; `--manual` still locked; override disables only L1, logs CRITICAL, watchdog P1 |
| I13 | Idempotency | duplicate tick → one fill; duplicate hourly/evening mail → one send |

**Operator drill (after 15:45 IST, results in §13):** `systemctl restart atlas` → one
process, lock shows MainPID · start `atlas serve --manual` → exit 75, no "starting
service: schedules" from it · `kill -9 <MainPID>` → one restart, lock re-acquired ·
watchdog clean; fake second process → incident.

**Done when:** inventory documented, I1–I13 pass, drill passes, one full session with a
single instance confirmed by the watchdog.

#### 9.4.1 Side-effect inventory (Step 0B.1 — recorded 2026-10-12)

All of the following run **in-process** under one `atlas serve` (no separate daemons
except the external `atlas-ops-watchdog.timer`). Connection = Postgres unless noted.

| Component | Registry / entry | Claims tasks / ticks | External / durable side effects | L3 candidate |
|-----------|------------------|----------------------|---------------------------------|--------------|
| **scheduler** | `SchedulerService` (`registry` name `scheduler`) | Yes — `claim_next` + recover interrupted | `scheduler.tasks` / `task_runs`; handler execution | **Yes** (key `atlas.svc.scheduler`) |
| **schedules** | `ScheduleService` (`schedules`) | Enqueues due work via `schedule_tick` | Schedule rows; enqueues into scheduler | **Yes** (key `atlas.svc.schedules`) — distinct from claim loop |
| **workers** | `WorkerManager` (`workers`) | `worker_tick` → per-type workers | Starts/pauses worker rows; dispatches ticks | **Yes** (key `atlas.svc.workers`) — umbrella for worker side effects |
| **paper_trading** | `PaperTradingWorker` via workers | Lab ticks | `sim.trades` / positions / cash; trade + F&O experience mail | Covered by **workers** lock + fill path must re-check ownership (L7) |
| **investor_reports** | `InvestorReportsWorker` + `InvestorReportMailer` | Worker tick / schedules | SMTP morning/hourly/evening; sent-receipts JSON | **Yes** as mail owner (key `atlas.svc.investor_mailer`) — F17 proved duplicate send |
| **zerodha_token_email** | `maybe_poll_zerodha_token_email` from provider-health tick | Via `provider_health_tick` → schedules/scheduler | IMAP poll; `complete_login`; pending JSON under data dir | **Yes** (key `atlas.svc.zerodha_token_mail`) |
| **recovery** | `RecoveryManager` (`recovery`) | On boot | `system.recovery_runs`; resets interrupted work | **Yes** (key `atlas.svc.recovery`) — F17: 172 recovery cycles |
| **notifier** | `notifier` | On demand from mailer/ops | SMTP | Share **investor_mailer** ownership or nest under it (same SMTP identity) |
| **backup** | `BackupManager` | `backup` task | `pg_dump` / backup files | **Yes** (key `atlas.svc.backup`) — rare but not safe to double |
| **ingestion** / **candidates** | `ingestion_source`, `candidate_consumer` | Tasks | Knowledge/asset writes | Defer L3 enforce; shadow-log in first rollout (not F17 primary) |
| **health_monitor** | last registered | Interval checks | Health rows only | No L3 (read/observe) |
| **API routes** | FastAPI after bind | N/A | Can trigger mail/login via HTTP | Must refuse side effects if process lacks the relevant L3 lock |

**Final L3 service list (for implement + I7):**

1. `atlas.svc.scheduler`
2. `atlas.svc.schedules`
3. `atlas.svc.workers`
4. `atlas.svc.investor_mailer`
5. `atlas.svc.zerodha_token_mail`
6. `atlas.svc.recovery`
7. `atlas.svc.backup`

Paper-trading fills execute only under `workers` ownership; mail sends only under
`investor_mailer`; IMAP/token completion only under `zerodha_token_mail`.

#### 9.4.2 Serve / uvicorn path (Step 0B.2 — recorded 2026-10-12)

**Call chain today**

1. `atlas serve` → `atlas.cli.main.cmd_serve` → `atlas.api.serve(host, port)`.
2. `serve()` (`atlas/api/server.py`): `build_application()` (construct only — **no**
   `start()`), `create_app(application)`, logs **"Atlas API listening on …"** (before
   any bind — F17 R6), then `uvicorn.run(app, host=…, port=…)`.
3. FastAPI lifespan (`atlas/api/app.py`): on startup `application.start()` →
   `lifecycle.start_all()` (registration order: clock → database → **recovery** → … →
   **scheduler** → … → **schedules** → **workers** → … → health_monitor) →
   "Atlas is ready".
4. Uvicorn then binds the listening socket. On collision: `Errno 98` **after** services
   have already started (F17 pattern).

**L2 feasibility:** **Yes**, without replacing uvicorn. Installed uvicorn **0.51.0**
exposes `uvicorn.run(..., fd=…)` and `Server.run(sockets=[…])`. Required change:

1. In `serve()`, **before** `uvicorn.run` / `Server.run`: create socket, `bind`+`listen`;
   on failure log holder hint and **exit 75** (no `application.start()`).
2. Pass the pre-bound socket via `fd=` or `sockets=` so uvicorn does not bind again.
3. Remove or move the premature "listening" log to **after** successful bind.
4. Lifespan may still call `application.start()` after our bind; that is safe because the
   losing instance never gets past step 1.

Alternative (not preferred): start the kernel only after uvicorn reports bind — harder
with current lifespan and unnecessary once the socket is pre-bound.

**L1/L4/L5 notes tied to this path:** L1 flock must be acquired in `serve()` (or
`cmd_serve`) **before** bind and before any start; systemd unit still lacks
`RestartPreventExitStatus=75` / start-limit (L4); CLI has no `--manual` / `INVOCATION_ID`
gate yet (L5).

### 9.5 Step 2 — Isolated P0.1 commit

1. `git diff` the four files; identify today's hunks (`_add_cash_and_pnl_metrics`;
   `build_trading_kpis` day-P&L + day fees; ledger endpoint day-P&L block; 2 new tests).
2. Create a temporary worktree at HEAD; apply only those hunks there; run
   `tests/test_day_pnl_round_trip.py tests/test_trading_kpis.py tests/test_lab_book_visibility.py
   tests/test_outage_resilience_reports.py tests/test_evening_learned_today.py`.
3. If they fail because of unrelated uncommitted code: **stop**, document the minimum
   prerequisite hunks here, and ask before including them (A2). Never stage whole files.
4. Stage the same hunks in the main tree with `git add -p`; verify `git diff --cached`
   equals the worktree patch.
5. Commit `OI-DELI0 P0.1: day P&L from full IST ledger; day fees not lifetime`; record
   sha and the F18 limitation in §13. No restart.

### 9.6 Step 3 — Decision gate (recorded 2026-10-12)

Inputs: three trace docs + 0A audit. **No code in this step.**

#### 9.6.1 What the three traces establish

| Dimension | NIFTY26OCT22550PE | TRENT.NS | COALINDIA.NS |
|-----------|-------------------|----------|--------------|
| Identity | OK | OK | OK |
| Accounting P&L | OK: +₹5,099.25 | OK: −₹17.80 | OK: −₹280.25 |
| Accounting return | CONFLICT: stored 22.8751% vs roc.v1 29.66% | No stored F&O return field; N/A | N/A |
| Decision linkage | CONFLICT: engine HOLD linked to BUY; exit decision missing | Decisions linked; entry decision packet missing | Entry and exit decisions linked |
| Decision evidence | Entry snapshot overwritten; order intent missing | Order intent missing | Order intent missing |
| Attribution | NOT_EVALUABLE | No validated causal explanation | No validated causal explanation |
| Learning | No defined, validated hypothesis | No validated lesson | No validated lesson |

#### 9.6.2 Shared vs trade-specific

| Kind | Finding | Role in first-fix choice |
|------|---------|---------------------------|
| Trade-specific COMPUTATION | NIFTY stored return denominator | Confirmed; **not** the shared first fix |
| F&O-specific LINKAGE | HOLD presented as BUY rationale; null exit decision | Closely coupled defect; Priority 2 with P0.5/P0.6 |
| **Shared PERSISTENCE** | **`order_intent` missing on all three** | **Strongest common implementation target** |
| Downstream LEARNING | No validated hypothesis/test on all three | Remains after reliable decision + evidence records |

Governing rule restated: an outcome is not its own explanation; recorded activity is not
demonstrated learning. Select the earliest **shared** blocking dependency, not the
dimension with the most cells.

#### 9.6.3 Decision (locked)

**Prioritize durable trade-lineage and order-intent persistence (P0.4), treating F&O
decision linkage (P0.5/P0.6) as a closely coupled defect. Do not prioritize the NIFTY
return-formula defect as the shared first fix.**

#### 9.6.4 Post-gate implementation priorities

| Priority | Work | Why |
|----------|------|-----|
| **1** | **P0.4** `trade_lineage` in shadow: entry decision, overlay decision, parent decision, **order intent**, fill, exit decision + reason, prediction id, entry-evidence snapshot ref (+ content hash) | Shared gap across all three traces; also the structure that makes F&O ownership unambiguous |
| **2** | **P0.5** exit decision on every sell path; **P0.6** F&O overlay own decision + engine as parent + `CONTROLLED_EXPERIMENT` | Fixes NIFTY-class linkage without changing control behaviour |
| **3** | Entry-evidence snapshot persistence + prediction identity (P0.7) | Especially NIFTY overwritten pack; keep historical predictions across re-entries |
| **4** | **P0.2 / P0.3** accounting module + reconciliation, including NIFTY return via `roc.v1` and F18 non-zero-fee regression | Keep on the remediation list; not dismissed because it is not shared-first |

Causal learning / validated-lesson promotion stay **downstream** of these integrity fixes.

#### 9.6.5 P0.4 acceptance (aligned with §4.3)

1. Every **new** trade has the required lineage records, **or** a detectable integrity failure.
2. An engine HOLD is **never** presented as the rationale for an overlay BUY.
3. Missing order intent is reported explicitly; **never** reconstructed from the eventual outcome.
4. A lineage-write failure does **not** block a fill; the trade is marked `lineage_incomplete` and surfaces in reconciliation and EOD reporting.
5. No change to the trading strategy / control rule behaviour.

#### 9.6.6 Next sequence after this gate

1. **Step 2** — **done** (`d0f85aa`); isolated P0.1 commit; no restart.
2. **Step 0B** — single-instance protection; operator `systemctl` restart; drill.
3. **Only then** deploy Priority 1→4 under shadow → enforce, per §2.

R2 remains open until operator read-only SQL for the F17 window completes.

### 9.7 Step 4a — P0.2 accounting module

`atlas/trading/pnl_truth.py` implementing §4.2 (`acct.v1`, `roc.v1`), returning ledger
values, calculated checks, components, unknown components, marks used (source + age),
trade ids used. Consumers switch one at a time after ≥ 3 sessions of shadow diffs: KPI
builder → evening mail → ledger API → fill-mail lab books → learning outcome. Remove the
`routes.py` formula afterwards. Fixes F18.

Tests (`tests/test_pnl_truth.py`): flat same-day round trip · overnight hold · partial
close (pro-rata entry fee) · multiple entries (avg-cost allocation) · > 10 fills · entry
fee on day 1, exit on day 2 (fees stay on their days) · zero-fee profile · non-zero fee
profile (no double subtraction; F18 regression) · open position without mark → component
`UNKNOWN`, `day_pnl` partial · index-proxy lot · NIFTY fixture `roc.v1` 29.66% · all
consumers equal on one fixture.

### 9.8 Step 4b — P0.3 reconciliation

`atlas/trading/reconcile.py` → findings per lab/day: ledger realized vs Σ sell
`realized_pnl` · KPI / mail / API vs `pnl_truth` · learning trade ids ⊆ ledger · experience
P&L = round trip · fees on fill day · each closed round trip has an experience or a stated
reason · `lineage_incomplete` trades (§4.3). Runs after 15:45 IST and before the evening
mail; writes `investment/integrity/reconcile/<lab>/<day>.json`. Shadow: appendix only.
Enforce: section A prints `RECONCILIATION FAILED: <field> <a> vs <b>`.

Tests (`tests/test_reconcile.py`): passing fixture; one failing fixture per check with its
own finding code; 2026-10-12 pre-fix state (KPI null, mail 1,822.50) produces findings.

### 9.9 After the gate — ordered candidates (Step 3)

| Order | Candidate | Summary | Test focus |
|-------|-----------|---------|------------|
| **1** | Lineage + order intent (P0.4) | Shadow `trade_lineage`; never block fill; §4.3 on write failure | New fills have lineage or integrity failure; HOLD never shown as overlay BUY reason |
| **2** | Exit + overlay decisions (P0.5, P0.6) | Every sell gets exit decision; F&O overlay own id + parent + CONTROLLED_EXPERIMENT | Each exit path non-null id; mail/learning use overlay reason |
| **3** | Entry snapshot + prediction id (P0.7) | Persist decision-time pack snapshot; predictions by `prediction_id` | Snapshot `as_of` ≤ fill; re-entry keeps both predictions |
| **4** | Accounting + reconcile (P0.2, P0.3) | `pnl_truth` + reconcile; fix return via `roc.v1`; F18 fee invariant | NIFTY 29.66%; non-zero-fee fixture; consumers equal |
| later | Attribution-input alias fix | Session context via alias table | Labelled o2c/c2c; state unchanged without entry-to-exit evidence |
| later | Instrument-class guard | Skip NFO as equity in research/thesis | No `.NS` lookups for options |

---

## 10. Documentation protocol

1. **Implementation log (§13):** per step — time IST, step, files, why, tests and results,
   deploy time or "not deployed", smoke result, flag state, commit sha.
2. **Status board (§7)** updated in the same edit.
3. **Traces** in `docs/traces/`, incidents in `docs/incidents/`, Markdown + JSON.
4. **Commits** small, one step each, prefix `OI-DELI0 <step>:`.
5. **Deviations:** edit the plan first with "changed because …", then the code.

## 11. Per-step continuity checklist

Before deploy: Step 0B done · tests green · change is reporting-only or flagged `shadow`/`off`
· after 15:45 or before 08:45 IST · operator restarts via `systemctl` · no open intraday
position (or flatten verified).
After deploy (next session): §2.7 smoke · watchdog single-instance clean · reconciliation
(once live) shows no new finding caused by the change. Regression → flag `off`, log, debug
offline.

---

## 12. Ambiguity register (locked)

| ID | Decision | Clarification |
|----|----------|---------------|
| A1 | `CONFLICT`/`AMBIGUOUS` are statuses; gap classes per §4.1 | Documented enum; `COMPUTATION` added as a cause class because a wrong formula is neither persistence nor linkage |
| A2 | Isolate P0.1 in a temporary worktree | If it depends on unrelated changes: stop, document minimum prerequisite, ask. Never stage whole files |
| A3 | `sim.trades.realized_pnl` is authoritative; recomputation is a check | Semantics verified (F18): exit-fee net, entry fees excluded. Never double-subtract |
| A4 | Return denominator = entry cost incl. allocated entry fees (`roc.v1`) | Avg-cost, pro-rata allocation for partial exits and multiple entries |
| A5 | Prediction file = historical overlay evidence only | Future F&O trades require a real overlay decision record; engine decision is parent/context |
| A6 | Missing order intent stays missing | Derived values may be `CALCULATED` context, never persisted intent |
| A7 | No spot from strike | Strike is identity/context, not a quote |
| A8 | Daily bar = session context | Not the entry-to-exit path; label o2c vs c2c explicitly |
| A9 | Logs are secondary | `LOG_ONLY`; never sole proof |
| A10 | Report prediction time and fill time | Prediction = decision-time forecast; fill = execution entry |
| A11 | Normalise to IST ISO-8601 | Keep original timestamp + tz in the source record |
| A12 | LLM review reported verbatim | Mechanical flags only; no truth grading from wording |
| A13 | Record option-as-equity error now | Guard implemented later, separate from the trace |
| A14 | Trace lives in `scripts/` | Pure functions testable without Atlas runtime imports |
| A15 | Third trace = most recent closed swing round trip | Record its actual date |
| A16 | `FNO-ATM-NIF-001` = identifier only | Find its generator in Step 1; until then not a defined experiment |
| A17 | Zero-fee ledger kept as accounting contract | Separate versioned realistic-cost profile for evaluation; zero-fee results labelled as such |
| A18 | Lock at `/data/atlas_data/run/atlas.lock` | Verified local ext4, `jagd`-owned, in unit `ReadWritePaths`; never unlink/replace while possibly held |
| A19 | Manual serve needs `--manual` + same locks | Manual mode never bypasses singleton checks |
| A20 | Agents request operator restarts | A narrow privileged restart mechanism only after scope and authorisation are verified |
| A21 | Read-only jobs may run independently | Anything that starts workers, claims work, trades, or mails needs the singleton rules |
| A22 | No scheduler-owned global lease | Per-service locks on each service's own connection (§4.6) |
| A23 | Prediction contract §4.1 | Rule output ≠ forecast; p=0.7 not a probability until calibrated |
| A24 | Per-strategy, per-field freshness rules | No universal threshold; F&O underlier + option LTP critical, IV optional but visible |
| A25 | Failed lineage write → §4.3 five-step handling | Retry repairs only from sufficient source data |
| A26 | Process / forecast / economic quality kept separate | Prevents learning from luck |
| A27 | Pre-registration per hypothesis | No universal thresholds; failed findings recorded, not discarded |
| A28 | Stable ids + quantities for pairing; content hashes on evidence | Ambiguity reported, never resolved silently; later versions never mistaken for decision-time evidence |
| A29 | Completeness metrics with explicit populations (§4.5) | "100%" never excludes unlinked records |

**Still open (do not block 0A/1/1B):** D4 thresholds, D5 cost profile values, D6 link
edits, A16 generator, final L3 service list (Step 0B inventory), uvicorn pre-bound socket
feasibility (Step 0B sub-step 2).

---

## 13. Implementation log

| When (IST) | Step | Change | Tests | Deploy | Commit |
|------------|------|--------|-------|--------|--------|
| 2026-10-12 18:36 | (pre-plan) day-P&L fix | `investor_reports.py`, `trading_kpis.py`, `routes.py`, `tests/test_day_pnl_round_trip.py`; today's KPI files rewritten | 23 passed | Manual kill + `atlas serve` by agent (caused F17) | uncommitted |
| 2026-10-12 20:20 | §8 inventory | none (read-only) | — | — | — |
| 2026-10-12 20:39 | F17 containment | Hand-started PID 853080 stopped (SIGTERM). systemd PID 1233554 sole instance, `active (running)`, port 8000, `/etc/atlas/atlas.env` loaded | `ps`, `ss`, `systemctl status` | — | — |
| 2026-10-12 20:50 | Review #2 applied | Plan rewritten: execution order, locked contracts §4, ownership model, ambiguity register A1–A29; F18 fee semantics verified from `apply_trade`; lock path verified | — | — | — |
| 2026-10-12 21:05 | Step 0A | `docs/incidents/2026-10-12_DUPLICATE_INSTANCE_AUDIT.md`; F18 no-double-subtract invariant recorded in §4.2 | journal + files read-only; DB checks cannot determine from agent netns | not deployed | — |
| 2026-10-12 21:15 | Step 1 | `scripts/trace_trade.py`; `tests/test_trace_trade.py` (16 passed); traces `2026-10-12_NIFTY26OCT22550PE_70109538.{md,json}`; read-only dump `docs/traces/_db_dump/`; A16 generator found (`experiment_family_id`) | 16 passed; 5 hand-verifies PASS; data-dir newer-count 0 | not deployed | — |
| 2026-10-12 21:25 | Step 1B | TRENT + COALINDIA traces; cash-equity NOT_APPLICABLE for IV/pack/prediction; dumps `docs/traces/_db_dump/{trent,swing}/` | tests still 16 passed; 5+5 hand-verifies PASS; data-dir newer 0 | not deployed | — |
| 2026-10-12 21:30 | Step 3 | Decision gate recorded §9.6: shared first = P0.4 lineage/order_intent; F&O linkage coupled (P0.5/P0.6); NIFTY return not shared-first; exec order 2→3→0B→deploy | — | not deployed | — |
| 2026-10-12 21:35 | Step 2 | Isolated P0.1 via temp worktree + hunk patch: `_add_cash_and_pnl_metrics` (full day ledger + same-day realized fallback + `fees_paid_today`); `build_trading_kpis` day P&L/fees; ledger endpoint day P&L; 2 tests. Excluded unrelated `skip_live_marks` / nightly cognition / Yahoo gate. **F18:** flat-book Σ sell `realized_pnl` still omits entry fees — correct under zero-fee `paper_demo`; wrong under fees until P0.2 | worktree: 20 passed (`day_pnl`, `trading_kpis`, `outage_resilience_reports`, `evening_learned_today`); `lab_book_visibility` needs unrelated `skip_live_marks` (not included; A2 not triggered) | not deployed; no restart | `d0f85aa` |
| 2026-10-12 21:45 | Step 0B.1–0B.2 | Side-effect inventory → final L3 list (scheduler, schedules, workers, investor_mailer, zerodha_token_mail, recovery, backup); serve path docs — L2 feasible via pre-bound socket + uvicorn `fd`/`sockets` (0.51.0); current order starts services before bind | read-only code path | not deployed | — |
| 2026-10-12 21:55 | Step 0B.3 | L1 flock (`atlas/ops/instance_lock.py`); L2+L5 (`serve_boot.py` + `api/server.py` pre-bind before lifespan); L3 shadow manager + wire scheduler/schedules/workers/recovery/backup/mailer/zerodha; L4 unit `RestartPreventExitStatus=75` + start limits; L6 watchdog multi-instance / lock-pid / errno98 / override-P1; CLI `--manual` | 21 passed: `test_instance_lock`, `test_serve_boot_order`, `test_service_locks`, `test_ops_watchdog_l6`, `test_side_effect_idempotency` | **not deployed**; no restart; L3 default `ATLAS_SERVICE_LOCK_MODE=shadow` | committed `e07c636` |
| 2026-10-12 22:05–22:14 | Step 0B drill | Operator `install.sh` + restart; lock pid=MainPID; `--manual` → 75; watchdog false-positive fixed (sandbox argv); early L1 before `build_application` | operator drill PASS; watchdog `{"ok": true}` | **live** | committed `e07c636` |
| 2026-10-12 22:20 | P0.4 shadow | `atlas/investment/trade_lineage.py`; `Portfolio.apply_trade` always shadow-writes lineage (or write_failure); paper path builds `order_intent` before fill; demotes engine HOLD linked as BUY entry to parent; paths under `investment/trade_lineage/` + `integrity/` | 6 passed `test_trade_lineage_p04` | restart 22:21 loaded code; dir awaits first fill | `d2375af` |
| 2026-10-12 22:30 | P0.5 / P0.6 | `decision_chain.py`: mint overlay BUY (parent=engine, CONTROLLED_EXPERIMENT) + mint exit decision; wired on main paper fill, eod_flatten, experiment_close | 3+6 passed `test_decision_chain_p05_p06` + lineage | **restart to load** | committed `d6b1203` |
| 2026-10-13 18:25 | P0.5 entry link | `resolve_open_entry_from_lineage`; wire experiment_close / eod_flatten / main sell; sell validate flags `missing_entry_decision_id` (no longer silenced); exit mint gets `parent_decision_id=entry` | 6+5 passed `test_trade_lineage_p04` + `test_decision_chain_p05_p06` | **operator restart to load**; do not backfill today's sells | committed `d6b1203` |
| 2026-10-13 18:40 | P0.7 + capital | `prediction_id` + by_id immutable store; contract pointer; entry snapshot; capital budget max_open=2 + 30% starting reserve; auto_top_up never | `test_fno_lab_v1` capital + prediction_id tests | **operator restart**; F&O book stays finite (~₹85.7k after −₹64.5k day) | committed `d6b1203` |
| 2026-10-13 19:30 | Incident: lab starvation + post-close F&O flatten | Host Guard hg.1.4 market-critical lane (paper_trading/portfolio_ledger 09:00–16:00 IST: 128 MB need vs 2048 MB floor); F&O flatten from 15:20; `exit_learning_eligibility` stamps after-close exits ineligible; `learning_quarantine` manifest + FEL filter; today's 10 F&O experiences quarantined (ledger untouched, FEL 49→39) | host_guard + fno_lab_v1 tests; no regressions vs HEAD on sampled suite | **operator restart**; see `docs/incidents/2026-10-13_LAB_STARVATION_AND_POST_CLOSE_FNO_FLATTEN.md`, `docs/2026-10-13_LAB_OPERATIONS_AND_LEARNING_REVIEW.md` | committed `8057120`; **live** (restart on `d9a99a9`) |
| 2026-10-13 19:45 | Operator decisions + capital reserve | Keep F&O cash ₹85.7k (no deposit/reset); quarantine 137 HBLPOWER 2026-09-21 swing churn rows (FEL 137→10); reserve base = max(starting, net contributed) | fno_lab_v1 capital tests | live | `ca84377`, `d9a99a9` |
| 2026-10-13 20:00 | F&O shadow trades + evening section | Counterfactual entries for capital/cash-blocked BUYs on READY packs; closed on the 15:20 clock; separate store, never learning | `test_fno_shadow` | **operator restart** | `1afa1e2`, `f8bdd69` |
| 2026-10-13 20:10 | Held-option managed exits + operator risk file | premium stop / reversal / optional target per tick; no same-day re-entry; all values in `investment/fno/lab_v1_risk_settings.json` (bounded, read per tick) | `test_fno_managed_exit` | **operator restart** | `9506ab2`, `259649e` |
| 2026-10-13 20:40 | Ops alerting | F&O worker incident verifies only on a pack written after it opened; per-lab admitted/deferred tick ledger + P0 `lab:<lab>:ticks` after 20 min; no self-resolve at close | `test_ops_health_loop0`, `test_lab_ticks` | **operator restart** | `05e7286`, `27c4890` |
